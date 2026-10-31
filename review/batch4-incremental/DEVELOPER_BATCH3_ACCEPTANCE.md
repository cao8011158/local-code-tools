# Batch 3 bounded actual-source acceptance: developer handoff

This is an offline, nine-file bounded input acceptance against fixed
`agentic-trpg/trpg-state-machine` commit
`a7b0804d5635e185a79ff3c1d1fa6241c2b858fe`. It is not the complete
83-file application or a three-repository business graph. Each original byte
sequence is checked against the fixture's Git blob and SHA-256 before copying;
the combined list is in `DEVELOPER_BATCH3_SOURCE_PROVENANCE.json`.
`tests/test_batch3_actual_acceptance.py` is the only new project code in this
batch. Production remains at reviewed B2 code `7f1d86e0b136a6df11cc981da053aa3c584b5f61`.
The independent reviewer owns `test_owner_publication_independent.py`.

## Scope and actual outcomes

| Capture | Input and update | Full-analysis budget and route | Observable checks |
| --- | --- | --- | --- |
| Three originals | `_execution.py`, `errors.py`, `item_units.py`; change actual `"actor"` literal | Full 51 Jedi/81 associations. Changed file parses once; owner update 28 Jedi/51 associations. | All 20 semantic/private tables match fresh. Old version stays readable. Recover first version, then reapply source change: owner update again matches fresh. An added then deleted synthetic `acceptance_extra.py` explicitly falls back full for `python-membership-changed`, each matching fresh. BM25 explicit old/current versions work. |
| Six originals | `combat.py`, `dnd_runtime.py`, `item_package.py`, `availability.py`, `errors.py`, `item_units.py` | Full 174 Jedi/12,807 associations, not limited. First `dnd_runtime.py` comment-only hash change uses owner mode (2 Jedi/0 associations); this is a same-semantics control. Then actual `item_units.py` limit changes `2**63 - 1`→`2**62 - 1`: full `open-receiver-source-coverage-unavailable`. | Both updates match fresh across all 20 tables, including B1 supports/subscriptions/writes, owner input events, UNKNOWN and ordered site provenance. The real value change is a conservative full case, not a claimed selective win. |
| Nine originals | Above six complex seeds plus three originals, including `service.py` and `world_containers.py` | Initial full 517 Jedi, 408 sites, 20,000/20,000 associations, `analysis_limited=true`. Actor edit consequently full `previous-owner-evidence-unavailable`, 515 Jedi and 20,000 associations; fresh full 517 Jedi/20,000. | 97 catalog nodes/696 edges initial; limited graph result and edited result match their same-input full oracles. BM25 is usable; synthetic, deterministic document/query vectors cached outside the measured build permit `attach_dense` from frozen lexical catalog, 96 chunks in 3 actual USearch partitions, zero provider requests. Explicit dense approximate/exact, RRF, node and graph queries use the published version; attached graph/catalog identities equal lexical. |
| Service/world limited subset | `service.py`, `world_containers.py`, `availability.py`, `errors.py` | 411 Jedi, 325 sites and 20,000 associations; limited even without the other five. | Source-only group budget probe; no selective-update admission claim. |

Missing `dnd5e_engine`, `rules_adapter`, `package` and other uncaptured
modules remain boundary/UNKNOWN according to the current analyzer. No stub is
created, no application module is imported/executed, no provider or paid API
is called, and no Neo4j service is started.

The independent synthetic dense publication control, which supplies vectors
without a provider call, covers a *changed* callback source with failed
`before_publish` (old pointer/artifact hashes preserved), successful owner
update, explicit old and new BM25/dense/RRF/graph reads, recover and next
owner update, portable backup/restore and another update after restore. It
passed in the developer targeted run. That control is separate from the
nine-file real-source capture. The existing cross-repository pin,
publication, portable restore, dense update and attachment tests passed as
a related regression; this does not imply a real external `dnd5e_engine`
checkout was present.

## Work and locality accounting

The fixture's source provenance verification, nine-file copy, and synthetic
cache preparation are separate from `storage.build`. Nine-file dense
preparation reads the *frozen* catalog, then inserts deterministic vectors
directly into the private test cache; it does not invoke inventory/AST/Jedi,
and the measured synthetic cache insertion was about 0.004 s. Dense
attachment reported 0.02 s in its summary and 0 provider requests; its
catalog hash, source fingerprint and graph remained identical to the lexical
version. The attached index and version files are fully materialized,
including 3 USearch artifacts and their mappings. No semantic quality claim
is made for deterministic synthetic vectors.

`developer-batch3-work.json` records each published snapshot's actual
`analysis_scope`, graph metrics, elapsed summary seconds, fingerprint,
artifact count and dense state. For the nine-file main run, lexical full was
37.75 s, edited full 35.59 s, fresh edited full 38.28 s. These total build
seconds include capture/inventory/hash, AST/Jedi/associations, index creation,
full SQLite/BM25 snapshot materialization and publication. The current
metrics do **not** time those latter phases independently; no CPU-time or
incremental-write claim is inferred. The three-file owner route records one
parsed Python file and 28 executed Jedi queries/51 associations versus
fresh full's three files and 51/81, while still materializing a complete
new snapshot. Its selected/reused owner counts, context bytes and cumulative
work are retained in the structured JSON. The six-file value case states
full fallback and the old owner preflight count separately.

B2's separately reviewed SQLite reverse-index and 0/20/100 unrelated-owner
controls provide the indexed-locality evidence; this B3 test does not
repeat or rename that SQL proof. No growth experiment on nine real files is
claimed. USearch search exercises the actual saved index and compares
approximate/exact returned target membership, without claiming a dense
ranking benchmark.

## Commands and raw evidence

- `.venv/bin/pytest -q tests/test_batch3_actual_acceptance.py review/batch4-incremental/test_owner_publication_independent.py -k 'not nine_original_bytes' -s > review/batch4-incremental/developer-batch3-targeted-3-6-publication.log 2>&1`: **3 passed, 1 deselected**.
- `.venv/bin/pytest -q tests > review/batch4-incremental/developer-batch3-full-main.log 2>&1`: **678 passed, 27 skipped**; this runs the expensive nine-file case once.
- `.venv/bin/pytest -q tests/test_cross_repository_python_incremental.py tests/test_publication_coordination.py tests/test_portable_restore.py tests/test_dense_update.py tests/test_attach_dense.py > review/batch4-incremental/developer-batch3-related-regression.log 2>&1`: **26 passed**.
- `.venv/bin/ruff check tests/test_batch3_actual_acceptance.py --select F,E9` and `git -c core.whitespace=cr-at-eol diff --check`: passed.
- `developer-batch3-nine-baseline.log`, `developer-batch3-seed-groups.log`, and `developer-batch3-work.json` preserve input and work observations. The first nine-file RRF attempt omitted a synthetic query cache entry; the inherited zero-cost budget rejected it, and `developer-batch3-early-nine.log` preserves this fixture error. The corrected full-main run passes with both query entries preseeded.

## Deliberately untested bounds

No full 83-file business capture, no real external dependency pin checkout,
no business execution or runtime order, no provider embeddings, no paid API,
no Neo4j projection or service, and no production deployment. The nine-file
limited association result is a declared current full-analysis boundary, not
owner reuse evidence. The six-file real value edit demonstrates safe full
fallback for an opaque selected receiver. A different source or future
core precision change requires a new fixed-input comparison.

This developer evidence is not the independent B3 review or release gate.
