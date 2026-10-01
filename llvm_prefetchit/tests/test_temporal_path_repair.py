from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/class_b'))
from temporal_path_repair import description


def test_existing_call_can_reach_nonadjacent_line_without_duplicate():
    call = dict(targets=[0x1000])
    assert description('a', call, 'a', 0x3100, {}) == dict(kind='local', target=0x3100)
    assert description('a', call, 'a', 0x1007, {}) is None


def test_capacity_and_unobserved_got_are_rejected():
    assert description('a', dict(targets=list(range(8))), 'a', 0x3100, {}) is None
    assert description('a', dict(targets=[]), 'b', 0x3100, {}) is None


def test_cross_image_reuses_highest_support_anchor():
    anchors = {('a', 'b'): [dict(got=32, anchor=0x1000, observations=9),
                           dict(got=40, anchor=0x2000, observations=2)]}
    result = description('a', dict(targets=[]), 'b', 0x3000, anchors)
    assert result['got'] == 32 and result['anchor'] + result['addend'] == 0x3000
