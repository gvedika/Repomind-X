from __future__ import annotations
import re
from pathlib import Path
from app.models.schemas import Finding


RULES=[
("REPOMIND001","HIGH",re.compile(r"(?:execute|executemany)\s*\(\s*(?:f[\"']|.*%|.*\.format\()",re.I),"Potential SQL injection: dynamic query passed to execute."),
("REPOMIND002","HIGH",re.compile(r"\b(?:eval|exec)\s*\(",re.I),"Dangerous dynamic code execution."),
("REPOMIND003","MEDIUM",re.compile(r"subprocess\.(?:call|run|Popen).*shell\s*=\s*True",re.I),"Shell execution can enable command injection."),
("REPOMIND004","CRITICAL",re.compile(r"(?:api[_-]?key|secret|password|access[_-]?token)\s*=\s*[\"'][^\"']{8,}",re.I),"Possible hard-coded secret."),
("REPOMIND005","HIGH",re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",re.I),"Private key material detected."),
]


def scan_python(root:Path)->list[Finding]:
    findings=[]
    for file in root.rglob("*"):
        if not file.is_file() or any(p in {".git",".venv","venv","node_modules","dist","build","__pycache__"} for p in file.parts): continue
        if file.suffix not in {".py",".js",".ts",".tsx",".json",".yaml",".yml",".env",".toml",".ini"}: continue
        try: lines=file.read_text(encoding="utf-8",errors="ignore").splitlines()
        except OSError: continue
        for line_number,line in enumerate(lines,1):
            for rule,severity,pattern,message in RULES:
                if pattern.search(line):
                    findings.append(Finding(rule_id=rule,severity=severity,message=message,file_path=file.relative_to(root).as_posix(),line=line_number))
    return findings
