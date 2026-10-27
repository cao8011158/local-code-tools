"""Extract Python AST nodes and heading-aware Markdown without project imports."""

import ast
import re
from collections import Counter

from .common import TEMPLATE, canonical, digest

CODE_KINDS = ("module", "class", "function")


def brief(doc):
    """Deterministic first nonempty docstring paragraph, at most 240 characters."""
    return next((x.strip()[:240] for x in (doc or "").split("\n\n") if x.strip()), "")


def module_name(path):
    """Derive import path from explicit src roots; scripts remain repository-local."""
    s = path.replace("\\", "/")
    if "/src/" in s:
        s = s.split("/src/", 1)[1]
    elif s.startswith("src/"):
        s = s[4:]
    s = s.removesuffix(".py").replace("/", ".")
    return s.removesuffix(".__init__")


def make_node(
    repo, path, kind, qual, parent, occurrence, start, end, source, doc="", signature="", **extra
):
    """Keep logical identity independent of line shifts; duplicate definitions use ordinal."""
    logical = f"{repo}:{path}:{kind}:{qual}#{occurrence}"
    return dict(
        node_id=logical,
        repository=repo,
        path=path,
        kind=kind,
        qualname=qual,
        parent=parent,
        occurrence=occurrence,
        start=start,
        end=end,
        signature=signature,
        docstring=doc,
        brief=brief(doc),
        fingerprint=digest(source),
        **extra,
    )


def python_nodes(file):
    """Extract the sole Python catalog, including methods, lambdas and redefinitions.

    kind/node_id retain legacy search-level compatibility; node_type distinguishes
    methods and lambdas. logical_id is ordinal scope identity, version_id binds the
    capture, exact AST byte span and source fingerprint. The AST map holds captured
    module text for Jedi; it is never recovered from the live working tree.
    """
    text, path, repo = file["text"], file["path"], file["repository"]
    tree = ast.parse(text, filename=path, type_comments=True)
    lines = text.splitlines(keepends=True)
    tree._lct_source = text
    nodes, ast_nodes = [], {}
    module = make_node(
        repo,
        path,
        "module",
        module_name(path),
        f"{repo}::repository",
        1,
        1,
        len(lines),
        text,
        ast.get_docstring(tree) or "",
        is_test=file["is_test"],
    )

    def identity(node, obj, node_type, name):
        node.update(
            logical_id=node["node_id"],
            repository_id=file.get("repository_id", repo),
            snapshot_id=file.get("snapshot_id", digest(text)),
            snapshot_scope="repository-capture" if "snapshot_id" in file else "single-file-capture",
            source_sha256=digest(text),
            node_type=node_type,
            name=name,
            module=module["node_id"],
            definition_line=getattr(obj, "lineno", 1),
            column=getattr(obj, "col_offset", 0),
            end_column=getattr(
                obj, "end_col_offset", len(lines[-1].rstrip("\r\n").encode("utf-8")) if lines else 0
            ),
        )
        node["version_id"] = digest(
            canonical(
                [
                    node["repository_id"],
                    node["snapshot_id"],
                    node["logical_id"],
                    node["definition_line"],
                    node["column"],
                    node["end"],
                    node["end_column"],
                    node["fingerprint"],
                ]
            )
        )

    identity(module, tree, "module", module["qualname"])
    nodes.append(module)
    ast_nodes[module["node_id"]] = tree
    counts = Counter()

    def walk(item, owner):
        for child in ast.iter_child_nodes(item):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                name = "<lambda>" if isinstance(child, ast.Lambda) else child.name
                qual = name if owner["kind"] == "module" else owner["qualname"] + "." + name
                counts[owner["node_id"], kind, name] += 1
                ordinal = counts[owner["node_id"], kind, name]
                # Include the owner's ordinal so same-name nested scopes do not collide.
                occurrence = str(owner["occurrence"]) + "." + str(ordinal)
                start = min(
                    [child.lineno] + [d.lineno for d in getattr(child, "decorator_list", [])]
                )
                while start > 1 and not isinstance(child, ast.Lambda):
                    prev = lines[start - 2]
                    indent = len(lines[child.lineno - 1]) - len(lines[child.lineno - 1].lstrip())
                    if not prev.strip().startswith("#") or len(prev) - len(prev.lstrip()) != indent:
                        break
                    start -= 1
                source = "".join(lines[start - 1 : child.end_lineno])
                if isinstance(child, ast.Lambda):
                    source = ast.get_source_segment(text, child)
                    signature = "lambda " + ast.unparse(child.args)
                elif kind == "function":
                    signature = (
                        "async " if isinstance(child, ast.AsyncFunctionDef) else ""
                    ) + f"def {child.name}({ast.unparse(child.args)})"
                    if child.returns:
                        signature += " -> " + ast.unparse(child.returns)
                else:
                    signature = (
                        f"class {child.name}({', '.join(ast.unparse(b) for b in child.bases)})"
                    )
                node = make_node(
                    repo,
                    path,
                    kind,
                    qual,
                    owner["node_id"],
                    occurrence,
                    start,
                    child.end_lineno,
                    source,
                    "" if isinstance(child, ast.Lambda) else ast.get_docstring(child) or "",
                    signature,
                    is_test=file["is_test"],
                    definition_line=child.lineno,
                    column=child.col_offset,
                )
                node_type = (
                    "class"
                    if kind == "class"
                    else "lambda"
                    if isinstance(child, ast.Lambda)
                    else "method"
                    if owner["node_type"] == "class"
                    else "function"
                )
                identity(node, child, node_type, name)
                nodes.append(node)
                ast_nodes[node["node_id"]] = child
                walk(child, node)
            else:
                walk(child, owner)

    walk(tree, module)
    return nodes, ast_nodes


