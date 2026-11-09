"""Full-build oracle comparison for published semantics and source dependencies.

Owner traversal ledgers are checked by separate functional invalidation tests.
Jedi observation, original site evidence and source subscriptions are compared
without normalizing away distinct reasons or locations.
"""

import json


EXECUTION_LEDGER = {"unit_analysis_reads", "unit_analysis_watches", "unit_input_events"}


def semantic_snapshot(records):
    """Ignore only owner work ledgers and Jedi candidate order.

    Raw candidates are a multiset of complete records; duplicate observations,
    parameters within a candidate, reasons and original site locations survive.
    """
    normalized = {table: rows for table, rows in records.items()
                  if table not in EXECUTION_LEDGER}
    if "sites" in normalized:
        sites = []
        for ordinal, data in normalized["sites"]:
            site = json.loads(data)
            for evidence in site.get("evidence", ()):
                if evidence.get("tool") == "jedi" and isinstance(evidence.get("raw"), list):
                    evidence["raw"] = sorted(evidence["raw"],
                                             key=lambda row: json.dumps(row, sort_keys=True))
            sites.append((ordinal, json.dumps(site, sort_keys=True)))
        normalized["sites"] = sorted(sites)
    return normalized


def assert_semantic_equal(actual, expected):
    a, b = semantic_snapshot(actual), semantic_snapshot(expected)
    for table in a.keys() | b.keys():
        assert a.get(table) == b.get(table), table
