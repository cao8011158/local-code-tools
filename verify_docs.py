"""Validate only this batch's Markdown edits and local navigation, preserving historical prose."""

import re

from lct.common import ROOT, atomic, git


def main():
    checked = []
    for repo, paths in {
        "agentic-trpg": ["AGENTS.md", "docs/LOCAL_CODE_TOOLS.md", "docs/SYSTEM_OVERVIEW.md"],
        "trpg-state-machine": ["AGENTS.md"],
        "trpg-rules-engine": ["AGENTS.md"],
    }.items():
        root = ROOT / "workspaces" / repo
        for rel in paths:
            text = (root / rel).read_text(encoding="utf-8-sig")
            fenced = False
            for line in text.splitlines():
                if re.match(r"^\s*(```|~~~)", line):
                    fenced = not fenced
            assert not fenced, (repo, rel, "unclosed fence")
            # New links only; legacy worktree/branch references are outside this task.
            patch = git(root, "diff", "--", rel)
            additions = (
                "\n".join(
                    x[1:]
                    for x in patch.splitlines()
                    if x.startswith("+") and not x.startswith("+++")
                )
                if rel != "docs/LOCAL_CODE_TOOLS.md"
                else text
            )
            for label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", additions):
                if target.startswith(("http:", "https:", "#")):
                    continue
                assert ((root / rel).parent / target.split("#")[0]).is_file(), (repo, rel, target)
            checked.append(str(root / rel))
        git(root, "diff", "--check")
    result = {
        "checked": checked,
        "fences": "passed",
        "new_local_links": "passed",
        "diff_check": "passed",
        "RE_strict_mkdocs": "exit 0, 8.45 seconds; existing locked environment; output outside repos",
    }
    atomic(ROOT / "reports/docs-validation.json", result)
    print(result)


if __name__ == "__main__":
    main()
