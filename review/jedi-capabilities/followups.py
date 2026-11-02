"""Small follow-ups to separate API errors, inputs and query choices."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

import jedi

from cases import BY_ID
from probe import environment, worker


def child(ident, config, fix_usage):
    errors = []
    if fix_usage:
        # Diagnostic only, never a production mutation or target rule.
        # This mirrors the already existing Parso 0.8.7 usage-timestamp shim.
        import parso.cache as cache
        original_insert = cache._set_cache_item

        def insert(grammar, path, item):
            item.last_used = cache.time.time()
            return original_insert(grammar, path, item)

        cache._set_cache_item = insert
    for api in ("infer", "goto", "get_signatures"):
        original = getattr(jedi.Script, api)

        def observed(*args, _api=api, _original=original, **kwargs):
            try:
                return _original(*args, **kwargs)
            except Exception:
                errors.append(dict(api=_api, traceback=traceback.format_exc(limit=25)))
                raise

        setattr(jedi.Script, api, observed)
    result = worker(BY_ID[ident], config, "source_first")
    result.update(tracebacks=errors, diagnostic_cache_usage_refresh=fix_usage)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child")
    parser.add_argument("--config", default="{}")
    parser.add_argument("--fix-usage", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child, json.loads(args.config), args.fix_usage)
        return
    if not args.output:
        parser.error("--output is required")
    runs = []
    for ident, config, fix in [
        ("direct", {"fast_parser": False}, False),
        ("classmethod", {"fast_parser": False}, False),
        ("classmethod", {"fast_parser": False}, True),
        ("dict_register", {"fast_parser": False}, True),
        ("dict_cross_module_write", {"fast_parser": False}, True),
        ("recursive_parameters", {"fast_parser": False}, True),
    ]:
        argv = [sys.executable, str(Path(__file__).resolve()), "--child", ident,
                "--config", json.dumps(config)]
        if fix:
            argv.append("--fix-usage")
        process = subprocess.run(argv, capture_output=True, text=True, timeout=25)
        if process.returncode:
            raise RuntimeError(process.stderr)
        runs.append(json.loads(process.stdout))
    # Isolate the path-bearing Script constructor from target language features.
    program = """
import jedi,tempfile,json,sys,traceback
from pathlib import Path
jedi.settings.fast_parser=False
source='def f():pass\\ndef run():f()\\n'
with tempfile.TemporaryDirectory(prefix='jedi-path-control-') as directory:
 path=Path(directory)/'demo.py';path.write_text(source)
 mode,sequence=sys.argv[1:]
 if mode=='code_only':script=jedi.Script(code=source)
 elif mode=='path_only':script=jedi.Script(path=path)
 elif mode=='code_and_path':script=jedi.Script(code=source,path=path)
 else:script=jedi.Script(code=source,path=path,project=jedi.Project(directory))
 rows=[]
 for api in (['get_signatures'] if sequence=='signature_only' else
             ['infer','goto','get_signatures']):
  try:
   column=12 if api=='get_signatures' else 11
   names=getattr(script,api)(2,column)
   rows.append(dict(api=api,results=[dict(name=n.name,type=n.type,line=n.line) for n in names]))
  except Exception as error:
   rows.append(dict(api=api,error=type(error).__name__,traceback=traceback.format_exc(limit=12)))
 print(json.dumps(dict(mode=mode,sequence=sequence,rows=rows)))
"""
    path_controls = []
    for mode in ("code_only", "path_only", "code_and_path", "explicit_project"):
        for sequence in ("signature_only", "source_first"):
            process = subprocess.run([sys.executable, "-c", program, mode, sequence],
                                     capture_output=True, text=True, timeout=15)
            if process.returncode:
                raise RuntimeError(process.stderr)
            path_controls.append(json.loads(process.stdout))
    args.output.write_text(json.dumps(dict(environment=environment(), runs=runs,
                                          path_control_source=program, path_controls=path_controls,
                                          source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
                                      indent=2) + "\n")
    print(json.dumps(dict(runs=len(runs), path_controls=len(path_controls), output=str(args.output))))


if __name__ == "__main__":
    main()
