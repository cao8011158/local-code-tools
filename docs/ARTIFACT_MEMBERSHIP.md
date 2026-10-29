# Version artifact membership

Each complete version summary records `catalog.sqlite`, `graph-sites.sqlite`, `source-files.json`, and, for each declared `partition-N` in sequence, `partition-N.npy`, `partition-N.usearch`, and `partition-N.json`. The latter two metadata artifacts preserve full graph and source evidence while allowing ordinary query metadata to remain small. Original legacy manifests retain their old membership; an explicit migration publishes the new membership in `summary.json` without changing their bytes.

The existing `artifacts` checksum and `artifact_sizes` fields keep their format. The build streams each required file in bounded chunks to derive both values from the same bytes; an unrelated candidate file is never promoted to an index artifact. A missing, symlinked, or nonregular required artifact, or a nonempty `catalog.sqlite-journal` or `catalog.sqlite-wal`, withholds publication. Full validation checks all artifact hashes and SQLite integrity before publication, recovery, backup, or restore. Ordinary queries check artifact sizes and sidecars without a catalog-wide count scan.

A portable backup validates every complete migrated version, then includes its summary, original manifest, artifacts, and `build-state.json` when present. Other version-directory files are excluded. Restore validates every staged version before publishing its destination.
