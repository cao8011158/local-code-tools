# Batch 4 class component development

2026-10-31. Development candidate on staged import of `feat/incremental-index-updates` at `a052f88d25646ee515523053898fe77463dbc526`; merge target `feat/local-code-tools-import`. This directory is not a Git checkout. The root agent owns publication, independent review, and the cumulative stage report. No push or merge was performed here.

## Change and scope

- `lct/simple_python.py`: v2 certificate admits ordinary baseless undecorated classes with docstrings, plain instance methods, and `__init__` assignments to `self.field`. It admits local objects originating in explicit captured function/class calls and their aliases, bound method aliases, and returned-instance attribute calls. Named imports must resolve to uniquely captured functions/classes. It rejects arbitrary parameter attributes, unknown aliases, descriptors/other dunders, inheritance/metaclasses/decorators, class body mutations, external imports, reflection names lacking a captured definition, and method field writes outside `__init__`. Unknown callback arguments continue through existing association semantics; unsupported syntax falls back to a full build. Old v1 certificates cannot be used by the v2 local gate, so a full build establishes a fresh certificate.
- `lct/python_effects.py`: B4-CLASS-MARKER fix makes inert AST marker objects contribute no execution clock ticks. Python reuses `Load`/`Store` markers; unrelated files overwrote their synthetic ownership and shifted event IDs in private effect proofs between complete and selected-component builds. Real AST operations, regions, and phase order remain unchanged.
- `tests/test_changed_python_gate.py`: the old class fallback fixture now uses unsupported inheritance; added an ordinary class positive case. `tests/test_class_component_certificate.py` covers gate rejections, docstrings, marker ownership/order with `before`, and exact full-catalog equality for `factory().cb()`.

## Verification

| Check | Result |
| --- | --- |
| Targeted independent class fixtures + gate and marker tests | 18 passed in 2.43s before the direct returned-instance test; then 15 passed in 1.73s for new tests plus independent fixtures |
| Fast repository suite + four prior independent review files + independent class fixtures | 543 passed, 25 skipped in 21.50s; exit 0; `class-component-fast.log` |
| Ruff on changed production/tests | exit 0; `class-component-ruff.log` |

Independent class fixtures assert whole JSON records for nodes, edges, sites, query observations, imports, and private proofs against fresh complete builds. For constructor callback first→second with unchanged factory, and for saved bound method callback first→second, the selected graph parses only a.py and b.py. Adding 20 unrelated same-named class/function files does not expand the parsed closure. The old version's records remain unchanged. The direct `factory().cb()` test compares the same whole-record catalog.

## Locality and limits

Public `storage.build → python_incremental.prepare → FileDependencies.adjacent/importers → extraction.python_nodes(selected) → Graph.build(selected)` consumes the existing indexed closure and parses two Python files with 0 or 20 unrelated class files in the independent fixture. The complete candidate/catalog/output still scales with all captured files, as before; this evidence establishes bounded AST and association scope for the certified component, not total constant-time build. SQLite EXPLAIN/VM count evidence for the same indexed dependency APIs is in `changed-python-independent-review.md`; no new SQL path was added here. No real repository scale, Neo4j, paid API, or multi-Python-repository update was run. Cross-repository Python and unsupported syntax retain full analysis.

No P0/P1 or core dependency defect was identified. B4-CLASS-MARKER is a current-step proof identity alignment defect reproduced by exact catalog comparison and fixed with the minimal inert-marker rule. Formal independent review is pending with the root agent.
