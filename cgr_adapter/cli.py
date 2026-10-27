"""Explicit local maintenance commands; default configuration is fixture-only."""

import argparse
import json
from pathlib import Path

from lct.common import load, lock
from lct.storage import manifest, validate_folder

from .coordinator import Coordinator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("operation", choices=["status", "update", "stop", "resume"])
    args = parser.parse_args()
    co = Coordinator(load(Path(args.config).resolve()))
    try:
        if args.operation == "update":
            result = co.update()
        elif args.operation == "stop":
            with lock(co.data / "publication.lock"):
                from lct.common import atomic

                previous = co.state()
                atomic(co.state_path, dict(state="STOPPED", previous=previous.get("version")))
                co.official.stop()
                result = co.status()
        elif args.operation == "resume":
            with lock(co.data / "publication.lock"):
                co._check()
                folder, metadata = manifest(co.c)
                validate_folder(folder, metadata)
                co.official.start()
                result = co.status()
        else:
            result = co.status()
        # Keep the full binding/manifest local; CLI output contains no auth configuration.
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "retrieval"}, ensure_ascii=False, indent=2
            )
        )
    finally:
        co.close()


if __name__ == "__main__":
    main()
