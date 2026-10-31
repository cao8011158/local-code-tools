"""Root-owned invalidation checks for ambiguous new writer receivers."""
import runpy
from pathlib import Path

import pytest

from lct.storage import build

helpers = runpy.run_path(str(Path(__file__).parent / "test_owner_update_independent.py"))
fixture, oracle = helpers["fixture"], helpers["oracle"]


@pytest.mark.parametrize("writer", [
    "from provider import one as registry\nfrom provider import two as registry\n"
    "from provider import second\ndef mutate(): pass\n",
    "from provider import one, two, second\nregistry=one\nregistry=two\n"
    "def mutate(): pass\n",
    "from provider import one as registry, two, second\n"
    "def mutate(flag):\n    if flag: registry=two\n    pass\n",
])
def test_new_write_uses_reaching_receiver_or_explicitly_falls_back(tmp_path, writer):
    config, repo = fixture(tmp_path, {
        "provider.py": "def first(): pass\ndef second(): pass\n"
                       "one={'go':first}\ntwo={'go':first}\n",
        "consumer.py": "from provider import one,two\ndef left(): one['go']()\n"
                       "def right(): two['go']()\n",
        "writer.py": writer,
    })
    build(config, offline=True, lexical_only=True)
    (repo / "src/writer.py").write_text(writer.replace("pass", "registry['go']=second"))
    updated = build(config, offline=True, lexical_only=True)
    oracle(config, updated["version"], tmp_path)
