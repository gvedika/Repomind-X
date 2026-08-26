from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class NodeKind(StrEnum):
    REPOSITORY = "Repository"
    DIRECTORY = "Directory"
    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    LIBRARY = "Library"
    COMMIT = "Commit"
    DEVELOPER = "Developer"
    ISSUE = "Issue"
    API_ENDPOINT = "APIEndpoint"
    DATABASE_ENTITY = "DatabaseEntity"
    FRAMEWORK_COMPONENT = "FrameworkComponent"


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    metadata: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str
    metadata: dict = Field(default_factory=dict)


class FunctionFact(BaseModel):
    qualified_name: str
    name: str
    file_path: str
    line_start: int
    line_end: int
    parameters: list[str] = Field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    complexity: int = 1
    embedding_id: str | None = None
    security_score: float = 0.0
    change_frequency: int = 0
    bug_frequency: int = 0


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    file_path: str
    line: int
    symbol: str | None = None


class IngestRequest(BaseModel):
    source: str = Field(description="Local repository path or public Git URL")
    branch: str | None = None


class RepositorySummary(BaseModel):
    id: str
    name: str
    source: str
    languages: dict[str, int]
    files: int
    functions: int
    classes: int
    dependencies: list[str]
    architecture: str
    risk_score: float
    indexed_at: datetime


class QueryRequest(BaseModel):
    repository_id: str
    question: str = Field(min_length=3)
    conversation_id: str | None = None


class Evidence(BaseModel):
    files: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    graph_path: list[str] = Field(default_factory=list)
    commits: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    confidence: float
    plan: list[str]
    evidence: Evidence
    verification_notes: list[str]
