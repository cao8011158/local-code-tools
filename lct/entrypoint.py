"""Select the CLI implementation before importing any retrieval components."""

import sys


def main():
    """Send CGR commands to the new runtime and preserve existing CLI commands."""
    if sys.argv[1:2] and sys.argv[1] in {
        "up",
        "refresh",
        "hybrid-search",
        "doc-search",
        "graph-mcp",
        "local-mcp",
    }:
        from .cgr_cli import main as cgr_main

        return cgr_main()
    from .cli import main as legacy_main

    return legacy_main()


if __name__ == "__main__":
    sys.exit(main())
