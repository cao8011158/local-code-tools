"""Compare current test contracts with fixed baseline Git blobs, without changing branches."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "9d5a54f9f8ecdd6f5ce6349a916c03522a1453a7"


def main():
    """Materialize only tracked baseline files into a new task-owned temporary directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--parser-only", action="store_true")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = out / "source"
    paths = (
        subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE], cwd=ROOT)
        .decode()
        .splitlines()
    )
    for name in paths:
        dest = source / name
        if not dest.resolve().is_relative_to(source):
            raise ValueError("Invalid baseline path")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT))
    code = (
        "import sys; sys.path.insert(0,sys.argv[1]); "
        "import lct,lct.extract,lct.graph; "
        "assert 'source' in lct.__file__; import pytest; "
        "sys.exit(pytest.main(sys.argv[2:]))"
    )
    selected = (
        [
            str(ROOT / "tests/test_core.py"),
            str(ROOT / "tests/test_python_pipeline.py"),
            str(ROOT / "tests/test_python_pipeline_gaps.py"),
        ]
        if args.parser_only
        else [str(ROOT / "tests")]
    )
    cmd = [
        sys.executable,
        "-c",
        code,
        str(source),
        "-q",
        *selected,
        "--basetemp=" + str(out / "pytest"),
        "--junitxml=" + str(out / "tests.xml"),
    ]
    print("baseline", BASE, flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
