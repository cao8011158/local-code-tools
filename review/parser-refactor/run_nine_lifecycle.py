"""Observe each real acceptance build without changing its input or analysis."""
import json
import signal
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from tests import test_batch3_actual_acceptance as acceptance

class PhaseDeadline(BaseException):
    pass

def stop(*_):
    raise PhaseDeadline('one public build exceeded the prior 180-second diagnostic bound')

actual = acceptance.build
root = Path(tempfile.mkdtemp(prefix='pr1-review1-nine-'))
print(json.dumps(dict(stage='start', root=str(root))), flush=True)
sequence = 0

def observed(*args, **kwargs):
    global sequence
    sequence += 1
    started = time.monotonic()
    print(json.dumps(dict(stage='build-start', sequence=sequence)), flush=True)
    signal.alarm(180)
    try:
        result = actual(*args, **kwargs)
    finally:
        signal.alarm(0)
    print(json.dumps(dict(stage='build-finished', sequence=sequence,
                          seconds=round(time.monotonic()-started, 3),
                          version=result['version'], graph=result['graph'],
                          incremental=result['incremental'])), flush=True)
    return result

signal.signal(signal.SIGALRM, stop)
with patch.object(acceptance, 'build', observed):
    acceptance.test_nine_original_bytes_limited_graph_bm25_and_attached_real_usearch(root)
print(json.dumps(dict(stage='lifecycle-pass', root=str(root))), flush=True)
