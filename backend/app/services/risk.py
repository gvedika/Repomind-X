from __future__ import annotations
from app.models.schemas import FunctionFact, Finding
from app.services.git_history import GitEvolution


def function_risk(function: FunctionFact, git: GitEvolution, findings: list[Finding]) -> tuple[float, list[str]]:
    file_changes = len(git.changes_for_file(function.file_path))
    contributors = git.contributors_for_file(function.file_path)
    local_findings = [f for f in findings if f.file_path == function.file_path and function.line_start <= f.line <= function.line_end]
    score = min(100.0, function.complexity * 4 + len(function.calls) * 3 + file_changes * 2 + contributors * 2 + len(local_findings) * 22)
    reasons = []
    if function.complexity >= 8: reasons.append("high cyclomatic complexity")
    if len(function.calls) >= 6: reasons.append("many dependencies")
    if file_changes >= 5: reasons.append("frequently modified")
    if contributors >= 3: reasons.append("multiple contributors")
    if local_findings: reasons.append("security finding in function")
    return score, reasons or ["low observed structural and evolution risk"]


def repository_risk(functions: list[FunctionFact], git: GitEvolution, findings: list[Finding]) -> float:
    if not functions: return min(100.0, len(findings) * 10)
    return round(sum(function_risk(f, git, findings)[0] for f in functions) / len(functions), 1)
