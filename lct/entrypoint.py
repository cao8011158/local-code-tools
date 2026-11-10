"""Run the CGR-backed LCT CLI from an installed script or Python module."""

import sys


def main():
    """Dispatch graph, search, refresh and MCP commands to the CGR integration."""
    from .cgr_cli import main as cgr_main

    return cgr_main()


if __name__ == "__main__":
    sys.exit(main())
