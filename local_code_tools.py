"""Absolute executable entry point, independent of shell cwd and source repositories."""

import sys

from lct.entrypoint import main

if __name__ == "__main__":
    sys.exit(main())
