"""Run the actual stdio MCP server with a read-only cached-vector acceptance guard."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.readonly_cache import readonly_embeddings  # noqa: E402


def main():
    """The parent supplies LCT_CONFIG; fail before serving if it is absent."""
    if not os.environ.get("LCT_CONFIG"):
        raise SystemExit("Explicit LCT_CONFIG required for read-only MCP validation")
    with readonly_embeddings():
        from lct.mcp_server import main as serve

        serve()


if __name__ == "__main__":
    main()