def utf8_prefix(text, size):
    """Bound UTF-8 bytes without cutting a codepoint."""
    return text.encode()[:size].decode("utf-8", errors="ignore")


def chunks(text, limit=22000):
    """Split code at lines, falling back to byte-safe slices for a single oversized line."""
    out, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line.encode()) > limit:
            if current:
                out.append(current)
                current = ""
            part = utf8_prefix(line, limit)
            out.append(part)
            line = line[len(part) :]
        if len((current + line).encode()) > limit:
            out.append(current)
            current = ""
        current += line
    if current or not out:
        out.append(current)
    return out


def embedding_texts(nodes, files):
    """Member names/signatures summarize modules/classes; functions embed their source once."""
    byid = {n["node_id"]: n for n in nodes}
    byfile = {(f["repository"], f["path"]): f["text"].splitlines(keepends=True) for f in files}
    children = {}
    for n in nodes:
        children.setdefault(n["parent"], []).append(n)
    result = []
    for n in nodes:
        kind = n["kind"]
        if kind not in CODE_KINDS:
            continue
        label = f"Repository: {n['repository']}\nPath: {n['path']}\n{kind}: {n['qualname']}\n"
        if kind == "function":
            owner = byid.get(n["parent"], {})
            module = owner
            while module.get("kind") not in (None, "module"):
                module = byid.get(module.get("parent"), {})
            context = utf8_prefix(
                f"Owner: {owner.get('qualname', '')}\nOwner context: {brief(owner.get('docstring'))}\nModule context: {brief(module.get('docstring'))}\n",
                2200,
            )
            source = "".join(byfile[n["repository"], n["path"]][n["start"] - 1 : n["end"]])
            texts = [label + context + part for part in chunks(source)]
        else:
            members = children.get(n["node_id"], [])
            # Explicit source-order budget: at most 80 members / 8 KiB; no bodies.
            member_text = "\n".join(
                (m["signature"] or m["qualname"])[:500] + " " + brief(m["docstring"])
                for m in members[:80]
            )
            texts = [
                label
                + utf8_prefix(n["signature"] + "\n" + n["docstring"], 10000)
                + "\nMembers (source order, cap=80/8KiB):\n"
                + utf8_prefix(member_text, 8000)
            ]
        for idx, text in enumerate(texts):
            result.append(
                {
                    "node_id": n["node_id"],
                    "chunk": idx,
                    "text": text,
                    "template": TEMPLATE,
                    "input_hash": digest(text),
                }
            )
    return result


