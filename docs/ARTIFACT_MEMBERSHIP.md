# Version artifact membership

Each complete version manifest records exactly `catalog.sqlite` and, for each
declared `partition-N` in sequence, `partition-N.npy`, `partition-N.usearch`,
and `partition-N.json`. A lexical-only version has no partitions. The existing
`artifacts` checksum and `artifact_sizes` fields keep their format. The build
streams each required file once in bounded chunks to derive both values from
the same bytes; an unrelated candidate file is never promoted to an index
artifact.

The candidate must have closed SQLite before finalization. A missing,
symlinked, or nonregular required artifact, or a nonempty
`catalog.sqlite-journal` or `catalog.sqlite-wal`, withholds publication. The
sidecar check runs before SQLite integrity validation so validation cannot
replay an incomplete transaction. The previous current pointer remains in
place on failure. Empty SQLite sidecars and incidental files are not artifacts.

A portable backup validates each complete version, then includes its manifest
artifacts, `manifest.json`, and `build-state.json` when present. Other files
in the version directory are excluded. Restore uses the original checksums
and validates each staged version before publishing its destination.
