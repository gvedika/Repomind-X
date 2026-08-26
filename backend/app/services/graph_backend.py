from __future__ import annotations
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
import json
from typing import Iterable
from app.core.config import settings
from app.models.schemas import GraphEdge, GraphNode, NodeKind


class GraphBackend(ABC):
    @abstractmethod
    def add_node(self, node: GraphNode, repository_id: str) -> None: ...
    @abstractmethod
    def add_edge(self, source: str, target: str, kind: str, repository_id: str, **metadata: object) -> None: ...
    @abstractmethod
    def search(self, repository_id: str, term: str, kinds: set[NodeKind] | None = None) -> list[GraphNode]: ...
    @abstractmethod
    def path(self, repository_id: str, starts: list[str], max_hops: int = 5) -> list[str]: ...
    @abstractmethod
    def impact(self, repository_id: str, symbol: str, max_hops: int = 4) -> list[GraphNode]: ...
    @abstractmethod
    def export(self, repository_id: str, limit: int = 250) -> dict: ...
    @abstractmethod
    def health(self) -> bool: ...


@dataclass
class InMemoryGraphBackend(GraphBackend):
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node, repository_id):
        self.nodes[node.id] = node

    def add_edge(self, source, target, kind, repository_id, **metadata):
        if source in self.nodes and target in self.nodes:
            self.edges.append(GraphEdge(source=source, target=target, kind=kind, metadata=metadata))

    def search(self, repository_id, term, kinds=None):
        term=term.lower()
        return [n for n in self.nodes.values() if term in n.name.lower() and (not kinds or n.kind in kinds)]

    def _neighbors(self, node_id):
        return [e for e in self.edges if e.source == node_id]

    def path(self, repository_id, starts, max_hops=5):
        seen=set(starts); q=deque((s,0) for s in starts); trace=[]
        while q:
            current,depth=q.popleft(); trace.append(current)
            if depth>=max_hops: continue
            for e in self._neighbors(current):
                if e.target not in seen:
                    seen.add(e.target); q.append((e.target,depth+1))
        return trace

    def impact(self, repository_id, symbol, max_hops=4):
        starts=[n.id for n in self.search(repository_id,symbol,{NodeKind.FUNCTION,NodeKind.CLASS})]
        return [self.nodes[n] for n in self.path(repository_id,starts,max_hops) if n in self.nodes]

    def export(self, repository_id, limit=250):
        ids=set(list(self.nodes)[:limit])
        return {"nodes":[n.model_dump() for n in self.nodes.values() if n.id in ids],
                "edges":[e.model_dump() for e in self.edges if e.source in ids and e.target in ids]}

    def health(self): return True


