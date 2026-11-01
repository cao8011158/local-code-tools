"""Reject semantic losses and fabricated gains in the limited-budget oracle."""

import copy
import ast
import json

import pytest

from lct.common import canonical, digest
from tests.limited_precision_comparison import assert_limited_refinement


SOURCE = "class Kind: pass\nclass Origin:\n    kind: Kind\ndef validate(value):\n    value[\"xp\"]\n"
PATH = "src/sample.py"
REPO = "sample"
ORIGIN = "sample:src/sample.py:class:Origin#1"
KIND = "sample:src/sample.py:class:Kind#1"
OWNER = "sample:src/sample.py:function:validate#1"


def _fixture():
    def node(identifier, name, line, version):
        data = dict(node_id=identifier, name=name, definition_line=line,
                    path=PATH, repository=REPO, version_id=version,
                    kind="function" if identifier == OWNER else "class")
        return (identifier, REPO, PATH, data["kind"], json.dumps(data), "hash")
    module_data = dict(node_id="sample:src/sample.py:module:sample#1", kind="module",
                       repository=REPO, path=PATH, snapshot_id="capture-snapshot",
                       definition_line=1)
    module = (module_data["node_id"], REPO, PATH, "module", json.dumps(module_data), "hash")

    edge = dict(basis="AST value reference; never implies invocation", phase="annotation",
                source_version_id="v-origin", target_version_id="v-kind", expression="Kind",
                line=3, column=10)
    eager = ("edge-annotation", ORIGIN, KIND, "REFERENCES", "resolved", json.dumps(edge))
    call = ("edge-call", OWNER, KIND, "CALLS", "unknown", "{}")
    location = dict(repository=REPO, path=PATH, line=5, column=4,
                    end_line=5, end_column=15, expression="value['xp']")
    site_key = [REPO, PATH, module_data["snapshot_id"], 5, 4, 5, 15]
    base = dict(origin="unknown-container-universe", key_kind="range", key=None,
                read_owner=OWNER, read_site=digest(canonical(site_key + ["container-read"])),
                read_location=location,
                unknown_reasons=["open-project-input"])
    propagated = dict(base, consumer_owner="other-consumer", consumer_site="propagated-site",
                      consumer_location=dict(location, line=4))
    direct = dict(base, consumer_owner=OWNER,
                  consumer_site=digest(canonical(site_key + ["read"])),
                  consumer_location=location)
    def subscription(identifier, record):
        return (digest(canonical(record)) if identifier == "direct" else identifier,
                record["origin"], record["key_kind"], "None",
                record["read_owner"], record["read_site"], record["consumer_owner"],
                record["consumer_site"], json.dumps(record))
    site = ("0", json.dumps(dict(site_id="site", complete=False, targets=[],
                                  unknown_origin=True, unresolved_reasons=["open-project-input"])))
    fresh = dict(nodes=sorted([module, node(ORIGIN, "Origin", 2, "v-origin"),
                               node(KIND, "Kind", 1, "v-kind"),
                               node(OWNER, "validate", 4, "v-validate")]),
                 edges=[call], sites=[site], unit_source_supports=[("support", "source")],
                 unit_container_subscriptions=[subscription("propagated", propagated)],
                 unit_container_writes=[("write", "record")],
                 analysis_input_consumers=[("capture", OWNER, REPO, PATH, "2")],
                 unit_analysis_reads=[])
    actual = copy.deepcopy(fresh)
    actual["edges"] = sorted([call, eager])
    actual["unit_container_subscriptions"] = sorted([
        subscription("propagated", propagated), subscription("direct", direct)])
    actual["analysis_input_consumers"] = [("capture", OWNER, REPO, PATH, "3")]
    return actual, fresh, {(REPO, PATH): SOURCE}


def test_limited_precision_accepts_only_source_backed_refinement():
    assert_limited_refinement(*_fixture())


