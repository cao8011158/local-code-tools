# Batch 4 publication layer, local implementation

`update-coordinated` stages the normal SQLite/BM25/HNSW version under `update.lock`,
imports that complete candidate into a fresh `(namespace, version)` Neo4j scope,
checks its complete marker/fingerprint/schema/counts, records a credential-free graph
binding in both version metadata files, then calls the existing atomic `activate`.
An import acknowledgment loss is reconciled against the graph marker. A pointer
acknowledgment loss is reconciled against current and the bound marker. A failure
before activation leaves the predecessor pointer and projection untouched; a
complete unreferenced candidate is safe to retry with a new version.

The `bind-current-graph` terminal command explicitly prepares an existing unbound
current version before coordinated updates. A bound current version rejects normal
`build`, `attach-dense`, and `recover` operations that would bypass graph readiness.
`publication-current` resolves and verifies a pinned descriptor against the actual
Neo4j marker. `publication-official-requests` uses that descriptor to create
official `read-cypher` requests; no MCP write transport was added. Search code and
docs accept an optional explicit version for first-page operation pinning, with a
cursor conflict check. Their original unpinned behavior remains available.

This is a *publication* change, not a graph delta algorithm. `import_snapshot`
still imports the complete candidate graph into a new scope. No real Neo4j import,
paid embeddings, or full business graph has been exercised here. Existing complete
v1 projection migration is still in-place and must not be used on a live predecessor.

Portable backups contain the bound version metadata through existing membership,
but do not include Neo4j. Restored coordinated requests validate the actual graph
marker and fail closed if the graph is unavailable or differs. A newly restored
environment needs a separately provisioned matching graph projection. Ordinary
SQLite-only historical queries retain their existing behavior.

The first coordinated update requires a current version with an established graph
binding; run `bind-current-graph` on a program-compatible current version. Updating
the toolkit changes `program_hash`. `migrate_metadata(version, expected_program_hash)`
can explicitly rebind an older legacy artifact with no `summary.json` when its
schema, format, tokenizer, template, config, model, and HNSW settings match. It
rejects a new-format version whose `summary.json` already exists and fails the
current program hash check; that case needs a new compatible build or a separately
specified upgrade contract. The
terminal binding step writes manifest and summary separately; a crash between
those writes may require rerunning `bind-current-graph` before a portable backup.
The explicit version pin does not reserve a retention lease across long-running
client operations; deployments must retain versions long enough for in-flight
operations. True graph delta preparation and a retention lease are later work.
