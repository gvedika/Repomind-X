from __future__ import annotations
from dataclasses import dataclass, field
from app.models.schemas import GraphEdge, GraphNode, NodeKind
from app.services.analyzer import FileAnalysis
from app.services.graph_backend import GraphBackend, InMemoryGraphBackend, get_production_backend


@dataclass
class KnowledgeGraph:
    repository_id: str
    backend: GraphBackend
    # These mirrors exist only for explicit in-memory test backends.
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self,node):
        self.backend.add_node(node,self.repository_id)
        if isinstance(self.backend,InMemoryGraphBackend): self.nodes[node.id]=node

    def add_edge(self,source,target,kind,**metadata):
        self.backend.add_edge(source,target,kind,self.repository_id,**metadata)
        if isinstance(self.backend,InMemoryGraphBackend) and source in self.nodes and target in self.nodes:
            self.edges.append(GraphEdge(source=source,target=target,kind=kind,metadata=metadata))

    def search(self,term,kinds=None): return self.backend.search(self.repository_id,term,kinds)
    def path(self,starts,max_hops=5): return self.backend.path(self.repository_id,starts,max_hops)
    def impact(self,symbol,max_hops=4): return self.backend.impact(self.repository_id,symbol,max_hops)
    def export(self,limit=250): return self.backend.export(self.repository_id,limit)
    def health(self): return self.backend.health()


def build_graph(repository_id, analyses, backend=None):
    if backend is None:
        from app.core.config import settings
        if settings.graph_backend == "memory":
            backend = InMemoryGraphBackend()
        else:
            backend = get_production_backend()
    graph=KnowledgeGraph(repository_id,backend)
    repo_id=f"repo:{repository_id}"
    graph.add_node(GraphNode(id=repo_id,kind=NodeKind.REPOSITORY,name=repository_id))
    function_ids={}
    path_function_ids=set()
    for analysis in analyses:
        file_id=f"file:{repository_id}:{analysis.path}"
        graph.add_node(GraphNode(id=file_id,kind=NodeKind.FILE,name=analysis.path,metadata={"path":analysis.path}))
        graph.add_edge(repo_id,file_id,"CONTAINS")
        for lib in analysis.imports:
            lib_id=f"lib:{repository_id}:{lib}"
            graph.add_node(GraphNode(id=lib_id,kind=NodeKind.LIBRARY,name=lib))
            graph.add_edge(file_id,lib_id,"IMPORTS")
        for cls in analysis.classes:
            cls_id=f"class:{repository_id}:{analysis.path}:{cls['name']}"
            graph.add_node(GraphNode(id=cls_id,kind=NodeKind.CLASS,name=cls["name"],metadata={"bases":cls["bases"],"path":analysis.path}))
            graph.add_edge(file_id,cls_id,"DEFINES")
            for base in cls["bases"]:
                matches=function_ids.get(base)
                if matches: graph.add_edge(cls_id,matches,"INHERITS")
        for fun in analysis.functions:
            fun_id=f"function:{repository_id}:{analysis.path}:{fun.qualified_name}"
            function_ids[fun.qualified_name]=fun_id
            path_function_ids.add(fun_id)
            graph.add_node(GraphNode(id=fun_id,kind=NodeKind.FUNCTION,name=fun.qualified_name,metadata=fun.model_dump()))
            graph.add_edge(file_id,fun_id,"DEFINES")
        for endpoint in analysis.endpoints:
            eid=f"endpoint:{repository_id}:{analysis.path}:{endpoint["method"]}:{endpoint.get("path") or endpoint["function"]}"
            graph.add_node(GraphNode(id=eid,kind=NodeKind.API_ENDPOINT,name=f"{endpoint["method"]} {endpoint.get("path") or ""}".strip(),metadata=endpoint))
            graph.add_edge(file_id,eid,"EXPOSES")
        for entity in analysis.database_entities:
            did=f"db:{repository_id}:{analysis.path}:{entity["name"]}"
            graph.add_node(GraphNode(id=did,kind=NodeKind.DATABASE_ENTITY,name=entity["name"],metadata=entity))
            graph.add_edge(file_id,did,"DEFINES")
        for component in analysis.framework_components:
            cid=f"framework:{repository_id}:{analysis.path}:{component["name"]}"
            graph.add_node(GraphNode(id=cid,kind=NodeKind.FRAMEWORK_COMPONENT,name=component["name"],metadata=component))
            graph.add_edge(file_id,cid,"USES")
    # Second pass: conservative CALLS edges resolved from canonical units; unresolved calls are not guessed.
    from app.retrieval.graph import build_code_graph
    units=[u for analysis in analyses for u in analysis.units]
    node_for={}
    for u in units:
        fid=f"function:{repository_id}:{u.file_path}:{u.qualified_name}"
        if fid in path_function_ids: node_for[u.unit_id]=fid
    for edge in build_code_graph(units).edges:
        if edge.kind=="CALLS" and edge.source in node_for and edge.target in node_for:
            graph.add_edge(node_for[edge.source],node_for[edge.target],"CALLS",resolution=edge.resolution,line=edge.line)
    return graph
