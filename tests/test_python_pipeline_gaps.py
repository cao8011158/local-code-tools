"""Former acceptance gaps, retained as strict regressions without changing their oracle.

Run explicitly or as part of tests/. No xfail or skip hides unsupported behavior.
"""

from pathlib import Path

from tests.test_python_pipeline import analyze, expect

FIXTURES = Path(__file__).parent / "fixtures" / "python_pipeline"


def test_generator_contextmanager_binding(tmp_path):
    text = (FIXTURES / "generator_context.py").read_text(encoding="utf-8-sig")
    result = analyze(tmp_path, {"demo.py": text})
    s = expect(
        result, "resource.work", "caller", {"Resource.work"}, unknown=False, complete=True
    )
    assert s["phase"] == "body"
    assert s["target_provider"] == "jedi-get-signatures"


def test_separate_instance_registries(tmp_path):
    text = (FIXTURES / "instance_registries.py").read_text(encoding="utf-8-sig")
    result = analyze(tmp_path, {"demo.py": text})
    s = expect(result, "self.handlers['go']", "Registry.dispatch", set(),
               unknown=True, complete=False, forbidden={"a", "b"})
    assert s["unresolved_reasons"] == ["jedi-no-result"]
