"""AST-based repository analysis for Python, including calls, routes and common DB/framework signals.

PythonAnalyzer is one adapter behind the LanguageAnalyzer interface in app.services.code_units; it emits
canonical CodeUnit records alongside the legacy FunctionFact list used by the graph and risk services."""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from pathlib import Path
from app.models.schemas import CallSite, CodeUnit, FunctionFact, ParseStatus, UnitType
from app.services.code_units import EXCLUDED_DIRS, AnalysisContext, assign_unit_ids, excerpt, split_lines

EXCLUDED = EXCLUDED_DIRS
FILE_SOURCE_LIMIT = 20_000


@dataclass
class FileAnalysis:
    path:str
    language:str="Python"
    imports:list[str]=field(default_factory=list)
    functions:list[FunctionFact]=field(default_factory=list)
    classes:list[dict]=field(default_factory=list)
    endpoints:list[dict]=field(default_factory=list)
    database_entities:list[dict]=field(default_factory=list)
    framework_components:list[dict]=field(default_factory=list)
    units:list[CodeUnit]=field(default_factory=list)
    exports:list[str]=field(default_factory=list)
    parse_status:ParseStatus=ParseStatus.OK
    parse_error:str|None=None


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self): self.score=1
    def generic_visit(self,node):
        if isinstance(node,(ast.If,ast.For,ast.AsyncFor,ast.While,ast.ExceptHandler,ast.With,ast.AsyncWith,ast.IfExp,ast.comprehension)): self.score+=1
        if isinstance(node,ast.BoolOp): self.score+=max(0,len(node.values)-1)
        super().generic_visit(node)


def dotted_name(node):
    if isinstance(node,ast.Name): return node.id
    if isinstance(node,ast.Attribute):
        parent=dotted_name(node.value); return f"{parent}.{node.attr}" if parent else node.attr
    return None


def call_sites(node)->tuple[list[CallSite],list[str]]:
    """Calls in syntactic source order; calls on non-name expressions are reported as uncertainty."""
    found=sorted((c for c in ast.walk(node) if isinstance(c,ast.Call)),key=lambda c:(c.lineno,c.col_offset))
    sites,unresolved=[],0
    for call in found:
        name=dotted_name(call.func)
        if name: sites.append(CallSite(name=name,line=call.lineno,order=len(sites)))
        else: unresolved+=1
    return sites,([f"{unresolved} call(s) on dynamic expressions not resolved"] if unresolved else [])


def function_fact(node,path,owner=None):
    calls=sorted({name for call in ast.walk(node) if isinstance(call,ast.Call) for name in [dotted_name(call.func)] if name})
    visitor=ComplexityVisitor(); visitor.visit(node)
    args=[a.arg for a in node.args.posonlyargs+node.args.args+node.args.kwonlyargs]
    if node.args.vararg: args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg: args.append(f"**{node.args.kwarg.arg}")
    return FunctionFact(qualified_name=f"{owner}.{node.name}" if owner else node.name,name=node.name,file_path=path,
        line_start=node.lineno,line_end=getattr(node,"end_lineno",node.lineno),parameters=args,
        return_type=ast.unparse(node.returns) if node.returns else None,docstring=ast.get_docstring(node),
        decorators=[ast.unparse(d) for d in node.decorator_list],calls=calls,complexity=visitor.score)


def _signature(node)->str:
    prefix="async def" if isinstance(node,ast.AsyncFunctionDef) else "def"
    returns=f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def _span(node)->tuple[int,int]:
    """One-based inclusive span, widened to include decorators so the excerpt is the full definition."""
    start=min([node.lineno,*[d.lineno for d in getattr(node,"decorator_list",[])]])
    return start,getattr(node,"end_lineno",node.lineno) or node.lineno


