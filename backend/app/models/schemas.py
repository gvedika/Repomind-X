from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field, computed_field


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


class UnitType(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    FILE = "file"


class ParseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class CallSite(BaseModel):
    name: str
    line: int
    order: int = Field(description="Source (syntactic) order within the enclosing unit; not proof of runtime order")


class CodeUnit(BaseModel):
    """Language-neutral retrieval record emitted by every analyzer adapter."""
    unit_id: str
    repository_id: str
    commit_sha: str
    language: str
    unit_type: UnitType
    name: str
    qualified_name: str
    signature: str | None = None
    file_path: str = Field(description="Repository-relative POSIX path")
    line_start: int = Field(ge=1, description="One-based, inclusive")
    line_end: int = Field(ge=1, description="One-based, inclusive")
    source: str = ""
    docstring: str | None = None
    imports: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    call_sites: list[CallSite] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    parent: str | None = None
    parse_status: ParseStatus = ParseStatus.OK
    parser_uncertainty: list[str] = Field(default_factory=list)


class FileCoverage(BaseModel):
    file_path: str
    language: str | None = None
    status: ParseStatus
    units: int = 0
    reason: str | None = None


class ParseCoverage(BaseModel):
    files_seen: int = 0
    files_parsed: int = 0
    files_partial: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    units: int = 0
    by_language: dict[str, int] = Field(default_factory=dict)
    skipped_reasons: dict[str, int] = Field(default_factory=dict)
    errors: list[FileCoverage] = Field(default_factory=list)

    @computed_field
    @property
    def ratio(self) -> float:
        attempted = self.files_parsed + self.files_partial + self.files_failed
        return round((self.files_parsed + self.files_partial) / attempted, 4) if attempted else 0.0


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
    commit_sha: str = "worktree"
    units: int = 0
    parse_coverage: ParseCoverage | None = None


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