class Neo4jGraphBackend(GraphBackend):
    """Production graph backend. Every node/edge is scoped by repository_id."""
    def __init__(self):
        if not all([settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password]):
            raise RuntimeError("Neo4j is required for production graph execution; configure NEO4J_URI/USERNAME/PASSWORD.")
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_pool_size,
            connection_acquisition_timeout=settings.neo4j_timeout_seconds,
        )

    def close(self):
        self.driver.close()

    def health(self):
        try:
            self.driver.verify_connectivity()
            return True
        except Exception:
            return False

    def _init(self):
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT repomind_node_id IF NOT EXISTS FOR (n:RepoMindNode) REQUIRE n.id IS UNIQUE")
            s.run("CREATE INDEX repomind_repo_id IF NOT EXISTS FOR (n:RepoMindNode) ON (n.repository_id)")

    def add_node(self,node,repository_id):
        props={"id":node.id,"repository_id":repository_id,"kind":node.kind.value,"name":node.name,"metadata":json.dumps(json_safe(node.metadata))}
        with self.driver.session() as s:
            s.execute_write(lambda tx: tx.run(
                "MERGE (n:RepoMindNode {id:$id}) SET n.repository_id=$repository_id,n.kind=$kind,n.name=$name,n.metadata=$metadata",
                **props))

    def add_edge(self,source,target,kind,repository_id,**metadata):
        # Relationship types cannot be parameters; validate against the allow-list.
        if kind not in {"CONTAINS","DEFINES","IMPORTS","CALLS","INHERITS","USES","ACCESSES","EXPOSES","DEPENDS_ON"}:
            raise ValueError(f"Unsupported relationship type: {kind}")
        query=f"""MATCH (a:RepoMindNode {{id:$source,repository_id:$repository_id}}),
                         (b:RepoMindNode {{id:$target,repository_id:$repository_id}})
                  MERGE (a)-[r:{kind}]->(b) SET r.metadata=$metadata"""
        with self.driver.session() as s:
            s.execute_write(lambda tx: tx.run(query,source=source,target=target,repository_id=repository_id,metadata=json.dumps(json_safe(metadata))))

    def search(self,repository_id,term,kinds=None):
        q="""MATCH (n:RepoMindNode {repository_id:$repository_id})
             WHERE toLower(n.name) CONTAINS toLower($term) AND ($kinds IS NULL OR n.kind IN $kinds)
             RETURN n ORDER BY size(n.name) LIMIT 100"""
        vals=[k.value for k in kinds] if kinds else None
        with self.driver.session() as s:
            rows=s.run(q,repository_id=repository_id,term=term,kinds=vals)
            return [node_from_record(r["n"]) for r in rows]

    def path(self,repository_id,starts,max_hops=5):
        if not starts:return []
        q=f"""MATCH (s:RepoMindNode {{repository_id:$repository_id}})
              WHERE s.id IN $starts
              OPTIONAL MATCH p=(s)-[*0..{int(max_hops)}]->(n:RepoMindNode {{repository_id:$repository_id}})
              WITH DISTINCT n
              RETURN n.id AS id
              ORDER BY id"""
        with self.driver.session() as s:
            return [r["id"] for r in s.run(q,repository_id=repository_id,starts=starts)]

    def impact(self,repository_id,symbol,max_hops=4):
        starts=self.search(repository_id,symbol,{NodeKind.FUNCTION,NodeKind.CLASS})
        ids=self.path(repository_id,[n.id for n in starts],max_hops)
        if not ids:return []
        with self.driver.session() as s:
            rows=s.run("MATCH (n:RepoMindNode {repository_id:$repository_id}) WHERE n.id IN $ids RETURN n",
                       repository_id=repository_id,ids=ids)
            by={n.id:n for n in (node_from_record(r["n"]) for r in rows)}
        return [by[i] for i in ids if i in by]

    def export(self,repository_id,limit=250):
        with self.driver.session() as s:
            nodes=[node_from_record(r["n"]) for r in s.run(
                "MATCH (n:RepoMindNode {repository_id:$repository_id}) RETURN n LIMIT $limit",
                repository_id=repository_id,limit=limit)]
            ids=[n.id for n in nodes]
            edges=[GraphEdge(source=r["source"],target=r["target"],kind=r["kind"],metadata=json.loads(r["metadata"] or "{}")) for r in s.run(
                """MATCH (a:RepoMindNode {repository_id:$repository_id})-[r]->(b:RepoMindNode {repository_id:$repository_id})
                   WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS source,b.id AS target,type(r) AS kind,r.metadata AS metadata""",
                repository_id=repository_id,ids=ids)]
        return {"nodes":[n.model_dump() for n in nodes],"edges":[e.model_dump() for e in edges]}


def json_safe(value):
    return json.loads(json.dumps(value, default=str))


def node_from_record(node):
    return GraphNode(id=node["id"],kind=NodeKind(node["kind"]),name=node["name"],metadata=json.loads(node.get("metadata") or "{}"))


def get_production_backend() -> Neo4jGraphBackend:
    backend=Neo4jGraphBackend()
    backend._init()
    return backend