class PythonAnalyzer:
    language="Python"
    extensions=frozenset({".py"})

    def analyze_file(self,absolute_path:Path,relative_path:str,context:AnalysisContext|None=None)->FileAnalysis:
        context=context or AnalysisContext()
        result=FileAnalysis(path=relative_path)
        try:
            text=absolute_path.read_text(encoding="utf-8")
            tree=ast.parse(text,filename=relative_path)
        except (SyntaxError,UnicodeDecodeError,ValueError) as exc:
            result.parse_error=str(exc); result.parse_status=ParseStatus.FAILED; return result
        lines=split_lines(text)
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imports.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom): imports.append(node.module or ".")
        result.imports=sorted(set(imports))
        explicit_all=self._explicit_all(tree)
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                result.functions.append(function_fact(node,relative_path))
                result.units.append(self._function_unit(node,relative_path,lines,result.imports))
                self._extract_endpoint(node,result)
            elif isinstance(node,ast.ClassDef):
                bases=[ast.unparse(b) for b in node.bases]
                method_nodes=[m for m in node.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef))]
                methods=[function_fact(m,relative_path,node.name) for m in method_nodes]
                result.classes.append({"name":node.name,"bases":bases,"line":node.lineno,"methods":[m.qualified_name for m in methods]})
                start,end=_span(node)
                result.units.append(CodeUnit(unit_id="",repository_id="",commit_sha="",language=self.language,unit_type=UnitType.CLASS,
                    name=node.name,qualified_name=node.name,signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                    file_path=relative_path,line_start=start,line_end=end,source=excerpt(lines,start,end),docstring=ast.get_docstring(node),
                    imports=result.imports,calls=sorted({m for fact in methods for m in fact.calls})))
                result.units.extend(self._function_unit(m,relative_path,lines,result.imports,owner=node.name) for m in method_nodes)
                if any("BaseModel" in b or "Base" in b for b in bases):
                    result.database_entities.append({"name":node.name,"kind":"class","line":node.lineno})
                if any("FastAPI" in b or "APIRouter" in b for b in bases):
                    result.framework_components.append({"name":node.name,"framework":"FastAPI","line":node.lineno})
        top_level=[u.name for u in result.units if u.parent is None and u.unit_type!=UnitType.FILE]
        result.exports=explicit_all if explicit_all is not None else [n for n in top_level if not n.startswith("_")]
        for unit in result.units:
            if unit.parent is None and unit.name in result.exports: unit.exports=[unit.name]
        result.units.insert(0,self._file_unit(relative_path,text,lines,result))
        assign_unit_ids(result.units,context)
        return result

    def _function_unit(self,node,path,lines,imports,owner=None)->CodeUnit:
        start,end=_span(node)
        sites,uncertainty=call_sites(node)
        return CodeUnit(unit_id="",repository_id="",commit_sha="",language=self.language,
            unit_type=UnitType.METHOD if owner else UnitType.FUNCTION,name=node.name,
            qualified_name=f"{owner}.{node.name}" if owner else node.name,signature=_signature(node),file_path=path,
            line_start=start,line_end=end,source=excerpt(lines,start,end),docstring=ast.get_docstring(node),imports=imports,
            calls=sorted({s.name for s in sites}),call_sites=sites,parent=owner,parser_uncertainty=uncertainty)

    def _file_unit(self,path,text,lines,result)->CodeUnit:
        uncertainty=["file source truncated for storage"] if len(text)>FILE_SOURCE_LIMIT else []
        module=path.rsplit("/",1)[-1].removesuffix(".py")
        return CodeUnit(unit_id="",repository_id="",commit_sha="",language=self.language,unit_type=UnitType.FILE,name=module,
            qualified_name=path,file_path=path,line_start=1,line_end=max(len(lines),1),source=text[:FILE_SOURCE_LIMIT],
            imports=result.imports,exports=result.exports,parser_uncertainty=uncertainty)

    @staticmethod
    def _explicit_all(tree)->list[str]|None:
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="__all__" for t in node.targets):
                try: return [str(x) for x in ast.literal_eval(node.value)]
                except (ValueError,TypeError): return None
        return None

    def _extract_endpoint(self,node,result):
        for dec in node.decorator_list:
            name=dotted_name(dec.func) if isinstance(dec,ast.Call) else dotted_name(dec)
            if name and name.split(".")[-1].lower() in {"get","post","put","patch","delete","route","api_route"} and isinstance(dec,ast.Call):
                path=ast.literal_eval(dec.args[0]) if dec.args and isinstance(dec.args[0],ast.Constant) and isinstance(dec.args[0].value,str) else None
                result.endpoints.append({"method":name.split(".")[-1].upper(),"path":path,"function":node.name,"line":node.lineno})

    def analyze_repository(self,root:Path,context:AnalysisContext|None=None)->list[FileAnalysis]:
        from app.services.code_units import analyze_repository
        return analyze_repository(root,[self],context)[0]
