"""Register exactly one local Codex stdio server without touching other MCP entries."""

import argparse
import json
import os
import re
import shutil
import time
import tomllib
from pathlib import Path

NAME = "agentic_trpg_local_code"
ROOT = Path(__file__).resolve().parent


def main():
    """Back up before a same-name replacement; store only env variable names, never keys."""
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(ROOT / "config.json"))
    p.add_argument("--codex-config")
    args = p.parse_args()
    codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    dest = Path(args.codex_config) if args.codex_config else codex_root / "config.toml"
    text = dest.read_text(encoding="utf-8-sig") if dest.exists() else ""
    before = tomllib.loads(text)
    command = (
        str(ROOT / ".venv" / "Scripts" / "python.exe")
        if os.name == "nt"
        else str(ROOT / ".venv" / "bin" / "python")
    )
    if not Path(command).is_file():
        raise SystemExit("Create independent environment with uv sync --locked first")
    desired = {
        "command": command,
        "args": [
            str(ROOT / "local_code_tools.py"),
            "--config",
            str(Path(args.config).resolve()),
            "mcp",
        ],
        "env_vars": ["VOYAGE_API_KEY"],
        "startup_timeout_sec": 30.0,
        "tool_timeout_sec": 120.0,
    }
    old = before.get("mcp_servers", {}).get(NAME)
    if old == desired:
        print(json.dumps({"service": NAME, "status": "already_registered", "command": command}))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if dest.exists():
        backup = dest.with_name(
            dest.name
            + ".local-code-tools-"
            + time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            + ".bak"
        )
        shutil.copy2(dest, backup)
    header = f"[mcp_servers.{NAME}]"
    # Remove only that exact table/subtables. Preserve other sections byte-for-byte.
    pieces = re.split(r"(?m)(?=^\[[^\n]+\]\s*$)", text)
    kept = []
    for part in pieces:
        first = part.splitlines()[0] if part.splitlines() else ""
        if (
            first == header
            or first.startswith(f"[mcp_servers.{NAME}.")
            or first.startswith(f'[mcp_servers."{NAME}"')
        ):
            continue
        kept.append(part)
    block = (
        header
        + "\n"
        + "\n".join(k + " = " + json.dumps(v, ensure_ascii=False) for k, v in desired.items())
        + "\n"
    )
    updated = "".join(kept).rstrip() + "\n\n" + block
    after = tomllib.loads(updated)
    a = dict(before)
    b = dict(after)
    a["mcp_servers"] = {k: v for k, v in a.get("mcp_servers", {}).items() if k != NAME}
    b["mcp_servers"] = {k: v for k, v in b.get("mcp_servers", {}).items() if k != NAME}
    if a != b:
        raise SystemExit("Refusing change outside the named MCP server")
    temp = dest.with_name(dest.name + ".local-code-tools.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    temp.replace(dest)
    for older in sorted(dest.parent.glob(dest.name + ".local-code-tools-*.bak"), reverse=True)[2:]:
        older.unlink()
    print(
        json.dumps(
            {
                "service": NAME,
                "status": "registered",
                "command": command,
                "config_backup": str(backup) if backup else None,
                "other_settings_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
