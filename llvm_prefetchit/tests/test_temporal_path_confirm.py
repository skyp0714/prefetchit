from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts/class_b'
sys.path.insert(0, str(SCRIPTS))
import temporal_path_confirm as confirm


def rows(name, rps, cpu=100, p99=10):
    return [dict(arm=name, valid=True, achieved_rps=rps,
                 metrics=dict(stack_cpu=cpu, p99_ms=p99)) for _ in range(2)]


def test_selection_rejects_cpu_and_tail_regressions():
    samples = rows('base', 100) + rows('fast', 110) + rows('cpu', 120, 101) + rows('tail', 125, p99=10.3)
    assert confirm.select(samples, 'base', ['fast', 'cpu', 'tail'])['selected'] == 'fast'


def test_base_is_retained_when_qualifying_refinement_is_slower():
    assert confirm.select(rows('base', 100) + rows('slow', 99), 'base', ['slow'])['selected'] == 'base'


def test_cleanup_retains_shared_binaries_and_records_deleted_hash(tmp_path):
    folder = tmp_path / 'builds/rejected'
    folder.mkdir(parents=True)
    unused = folder / 'unused'
    shared = folder / 'shared'
    unused.write_bytes(b'\x7fELFunused')
    shared.write_bytes(b'\x7fELFshared')
    patch = folder / 'record.json'
    patch.write_text('{}')
    confirm.cleanup(tmp_path, ['rejected'], [dict(overrides={'a': str(shared)}, mongo_binary=str(shared))])
    import json
    record = json.loads((tmp_path / 'screen2_rejected_cleanup.json').read_text())
    assert record['complete'] and record['bytes_removed'] == 10
    assert len(record['files']) == 1 and len(record['files'][0]['sha256']) == 64
    assert shared.exists() and patch.exists() and not unused.exists()
