import importlib.util
from pathlib import Path
import re
import sys


tools = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(tools))
spec = importlib.util.spec_from_file_location('lbr_padding', tools / 'lbr_padding_prefetch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_mapping_uses_elf_virtual_address_for_exec_and_pie():
    pattern = re.compile('target')
    maps = '00401000-00403000 r-xp 00001000 00:00 1 /target\n'
    assert module.mapping_bias(maps, pattern, [(0x401000, 0x1000, 0x1000)]) == 0
    maps = '70001000-70003000 r-xp 00001000 00:00 1 /target\n'
    assert module.mapping_bias(maps, pattern, [(0x1000, 0x1000, 0x1000)]) == 0x70000000


def test_cycles_belong_to_interval_ending_at_newer_branch():
    bias = 0x70000000
    edges = [(bias + 1100, 'target', bias + 1200, 'target', 100),
             (bias + 900, 'target', bias + 1000, 'target', 50),
             (bias + 700, 'target', bias + 800, 'target', 3)]
    # The 1080 slot is only 20 estimated cycles before the final branch.
    # 1020 is 80 cycles before it; 850 is 125 cycles before it.
    got = module.candidate_sites(edges, [750, 850, 1020, 1080, 1150], bias,
                                 re.compile('target'), 64, 128)
    assert got == {850, 1020}


def test_unknown_timing_and_cross_dso_intervals_do_not_invent_sites():
    edges = [(1100, 'other', 1200, 'target', 100),
             (900, 'target', 1000, 'target', None),
             (700, 'target', 800, 'target', 3)]
    assert module.candidate_sites(edges, [850, 1020], 0,
                                  re.compile('target'), 0, 1000) == set()


def test_perf_pid_and_parenthesized_dso_are_parsed():
    line = (' 123 7f1000 (/tmp/a (copy)) '
            '0x7f0200 (/tmp/a (copy))/0x7f1000 (/tmp/a (copy))/P/-/-/84/CALL/-')
    header = module.HEADER.match(line)
    assert header.groups() == ('123', '7f1000', '(/tmp/a (copy))')
    assert module.EDGE.findall(line) == [('7f0200', '(/tmp/a (copy))',
                                        '7f1000', '(/tmp/a (copy))', '84', 'CALL')]


def test_unknown_branch_type_preserves_interval_edges():
    line = '0x200 (target)/0x300 (target)/P/-/-/84/-/-'
    assert module.EDGE.findall(line) == [('200', '(target)', '300', '(target)', '84', '-')]


def test_density_bound_preserves_vote_order_and_budget():
    ranked = [(10, 100, 500, 1., 10), (9, 130, 600, 1., 9),
              (8, 180, 700, 1., 8), (7, 300, 800, 1., 7)]
    assert [r[1] for r in module.select_spaced(ranked, 2, 64)] == [100, 180]
    assert module.select_spaced(ranked, 2, 0) == ranked[:2]


def test_heldout_mapping_and_each_miss_has_one_candidate_set(tmp_path):
    maps = tmp_path / 'maps'
    maps.write_text('00001000-00003000 r-xp 00001000 00:00 1 /target\n')
    sample = tmp_path / 'samples'
    sample.write_text('123 1800 (/target) '
        '0x1400 (/target)/0x1700 (/target)/P/-/-/100/-/- '
        '0x1100 (/target)/0x1200 (/target)/P/-/-/50/-/-\n')
    counts = module.collections.Counter()
    result = list(module.sample_candidates(sample, [0x1280, 0x1380],
        [(0x1000, 0x1000, 0x2000)], re.compile('target'), 50, 100, maps, counts=counts))
    assert result == [(0x1800, {0x1280})]
    assert counts['all_samples'] == 1 and counts['parsed_branch_edges'] == 2
