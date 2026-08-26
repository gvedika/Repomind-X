from app.models.schemas import GraphNode,NodeKind
from app.services.graph_backend import InMemoryGraphBackend


def test_memory_backend_isolated_by_api_contract():
    backend=InMemoryGraphBackend()
    backend.add_node(GraphNode(id="a",kind=NodeKind.FUNCTION,name="foo"),"repo")
    backend.add_node(GraphNode(id="b",kind=NodeKind.FUNCTION,name="bar"),"repo")
    backend.add_edge("a","b","CALLS","repo")
    assert backend.search("repo","foo")[0].name=="foo"
    assert backend.path("repo",["a"],1)==["a","b"]
