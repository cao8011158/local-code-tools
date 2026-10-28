# Batch 3 prerequisite fixes — combined candidate

Branch: `feat/full-business-graph-indexes`. Base remote checkpoint: `eb3411c38898a83030d13a7cc8436553e3bd4000`; implementation baseline `7c50563cd695aed018bd451dec9d05a631792525`. Root compiled two isolated developer changes. No business repository modified. No paid API or dependency changes.

User explicitly authorized both prior-code repairs and requested resumption on 2026-10-28. B3-001 covers repeated global caller scans and all-node definition lookup. B3-002 covers incidental version artifact membership and backup inclusion. Separate developer reports document historical runs, prepublication adjustments, and exclusions.

After both production changes (including streaming hashes), combined quick regression: `python -m pytest tests -q -k 'not neo4j'` -> **424 passed, 1 skipped, 12 deselected in 11.86 seconds**, exit 0. Shared Python 3.12 environment, no clean-install claim. This command covers the product `tests/` suite, not separate analyzer experiments with their own environment. Those experiments' root collection hit missing psutil, documented in artifact report.

Root independent prepublication checks: five added dense-artifact/membership/real-WAL boundary cases passed. `tests/test_artifact_review.py` preserves them. Public Graph.build differential probes cover twelve case/size pairs; site semantics and edge multisets match, described in BATCH3_LOCALITY_SYNTHETIC.md. These checks are not a completed fixed-remote-SHA formal review.

Actual captured-source scale comparison and full Neo4j quick regression are pending at this code publication. Old failed business database is preserved. New live database construction uses a private /tmp directory. Full Batch 3 acceptance, paid vectors, real Neo4j business projection and Drive recovery remain uncompleted; do not merge based on these prerequisite fixes alone.
