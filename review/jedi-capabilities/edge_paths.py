"""Additional graph-exit observations: imports, bases, lambdas and boundaries."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from probe import environment, worker

CASES = [
    dict(id="inheritance_direct", files={"demo.py":
         "class Base:pass\nclass Child(Base«base»):pass\nChild«value»(«call»)\n"}),
    dict(id="inheritance_imported", files={"provider.py": "class Base:pass\n",
         "client.py": "from provider import Base as Alias\n"
                      "class Child(Alias«base»):pass\nChild«value»(«call»)\n"}),
    dict(id="import_binding", files={"provider.py": "def first():pass\n",
         "client.py": "from provider import first as alias«binding»\nalias«value»(«call»)\n"}),
    dict(id="lambda_target", files={"demo.py": "fn=lambda:None\nfn«value»(«call»)\n"}),
    dict(id="external_call", files={"demo.py":
         "from math import sqrt\nsqrt«value»(«call»4)\n"}),
    dict(id="partial_call", files={"demo.py":
         "from functools import partial\ndef first():pass\n"
         "def execute(cb):cb«callback_value»(«call_callback»)\n"
         "fn=partial(execute,first«source»)\nfn«value»(«call»)\n"}),
]
for case in CASES:
    case.update(family="graph-exit", docs=["api", "features"],
                note="Public API result only; path/type identity is not an LCT mapping claim.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        case = next(case for case in CASES if case["id"] == args.worker)
        print(json.dumps(worker(case, {}, "source_first")))
        return
    if not args.output:
        parser.error("--output required")
    runs = []
    for case in CASES:
        for repeat in (1, 2):
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                      "--worker", case["id"]],
                                     capture_output=True, text=True, timeout=20)
            if process.returncode:
                raise RuntimeError(process.stderr)
            result = json.loads(process.stdout)
            result.update(repeat=repeat, status="observed", exit_code=0, stderr=process.stderr)
            runs.append(result)
    args.output.write_text(json.dumps(dict(environment=environment(), runs=runs,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), indent=2) + "\n")
    print(json.dumps(dict(cases=len(CASES), runs=len(runs), output=str(args.output))))


if __name__ == "__main__":
    main()
