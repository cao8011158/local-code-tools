"""Source-only nine-file syntax/import audit; does not analyze or execute project code."""
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

from lct.extract import module_name
from lct.graph import Graph
from lct.simple_python import CERTIFICATE, _certify_common, _certify_v4, certify

ROOT = Path(__file__).resolve().parent
RELATED = ROOT / "fixtures/actual-related-source"
SUBSET = ROOT / "fixtures/actual-source-subset"
REPO = "agentic-trpg/trpg-state-machine"


def main():
    provenance = json.loads((RELATED / "provenance.json").read_text())
    files, asts, catalog = [], {}, []
    for root in (RELATED, SUBSET):
        for source in sorted((root / "src/trpg_state_machine").glob("*.py")):
            path = "src/trpg_state_machine/" + source.name
            raw = source.read_bytes()
            if root == RELATED:
                expected = provenance["files"][path]
                assert len(raw) == expected["bytes"]
                assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
                assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == expected["git_blob_sha1"]
            ident = f"{REPO}:{path}:module:{module_name(path)}#1"
            tree = ast.parse(raw, filename=path)
            asts[ident] = tree
            files.append(dict(repository=REPO, path=path))
            catalog.append(dict(node_id=ident, kind="module", repository=REPO,
                                path=path, qualname=module_name(path)))
    graph = Graph(catalog, asts, [])  # Resolver only: no Graph.build/Jedi/analyzed source.
    selected = {(f["repository"], f["path"]) for f in files}
    entries = []
    for file in files:
        path = file["path"]
        ident = f"{REPO}:{path}:module:{module_name(path)}#1"
        tree = asts[ident]
        body = tree.body[1:] if ast.get_docstring(tree) else tree.body
        imports = []
        for stmt in body:
            if not isinstance(stmt, (ast.ImportFrom, ast.Import)):
                continue
            for alias in stmt.names:
                request = graph.import_request_module(ident, stmt, alias)
                targets = sorted(graph.imported(REPO, request)) if request else []
                missing_export = []
                for target in targets:
                    if target in asts and isinstance(stmt, ast.ImportFrom):
                        exports = {s.name for s in asts[target].body
                                   if isinstance(s, (ast.FunctionDef, ast.ClassDef))}
                        if alias.name not in exports:
                            missing_export.append(alias.name)
                imports.append(dict(line=stmt.lineno, source=ast.unparse(stmt), request=request,
                                    targets=targets, missing_export=missing_export))
        defs = [s for s in body if isinstance(s, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]
        methods = [s for s in ast.walk(tree) if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        risks = dict(top_level=[dict(line=s.lineno, kind=type(s).__name__, source=ast.unparse(s)[:90])
                                for s in body if not isinstance(s, (ast.FunctionDef, ast.ClassDef, ast.ImportFrom, ast.Import))],
                     class_bases=[dict(line=s.lineno, name=s.name, bases=[ast.unparse(b) for b in s.bases])
                                  for s in defs if isinstance(s, ast.ClassDef) and s.bases],
                     decorators=[dict(line=s.lineno, name=s.name,
                                      decorators=[ast.unparse(d) for d in s.decorator_list])
                                 for s in ast.walk(tree) if isinstance(s, (ast.FunctionDef, ast.ClassDef)) and s.decorator_list],
                     function_headers=[dict(line=s.lineno, name=s.name,
                                            kwonly=len(s.args.kwonlyargs), vararg=bool(s.args.vararg),
                                            kwarg=bool(s.args.kwarg), posdefaults=len(s.args.defaults),
                                            return_annotation=ast.unparse(s.returns) if s.returns else None)
                                       for s in methods if (s.args.vararg or s.args.kwarg or s.args.defaults or
                                                            s.args.kwonlyargs or s.returns)][:12],
                     body_nodes=dict(Counter(type(n).__name__ for n in ast.walk(tree)
                                          if isinstance(n, (ast.If, ast.For, ast.While, ast.Try,
                                                            ast.With, ast.Raise, ast.Lambda,
                                                            ast.ListComp, ast.DictComp, ast.SetComp,
                                                            ast.GeneratorExp, ast.NamedExpr, ast.AsyncFunctionDef)))))
        entries.append(dict(path=path, strict=_certify_v4([file], asts, graph=graph,
                     selected_context=selected) == CERTIFICATE,
                     common=_certify_common([file], asts, graph, selected),
                     imports=imports, risks=risks))
    result = dict(commit=provenance["commit"], files=len(files),
                  full_certificate=certify(files, asts, graph=graph), entries=entries,
                  method="AST parse + Graph resolver/import_request_module + certify only; no Graph.build/Jedi")
    output = ROOT / "actual-related-admission-audit.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(files=len(files), full_certificate=result["full_certificate"],
                          individually_certified=[e["path"] for e in entries if e["strict"] or e["common"]],
                          relative_imports=sum(1 for e in entries for i in e["imports"] if i["source"].startswith("from ."))),
                     sort_keys=True))


if __name__ == "__main__":
    main()