def markdown_nodes(file):
    """Split at headings outside fences, then paragraphs/tables/fences as atomic blocks."""
    lines = file["text"].splitlines(keepends=True)
    headings = [(0, 0, "(preamble)")]
    fence = None
    for i, line in enumerate(lines):
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            headings.append((i, len(m[1]), m[2]))
        elif i and re.match(r"^(?:={3,}|-{3,})\s*$", line) and lines[i - 1].strip():
            headings.append((i - 1, 1 if line.startswith("=") else 2, lines[i - 1].strip()))
    headings = sorted(set(headings), key=lambda x: (x[0], x[1]))
    stack, counts, nodes, anchor_counts = [], Counter(), [], Counter()
    path = file["path"]
    category = (
        "experiment"
        if any(x in path.lower() for x in ("experiment", "ablation"))
        else "history"
        if any(x in path.lower() for x in ("review", "progress", "acceptance", "changelog"))
        else "contract"
        if file["repository"] == "agentic-trpg" and path.startswith("docs/")
        else "implementation"
    )
    for h, (start, level, title) in enumerate(headings):
        end = headings[h + 1][0] if h + 1 < len(headings) else len(lines)
        if start == end:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        heading_path = [x[1] for x in stack] + [title]
        qual = " / ".join(heading_path)
        counts[qual] += 1
        slug = re.sub(r"[^\w\-\s]", "", title.lower()).replace(" ", "-")
        anchor_counts[slug] += 1
        anchor = slug + ("-" + str(anchor_counts[slug] - 1) if anchor_counts[slug] > 1 else "")
        owner = stack[-1][2] if stack else f"{file['repository']}::repository"
        # Blank paragraphs outside fenced blocks and pipe tables are safe split points.
        spans, block_start, fenced = [], start, False
        for j in range(start, end):
            if re.match(r"^\s*(`{3,}|~{3,})", lines[j]):
                fenced = not fenced
            if not fenced and not lines[j].strip():
                spans.append((block_start, j + 1))
                block_start = j + 1
        if block_start < end:
            spans.append((block_start, end))
        groups, a, b = [], start, start
        for x, y in spans:
            if b > a and len("".join(lines[a:y]).encode()) > 18000:
                groups.append((a, b))
                a = x
            b = y
        if b > a:
            groups.append((a, b))
        first_id = None
        for part, (a, b) in enumerate(groups or [(start, end)]):
            source = "".join(lines[a:b])
            n = make_node(
                file["repository"],
                path,
                "documentsection",
                qual,
                owner if part == 0 else first_id,
                f"{counts[qual]}.{part}",
                a + 1,
                b,
                source,
                brief(source),
                heading_path=heading_path,
                anchor=anchor,
                part=part,
                category=category,
                oversized_atomic_block=len(source.encode()) > 18000,
                is_test=False,
            )
            first_id = first_id or n["node_id"]
            nodes.append(n)
        stack.append((level, title, first_id))
    return nodes


def extract(files):
    """Build one unified node catalog and AST map; parse errors fail the candidate build."""
    nodes, asts = [], {}
    for repo in sorted({f["repository"] for f in files}):
        nodes.append(
            dict(
                node_id=f"{repo}::repository",
                repository=repo,
                path="",
                kind="repository",
                qualname=repo,
                parent=None,
                start=0,
                end=0,
                signature="",
                docstring="",
                brief="",
                fingerprint=digest(repo),
                is_test=False,
            )
        )
    snapshots = {
        repo: digest(
            canonical(
                sorted((f["path"], digest(f["text"])) for f in files if f["repository"] == repo)
            )
        )
        for repo in {f["repository"] for f in files}
    }
    for f in files:
        f = dict(f, snapshot_id=snapshots[f["repository"]])
        if f["path"].endswith(".py"):
            ns, trees = python_nodes(f)
            nodes.extend(ns)
            asts.update(trees)
        else:
            nodes.extend(markdown_nodes(f))
    if len(nodes) != len({n["node_id"] for n in nodes}):
        raise ValueError("Node identity collision")
    return nodes, asts
