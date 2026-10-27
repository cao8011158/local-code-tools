"""Syntax-only positions and execution owners; no call-target inference."""

import ast
import re


def normalize(full, modules):
    """Map known module prefixes and one anonymous scope spelling; retain raw elsewhere."""
    full = re.sub(r"\.lambda\.\d+(?=\.|$)", ".<lambda>", full or "")
    for mod in sorted(modules, key=lambda m: len(m.removesuffix(".__init__")), reverse=True):
        clean = mod.removesuffix(".__init__")
        if full in (mod, clean):
            return clean + ":<module>"
        if full.startswith(clean + "."):
            return clean + ":" + full[len(clean) + 1 :]
    # External full names keep their own module boundary. Never guess project targets.
    left, _, right = full.rpartition(".")
    return (left + ":" + right) if left else full


def inventory(source):
    """Enumerate calls including bare decorators and definition-time default expressions."""
    tree = ast.parse(source["text"])
    module = source["module"].removesuffix(".__init__")
    calls, definitions = [], []

    def node(name, obj, kind):
        definitions.append(dict(id=module + ":" + name, line=getattr(obj, "lineno", 1), kind=kind))

    def visit(n, owner="<module>", phase="module"):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qual = n.name if owner == "<module>" else owner + "." + n.name
            node(qual, n, "class" if isinstance(n, ast.ClassDef) else "function")
            for deco in n.decorator_list:
                visit(deco, owner, "definition")
                # Applying bare decorators is implicit syntax; factory application is not inferred.
                if isinstance(deco, (ast.Name, ast.Attribute)):
                    calls.append(
                        dict(
                            line=deco.lineno,
                            column=deco.col_offset,
                            end_line=deco.end_lineno,
                            end_column=deco.end_col_offset,
                            expression=ast.unparse(deco),
                            context=module + ":" + owner,
                            phase="definition",
                            kind="implicit_decorator",
                        )
                    )
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in n.args.defaults + [x for x in n.args.kw_defaults if x is not None]:
                    visit(default, owner, "definition")
                for statement in n.body:
                    visit(statement, qual, "body")
            else:
                for base in n.bases:
                    visit(base, owner, "definition")
                for statement in n.body:
                    visit(statement, qual, "class_body")
            return
        if isinstance(n, ast.Lambda):
            qual = ("" if owner == "<module>" else owner + ".") + "<lambda>"
            node(qual, n, "lambda")
            for default in n.args.defaults:
                visit(default, owner, "definition")
            visit(n.body, qual, "body")
            return
        if isinstance(n, ast.Call):
            calls.append(
                dict(
                    line=n.lineno,
                    column=n.col_offset,
                    end_line=n.func.end_lineno,
                    end_column=n.func.end_col_offset,
                    expression=ast.unparse(n.func),
                    context=module + ":" + owner,
                    phase=phase,
                    kind="call",
                )
            )
        for child in ast.iter_child_nodes(n):
            visit(child, owner, phase)

    node("<module>", tree, "module")
    visit(tree)
    return calls, definitions


def annotated(sources, truth, synthetic):
    """Locate previously authored labels by comment or fixed source coordinates."""
    result = []
    for item in truth["sites"]:
        source = next(
            s
            for s in sources
            if s["path"] == item["file"] and (synthetic or s["repository"] == item["repository"])
        )
        row = dict(
            item, module=source["module"], source_key=source["repository"] + ":" + source["path"]
        )
        if synthetic:
            token = ("reference:" if item["kind"] == "reference" else "case:") + item["id"]
            lines = source["text"].splitlines()
            matches = [i + 1 for i, t in enumerate(lines) if token in t]
            assert len(matches) == 1, item["id"]
            row["line"] = matches[0]
            if item["kind"] == "reference":
                tree = ast.parse(source["text"])
                choices = [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Name)
                    and isinstance(n.ctx, ast.Load)
                    and n.lineno == row["line"]
                ]
                # One query anchor; expected multiple reference targets remain in truth.
                row["reference_positions"] = [(n.end_lineno, n.end_col_offset) for n in choices]
                n = choices[0]
                row["column"] = n.col_offset
                row["end_column"] = n.end_col_offset
                row["end_line"] = n.end_lineno
                row["expression"] = n.id
            else:
                sites, _ = inventory(source)
                choices = [
                    s
                    for s in sites
                    if s["line"] == row["line"]
                    and (not item["expression"] or s["expression"] == item["expression"])
                ]
                assert len(choices) == 1, (item["id"], choices)
                row.update(
                    {k: choices[0][k] for k in ("column", "end_column", "end_line", "expression")}
                )
        else:
            if item["kind"] == "reference":
                n = next(
                    n
                    for n in ast.walk(ast.parse(source["text"]))
                    if isinstance(n, ast.Name)
                    and n.lineno == row["line"]
                    and n.col_offset == row["column"]
                )
                row.update(end_column=n.end_col_offset, end_line=n.end_lineno)
            else:
                calls, _ = inventory(source)
                n = next(
                    s for s in calls if (s["line"], s["column"]) == (row["line"], row["column"])
                )
                row.update(end_column=n["end_column"], end_line=n["end_line"])
        result.append(row)
    return result