@pytest.mark.parametrize("mutation", [
    "lost-call", "changed-target", "lost-support", "lost-subscription", "changed-unknown",
    "fake-annotation", "fake-consumer", "fake-source-site", "fake-row-digest",
    "fake-consumer-site", "new-call",
])
def test_limited_precision_rejects_semantic_mutation(mutation):
    actual, fresh, sources = _fixture()
    if mutation == "lost-call":
        actual["edges"] = [edge for edge in actual["edges"] if edge[3] != "CALLS"]
    elif mutation == "changed-target":
        actual["edges"] = [("edge-call", OWNER, ORIGIN, "CALLS", "unknown", "{}")
                           if edge[3] == "CALLS" else edge for edge in actual["edges"]]
    elif mutation == "lost-support":
        actual["unit_source_supports"] = []
    elif mutation == "lost-subscription":
        actual["unit_container_subscriptions"] = actual["unit_container_subscriptions"][:1]
    elif mutation == "changed-unknown":
        actual["sites"] = [("0", json.dumps(dict(site_id="site", complete=True,
                                                   targets=[], unknown_origin=False)))]
    elif mutation == "fake-annotation":
        index = next(i for i, edge in enumerate(actual["edges"]) if edge[3] == "REFERENCES")
        row = list(actual["edges"][index]); data = json.loads(row[-1]); data["line"] = 1
        row[-1] = json.dumps(data); actual["edges"][index] = tuple(row)
    elif mutation == "fake-consumer":
        row = list(actual["unit_container_subscriptions"][0]); data = json.loads(row[-1])
        data["consumer_owner"] = "invented"; row[-1] = json.dumps(data)
        actual["unit_container_subscriptions"][0] = tuple(row)
    elif mutation == "fake-source-site":
        row = list(actual["unit_container_subscriptions"][0]); data = json.loads(row[-1])
        data["read_site"] = "unmatched"; row[-1] = json.dumps(data)
        actual["unit_container_subscriptions"][0] = tuple(row)
    elif mutation == "fake-row-digest":
        row = list(actual["unit_container_subscriptions"][0]); row[0] = "invented"
        actual["unit_container_subscriptions"][0] = tuple(row)
    elif mutation == "fake-consumer-site":
        row = list(actual["unit_container_subscriptions"][0]); data = json.loads(row[-1])
        data["consumer_site"] = "invented"; row[7] = "invented"
        row[-1] = json.dumps(data); row[0] = digest(canonical(data))
        actual["unit_container_subscriptions"][0] = tuple(row)
    elif mutation == "new-call":
        actual["edges"].append(("invented", OWNER, ORIGIN, "CALLS", "resolved", "{}"))
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, sources)


def test_class_local_binding_before_annotation_is_not_module_target():
    actual, fresh, sources = _fixture()
    actual["unit_container_subscriptions"] = fresh["unit_container_subscriptions"][:]
    sources[REPO, PATH] = SOURCE.replace("    kind: Kind", "    Kind = int\n    kind: Kind")
    edge_index = next(i for i, row in enumerate(actual["edges"]) if row[3] == "REFERENCES")
    row = list(actual["edges"][edge_index]); evidence = json.loads(row[-1]); evidence["line"] = 4
    row[-1] = json.dumps(evidence); actual["edges"][edge_index] = tuple(row)
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, sources)


def test_function_body_annotation_is_not_eager_class_reference():
    actual, fresh, sources = _fixture()
    actual["unit_container_subscriptions"] = fresh["unit_container_subscriptions"][:]
    sources[REPO, PATH] = SOURCE.replace("class Origin:", "def Origin():")
    for snapshot in (actual, fresh):
        rows = []
        for row in snapshot["nodes"]:
            if row[0] != ORIGIN:
                rows.append(row); continue
            values = list(row); data = json.loads(values[4]); data["kind"] = "function"
            values[3] = "function"; values[4] = json.dumps(data); rows.append(tuple(values))
        snapshot["nodes"] = rows
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, sources)


@pytest.mark.parametrize("later", [
    "def mutate():\n    global Kind\n    Kind=1\n",
    "@(Kind := lambda f: f)\ndef decorated(): pass\n",
])
def test_later_global_or_definition_header_rebind_rejects_body_gain(later):
    content = "class Kind: pass\ndef use():\n    Kind\n" + later
    module = f"{REPO}:{PATH}:module:sample#1"
    kind = f"{REPO}:{PATH}:class:Kind#1"
    owner = f"{REPO}:{PATH}:function:use#1"
    def row(identifier, name, kind_name, line, parent):
        data = dict(node_id=identifier, name=name, kind=kind_name,
                    repository=REPO, path=PATH, parent=parent,
                    version_id="v-" + name, definition_line=line)
        return (identifier, REPO, PATH, kind_name, canonical(data), "hash")
    nodes = sorted([row(module, "sample", "module", 1, ""),
                    row(kind, "Kind", "class", 1, module),
                    row(owner, "use", "function", 2, module)])
    token = next(n for n in ast.walk(ast.parse(content)) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load) and n.id == "Kind")
    fact = dict(source=owner, target=kind, kind="REFERENCES", status="resolved",
                source_version_id="v-use", target_version_id="v-Kind",
                basis="AST value reference; never implies invocation", phase="body",
                expression="Kind", line=token.lineno, column=token.col_offset)
    fact["edge_id"] = digest(canonical(fact))
    actual = dict(nodes=nodes, edges=[(fact["edge_id"], owner, kind,
                                      "REFERENCES", "resolved", canonical(fact))])
    fresh = dict(nodes=nodes, edges=[])
    with pytest.raises(AssertionError):
        assert_limited_refinement(actual, fresh, {(REPO, PATH): content})
