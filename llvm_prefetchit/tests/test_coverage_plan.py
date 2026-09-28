from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from coverage_plan import choose_keys


def row(key, target, caller='f', **kwargs):
    return dict(key=key, target=target, module='m', function=caller,
                active=True, direct=True, **kwargs)


def test_miss_ranking_keeps_physical_copies_without_spending_extra_budget():
    records = [row('low', 64), row('hot', 128), row('hot', 192),
               row('other', 256, 'g')]
    selected = choose_keys(records, {64: 1, 128: 9, 192: 9, 256: 2}, 1)
    assert selected == {'hot', 'other'}
    assert choose_keys(list(reversed(records)), {64: 1, 128: 9, 192: 9, 256: 2}, 1) == selected


def test_unranked_targets_fail_instead_of_silently_dropping():
    with pytest.raises(ValueError, match='Unranked'):
        choose_keys([row('missing', 64)], {}, 1)


def test_stable_ties_and_positive_budget():
    assert choose_keys([row('b', 64), row('a', 128)], {64: 1, 128: 1}, 1) == {'a'}
    with pytest.raises(ValueError, match='Positive'):
        choose_keys([], {}, 0)
