# Portable restore for Work

Build an index with the source toolkit, then run `backup` while its source configuration and index are available. Transfer the resulting ZIP to the new Work environment. Install the locked dependencies and use the copied toolkit's `restore` command with the original configuration and a destination that does not exist:

```sh
python local_code_tools.py --config /path/to/original-config.json restore /path/to/backup.zip /new/toolkit
python /new/toolkit/local_code_tools.py --config /new/toolkit/config.json search-code weight --mode bm25
```

The backup stores the source configuration with its **resolved absolute data directory**, even if the input used a relative path. Restore checks member names, checksums, the captured executable fingerprint, index format, current version, and every retained index artifact before publishing the destination. It updates only `data` in the copied configuration and the configuration hash of compatible retained manifests. Other manifests remain unchanged and incompatible. The receipt in `restore-receipt.json` records the archive SHA-256, original and new configuration identities, original and new data paths, rebound version names, and original manifest hashes. Index artifacts, node and edge IDs, source Git evidence, and model/program identifiers are preserved.

If the old config file is unavailable, use the normalized `config.json` contained in the archive as the source configuration; do not change its old `data` value before invoking restore. This is configuration data, not code to execute. Verify the archive SHA-256 against its trusted transfer record first. The acceptance utility `tools/verify_portable_work.py restore` demonstrates passing that archived configuration to `restore()`; the restoration code independently checks it and writes the new destination binding. Original source and data directories do not need to exist for this operation.

Queries can use the captured source text when original repositories are unavailable; `get-nodes` reports `indexed_snapshot` for that case. Restoring does not scan or regenerate repositories or call the embedding provider. New builds or freshness scans require accessible source repositories and appropriate configuration. An old schema-1 ZIP lacks resolved configuration evidence and is refused for relocation; make a new backup with the current toolkit while the original index is accessible. Changed model, algorithm, program, or incompatible retained versions are not promoted by restore. A successful restore is a local package check, not a Drive round trip, Neo4j import, or full-scale performance result.
