from __future__ import annotations
import re


INJECTION_PATTERNS=[
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"disregard\s+(?:the\s+)?system\s+prompt",
    r"reveal\s+(?:the\s+)?system\s+prompt",
    r"exfiltrat(?:e|ion)",
    r"print\s+(?:all\s+)?(?:secrets|environment variables|credentials)",
    r"upload\s+(?:the\s+)?(?:source|repository|credentials)",
]
SECRET_PATTERNS=[
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
]


def detect_repository_instruction(text:str)->bool:
    return any(re.search(p,text,re.I) for p in INJECTION_PATTERNS)


def detect_secrets(text:str)->list[str]:
    return [p.pattern for p in SECRET_PATTERNS if p.search(text)]


def sanitize_repository_text(text:str)->str:
    # Repository files are data, never instructions to the agent.
    return text.replace("\x00","")[:12000]
