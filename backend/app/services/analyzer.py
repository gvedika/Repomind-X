"""AST-based repository analysis for Python, including calls, routes and common DB/framework signals."""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from pathlib import Path
from app.models.schemas import FunctionFact

EXCLUDED={".git",".venv","venv","node_modules","dist","build","__pycache__",".tox",".mypy_cache",".pytest_cache"}


@dataclass
class FileAnalysis:
    path:str
    imports:list[str]=field(default_factory=list)
    functions:list[FunctionFact]=field(default_factory=list)
    classes:list[dict]=field(default_factory=list)
    endpoints:list[dict]=field(default_factory=list)
    database_entities:list[dict]=field(default_factory=list)
    framework_components:list[dict]=field(default_factory=list)
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


class PythonAnalyzer:
    def analyze_file(self,absolute_path:Path,relative_path:str)->FileAnalysis:
        result=FileAnalysis(path=relative_path)
        try: tree=ast.parse(absolute_path.read_text(encoding="utf-8"),filename=relative_path)
        except (SyntaxError,UnicodeDecodeError) as exc:
            result.parse_error=str(exc); return result
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imports.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom): imports.append(node.module or ".")
        result.imports=sorted(set(imports))
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                result.functions.append(function_fact(node,relative_path))
                self._extract_endpoint(node,result)
            elif isinstance(node,ast.ClassDef):
                bases=[ast.unparse(b) for b in node.bases]
                methods=[function_fact(m,relative_path,node.name) for m in node.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef))]
                result.classes.append({"name":node.name,"bases":bases,"line":node.lineno,"methods":[m.qualified_name for m in methods]})
                if any("BaseModel" in b or "Base" in b for b in bases):
                    result.database_entities.append({"name":node.name,"kind":"class","line":node.lineno})
                if any("FastAPI" in b or "APIRouter" in b for b in bases):
                    result.framework_components.append({"name":node.name,"framework":"FastAPI","line":node.lineno})
        return result

    def _extract_endpoint(self,node,result):
        for dec in node.decorator_list:
            name=dotted_name(dec.func) if isinstance(dec,ast.Call) else dotted_name(dec)
            if name and name.split(".")[-1].lower() in {"get","post","put","patch","delete","route","api_route"} and isinstance(dec,ast.Call):
                path=ast.literal_eval(dec.args[0]) if dec.args and isinstance(dec.args[0],ast.Constant) and isinstance(dec.args[0].value,str) else None
                result.endpoints.append({"method":name.split(".")[-1].upper(),"path":path,"function":node.name,"line":node.lineno})

    def analyze_repository(self,root:Path)->list[FileAnalysis]:
        results=[]
        for path in root.rglob("*.py"):
            if any(part in EXCLUDED for part in path.parts): continue
            results.append(self.analyze_file(path,path.relative_to(root).as_posix()))
        return results
