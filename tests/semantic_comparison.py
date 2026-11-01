"""Full-build oracle comparison for public semantics and source dependencies.

Owner scheduling can traverse different rejected candidates. Its execution
ledger is verified by separate invalidation tests, not by snapshot equality.
"""

import json


EXECUTION_LEDGER = {"unit_analysis_reads", "unit_analysis_watches", "unit_input_events"}


def _site(record):
    site = json.loads(record)
    def normalize_coverage(coverage):
        if not isinstance(coverage, dict):
            return
        if isinstance(coverage.get("gaps"), list):
            # Only repetition of an identical reason/evidence record is
            # incidental. A different reason or source location survives.
            coverage["gaps"] = sorted({json.dumps(gap, sort_keys=True)
                                        for gap in coverage["gaps"]})
        # A transitive write-source receipt contains child coverage receipts.
        # Retain their order, count, sources, rules and completeness; only
        # normalize duplicate diagnostic gaps within each receipt.
        if isinstance(coverage.get("dependencies"), list):
            for dependency in coverage["dependencies"]:
                normalize_coverage(dependency)

    def normalize_decision(decision):
        if not isinstance(decision, dict):
            return
        normalize_coverage(decision.get("write_source_coverage"))

    for evidence in site.get("evidence", ()):
        if evidence.get("tool") == "lct":
            evidence.pop("association_trace", None)
            normalize_decision(evidence.get("decision"))
    for key in ("decision", "resolution_decision"):
        normalize_decision(site.get(key))
    return json.dumps(site, sort_keys=True)


def semantic_snapshot(records):
    """Normalize only traversal traces and duplicate identical gap records.

    Accepts the table->row snapshot used by acceptance tests. All other
    tables, columns and metadata remain part of the equality assertion.
    """
    normalized = {}
    for table, rows in records.items():
        if table in EXECUTION_LEDGER:
            continue
        if table == "sites":
            normalized[table] = sorted((row[0], _site(row[1])) for row in rows)
        else:
            normalized[table] = rows
    return normalized


def assert_semantic_equal(actual, expected):
    a, b = semantic_snapshot(actual), semantic_snapshot(expected)
    for table in a.keys() | b.keys():
        assert a.get(table) == b.get(table), table
