"""Independent public-path boundaries for explicit artifact publication/backup."""
import copy
import sqlite3
from pathlib import Path

import pytest

from lct.common import ToolError
from lct.management import backup
from lct.storage import current, manifest, validate_folder
from tests.synthetic_support import build_fixture, initialize


@pytest.mark.parametrize('extension', ['.npy', '.json', '.usearch'])
def test_missing_dense_part_refuses_backup(tmp_path, extension):
    c, _ = initialize(tmp_path/'fixture')
    m = build_fixture(c)
    folder, _ = manifest(c)
    (folder/(m['partitions'][0]['stem']+extension)).unlink()
    with pytest.raises(ToolError, match='artifact unavailable'):
        backup(c)
    assert current(c) == m['version']
    assert not list((Path(c['data'])/'backups').glob('*.zip'))


def test_manifest_cannot_bless_incidental_file(tmp_path):
    c, _ = initialize(tmp_path/'fixture')
    m = build_fixture(c)
    folder, _ = manifest(c)
    bad = copy.deepcopy(m)
    bad['artifacts']['foreign.log'] = '0'*64
    (folder/'foreign.log').write_text('not an index artifact')
    with pytest.raises(ToolError, match='membership mismatch'):
        validate_folder(folder, bad, full=False)


def test_real_live_wal_is_rejected_without_checkpoint(tmp_path):
    c, _ = initialize(tmp_path/'fixture')
    m = build_fixture(c)
    folder, _ = manifest(c)
    db = sqlite3.connect(folder/'catalog.sqlite')
    try:
        assert db.execute('pragma journal_mode=wal').fetchone()[0] == 'wal'
        db.execute('create table external_mutation(value)')
        db.commit()
        wal = folder/'catalog.sqlite-wal'
        before = wal.read_bytes()
        assert before
        with pytest.raises(ToolError, match='nonempty SQLite sidecar'):
            backup(c)
        assert wal.read_bytes() == before
        assert current(c) == m['version']
    finally:
        db.close()
