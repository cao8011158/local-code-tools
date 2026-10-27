"""Create a new synthetic fixture configuration, without touching any existing index."""

import argparse
import json
import subprocess
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--native-home", required=True, type=Path)
    parser.add_argument("--auth-file", required=True, type=Path)
    args = parser.parse_args()
    out = args.output_root.resolve()
    if out.exists():
        raise ValueError("Choose a new output directory; existing work is preserved")
    out.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    repo = out / "fixture"
    repo.mkdir()
    (repo / "sample.py").write_bytes(
        (root / "tests/cgr_integration/fixtures/sample.py").read_bytes()
    )
    (repo / "guide.md").write_text(
        "# Command fixture\n\nDispatch a registered command.\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "--", "sample.py", "guide.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Synthetic fixture",
        ],
        check=True,
    )
    c = json.loads((root / "integration_env/config.example.json").read_text(encoding="utf-8"))
    auth = json.loads(args.auth_file.read_text(encoding="utf-8"))
    c.update(
        data=str(out / "index"),
        namespace="lct-fixture-" + uuid.uuid4().hex[:16],
        uri=auth["uri"],
        owned_home=str(args.native_home.resolve()),
        auth_file=str(args.auth_file.resolve()),
        repositories=[
            dict(
                name="fixture",
                path=str(repo),
                files=["sample.py"],
                source_roots=["."],
                documents=["guide.md"],
            )
        ],
    )
    config = out / "config.json"
    config.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    print(config)


if __name__ == "__main__":
    main()
