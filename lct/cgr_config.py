"""Read the CGR runtime's repository, storage and service configuration."""

import hashlib
import ipaddress
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Repository:
    """A configured checkout and its explicit exclusion rules."""

    path: Path
    kind: str
    name: str
    exclude: tuple[str, ...]
    exclude_dirs: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    """Configuration for one isolated graph, collection and lexical index set."""

    path: Path
    name: str
    data: Path
    model_cache: Path
    qdrant_url: str
    qdrant_exe: Path | None
    qdrant_dir: Path | None
    repositories: dict[str, Repository]
    disable_legacy: tuple[str, ...]
    mcp_prefix: str

    @property
    def collection(self):
        """Namespace points by installation, including configs with the same name."""
        identity = hashlib.sha256(os.path.normcase(str(self.data)).encode()).hexdigest()[:16]
        return f"lct_{self.name}_{identity}"

    @property
    def code(self):
        """Return the configured code aliases in config order."""
        return tuple(key for key, repo in self.repositories.items() if repo.kind == "code")

    @property
    def doc(self):
        """Return the optional documentation alias."""
        return next((key for key, repo in self.repositories.items() if repo.kind == "docs"), None)

    def index_identity(self):
        """Bind persisted indexes to their owning checkouts and configuration."""
        return json.dumps(
            {
                "name": self.name,
                "qdrant_url": self.qdrant_url,
                "schema": 1,
                "repos": {
                    key: [str(repo.path), repo.kind, repo.name, repo.exclude, repo.exclude_dirs]
                    for key, repo in self.repositories.items()
                },
            },
            sort_keys=True,
        )


def load_config(path):
    """Resolve paths relative to TOML and validate ownership before startup."""
    path = Path(path).resolve(strict=True)
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))

    def resolve(value):
        """Resolve a local path relative to the configuration file."""
        return (path.parent / value).resolve()

    name = raw["name"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", name):
        raise ValueError("name must be a lowercase identifier")
    mcp_prefix = raw.get("mcp_prefix", f"lct_{name}")
    if not isinstance(mcp_prefix, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", mcp_prefix):
        raise ValueError("mcp_prefix must be a lowercase identifier")
    repos = {}
    for key, repo in raw["repositories"].items():
        kind = repo["kind"]
        graph_name = repo.get("name", key)
        if kind not in {"code", "docs"} or not re.fullmatch(r"[A-Za-z0-9_-]+", graph_name):
            raise ValueError(f"Invalid repository kind or CGR project name for {key}")
        root = resolve(repo["path"])
        if not root.is_dir():
            raise ValueError(f"Missing checkout {key}: {root}")
        repos[key] = Repository(
            root,
            kind,
            graph_name,
            tuple(repo.get("exclude", [])),
            tuple(repo.get("exclude_dirs", [])),
        )
    code_names = [repo.name for repo in repos.values() if repo.kind == "code"]
    if not code_names or len(code_names) != len(set(code_names)):
        raise ValueError("Configure one or more code repos with distinct CGR project names")
    if sum(repo.kind == "docs" for repo in repos.values()) > 1:
        raise ValueError("Only one documentation repository is supported")
    qdrant = raw.get("qdrant", {})
    url = qdrant.get("url", "http://127.0.0.1:6333").rstrip("/")
    endpoint = urlsplit(url)
    if (
        endpoint.scheme != "http"
        or endpoint.username
        or endpoint.path
        or endpoint.query
        or endpoint.fragment
        or not ipaddress.ip_address(endpoint.hostname or "").is_loopback
    ):
        raise ValueError("qdrant.url must be a loopback HTTP endpoint")
    exe = resolve(qdrant["executable"]) if "executable" in qdrant else None
    service_dir = resolve(qdrant["directory"]) if "directory" in qdrant else None
    if (exe is None) != (service_dir is None):
        raise ValueError("Qdrant executable and directory must be configured together")
    return Config(
        path,
        name,
        resolve(raw["index_dir"]),
        resolve(raw["model_cache"]),
        url,
        exe,
        service_dir,
        repos,
        tuple(raw.get("disable_legacy", [])),
        mcp_prefix,
    )
