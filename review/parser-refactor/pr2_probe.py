"""Read-only Jedi 0.20.1 receiver API probes over synthetic captured source."""

import ast
import json
import tempfile
from pathlib import Path

import jedi


CASES = {
    "global": {"demo.py": """def target(): pass
registry={}
def register(key, fn): registry[key]=fn
register('go',target)
def run(): registry['go']()
"""},
    "same_alias": {"demo.py": """def target(): pass
first={}
second=first
second['go']=target
def run(): first['go']()
"""},
    "fresh_separate": {"demo.py": """def target(): pass
left={}
right={}
right['go']=target
def run(): left['go']()
"""},
    "import_alias": {
        "base.py": "registry={}\n",
        "client.py": """from base import registry as alias
def target(): pass
alias['go']=target
def run(): alias['go']()
""",
    },
    "parameter_writer": {"demo.py": """def target(): pass
registry={}
def add(bucket): bucket['go']=target
add(registry)
def run(): registry['go']()
"""},
    "return_origin": {"demo.py": """def target(): pass
def make(): return {}
bucket=make()
bucket['go']=target
def run(): bucket['go']()
"""},
}


def name_record(name):
    return dict(name=name.name, type=name.type, full_name=name.full_name,
                module_path=str(name.module_path) if name.module_path else None,
                line=name.line, column=name.column)


def main():
    result = dict(jedi_version=jedi.__version__, cases={})
    with tempfile.TemporaryDirectory(prefix="lct-pr2-jedi-") as root:
        for label, sources in CASES.items():
            folder = Path(root, label)
            folder.mkdir()
            for filename, source in sources.items():
                Path(folder, filename).write_text(source, encoding="utf-8")
            project = jedi.Project(folder, sys_path=[str(folder)], smart_sys_path=False,
                                   load_unsafe_extensions=False)
            entries = []
            for filename, source in sources.items():
                script = jedi.Script(code=source, path=folder / filename, project=project)
                tree = ast.parse(source)
                receivers = []
                for subscript in ast.walk(tree):
                    if isinstance(subscript, ast.Subscript) and isinstance(subscript.value, ast.Name):
                        receivers.append((subscript.value, type(subscript.ctx).__name__))
                for receiver, context in sorted(receivers, key=lambda pair: (pair[0].lineno,
                                                                           pair[0].col_offset)):
                    line = source.splitlines()[receiver.end_lineno - 1]
                    column = len(line.encode()[:receiver.end_col_offset].decode())
                    record = dict(path=filename, receiver=receiver.id, context=context,
                                  line=receiver.end_lineno, column=column)
                    for method, kwargs in (("infer", {}), ("goto", {"follow_imports": True}),
                                           ("get_references", {"include_builtins": False})):
                        try:
                            names = getattr(script, method)(receiver.end_lineno, column, **kwargs)
                            record[method] = [name_record(name) for name in names]
                        except Exception as exc:
                            record[method] = dict(error=type(exc).__name__, message=str(exc))
                    entries.append(record)
            result["cases"][label] = entries
    destination = Path(__file__).with_name("PR2_PROBES.json")
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({case: [(r["path"], r["receiver"], r["context"],
                              [(n["name"], n["type"], n["line"]) for n in r["goto"]],
                              [(n["name"], n["type"], n["line"]) for n in r["infer"]])
                             for r in entries] for case, entries in result["cases"].items()},
                     indent=2))


if __name__ == "__main__":
    main()
