import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

analysis = module("wake_headroom", ROOT / "tools/analyze_wake_headroom.py")

def test_trace_missing_rare_types_are_not_renormalized(tmp_path):
    (tmp_path / "runs.tsv").write_text("method\tfirst_mark\tdistinct_lines\n"
                                       "a\t0\t100\na\t0\t100\nrare\t0\t100\n")
    (tmp_path / "list_a__m0.tsv").write_text("#rank\tp\tidx_med\tus_med\tdso\telf_line\tsym+off\tpseq\n"
                                           "0\t1.00\t0\t1\tapp\t0x1000\tf\t0\n")
    result = analysis.analyze(tmp_path)
    policy = next(x for x in result["policies"] if x["budget"] == 8 and x["p_min"] == .5 and x["horizon"] == 32)
    assert result["represented_runs"] == 2
    assert policy["global_expected_touched_per_run"] == pytest.approx(2/3)
    assert policy["global_total_first_touch_coverage_pct"] == pytest.approx(2/3)
    strict = next(x for x in result["policies"] if x["budget"] == 8 and x["p_min"] == .8 and x["horizon"] == 32)
    assert strict["global_issued_per_run"] == 0
    assert strict["oracle_context_expected_touched_per_run"] == pytest.approx(2/3)
