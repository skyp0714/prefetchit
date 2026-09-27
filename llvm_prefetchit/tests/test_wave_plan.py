"""Address relocation, future-stage selection, and non-additive coverage."""
import importlib.util
from pathlib import Path
import sys

scripts = Path(__file__).resolve().parents[1]/'scripts/class_b'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('wave_plan', scripts/'wave_plan.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_runtime_ip_resolves_through_file_offset_to_elf_line():
    images = {'/app':dict(segments=[(0x1000,0x401000,0x2000)],
                         mappings=[(0x71001000,0x71003000,0x1000)])}
    assert m.resolve_ip(0x71001117, images) == ('/app', 0x401100)
    assert m.resolve_ip(0xdead, images) is None


def test_stages_use_future_bin_and_unique_targets_without_sparse_padding():
    rows = [dict(path='/app',va=64,age_us=1,samples=30),
            dict(path='/app',va=128,age_us=1,samples=20),
            dict(path='/app',va=64,age_us=3,samples=90),
            dict(path='/app',va=192,age_us=3,samples=10),
            dict(path='/app',va=256,age_us=4,samples=9)]
    selected = m.fit(rows,2,2,4)
    assert [(r['va'],r['issue_us']) for r in selected] == [(64,0),(128,0),(192,2),(256,2)]
    heldout = [dict(path='/app',va=64,age_us=2,samples=10),
               dict(path='/app',va=192,age_us=1,samples=10),
               dict(path='/app',va=512,age_us=5,samples=20)]
    result = m.evaluate(selected, heldout)
    assert result['address_coverage_pct'] == 50
    assert result['nominally_early_coverage_pct'] == 25
