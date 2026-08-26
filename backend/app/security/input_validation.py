from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
import re


ALLOWED_GIT_SCHEMES={"https","ssh"}


def validate_repository_source(source:str)->str:
    source=source.strip()
    if not source: raise ValueError("Repository source cannot be empty.")
    p=Path(source).expanduser()
    if p.exists():
        if not p.is_dir(): raise ValueError("Repository source must be a directory.")
        return str(p.resolve())
    parsed=urlparse(source)
    if parsed.scheme not in ALLOWED_GIT_SCHEMES and not source.startswith("git@"):
        raise ValueError("Only local directories or HTTPS/SSH Git URLs are allowed.")
    if parsed.scheme=="https" and parsed.username:
        raise ValueError("Embedded credentials in Git URLs are not allowed.")
    return source


def safe_repository_path(root:Path, relative:str)->Path:
    candidate=(root/relative).resolve()
    root=root.resolve()
    if candidate!=root and root not in candidate.parents:
        raise ValueError("Path traversal outside repository root is forbidden.")
    return candidate


def validate_tool_string(value:str,max_length:int=4000)->str:
    if not isinstance(value,str) or not value.strip(): raise ValueError("Tool argument must be a non-empty string.")
    if len(value)>max_length: raise ValueError("Tool argument exceeds maximum length.")
    return value.strip()
