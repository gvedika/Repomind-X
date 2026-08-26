from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from git import Repo, InvalidGitRepositoryError


@dataclass
class CommitFact:
    sha: str; message: str; author: str; files: list[str]


class GitEvolution:
    def __init__(self, commits: list[CommitFact] | None = None): self.commits = commits or []

    @classmethod
    def mine(cls, root: Path, limit: int = 300) -> "GitEvolution":
        try: repo = Repo(root, search_parent_directories=True)
        except InvalidGitRepositoryError: return cls()
        records = []
        for commit in repo.iter_commits(max_count=limit):
            try: files = list(commit.stats.files)
            except ValueError: files = []
            records.append(CommitFact(commit.hexsha[:12], commit.message.splitlines()[0], str(commit.author), files))
        return cls(records)

    def changes_for_file(self, path: str) -> list[CommitFact]: return [c for c in self.commits if path in c.files]
    def contributors_for_file(self, path: str) -> int: return len({c.author for c in self.changes_for_file(path)})
    def summary(self, path: str) -> list[dict]:
        return [{"sha": c.sha, "message": c.message, "author": c.author} for c in self.changes_for_file(path)[:8]]
