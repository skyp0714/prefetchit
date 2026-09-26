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

planner = module("wake_planner", ROOT.parent / "flat_codegen/dsb_build/media/ws/ws_plan_pass.py")

def test_merge_prefers_frequent_context_and_accounts_for_hint_cost():
    rare = ("rare", 0, 0, 64, "app", 64)
    common = ("common", 0, 1, 128, "lib", 128)
    direct = ("direct", 0, 0, 192, "app", 192)
    scores = {("app", 64): 1, ("lib", 128): 10, ("app", 192): 8}
    candidates = [rare, common, direct, common]
    assert planner.merge_targets(candidates, scores, 1) == [rare]
    assert planner.merge_targets(candidates, scores, 1, "support") == [common]
    assert planner.merge_targets(candidates, scores, 1, "byte-efficiency") == [direct]
    assert len(planner.merge_targets(candidates, scores, 8, "support")) == 3

def test_planner_cli_changes_capped_target_and_reports_postcap_coverage(tmp_path):
    source = tmp_path / "app.c"
    source.write_text('void __attribute__((noinline, aligned(64))) site(void) {}\n'
                      'void __attribute__((noinline, aligned(64))) rare_target(void) {}\n'
                      'void __attribute__((noinline, aligned(64))) common_target(void) {}\n'
                      'int main(void) { site(); return 0; }\n')
    symfs = tmp_path / "symfs"
    (symfs / "custom").mkdir(parents=True)
    binary = symfs / "custom/app"
    subprocess.run(["cc", "-no-pie", str(source), "-o", str(binary)], check=True)
    symbols = {}
    for row in subprocess.check_output(["nm", "-n", str(binary)], text=True).splitlines():
        fields = row.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    trace = tmp_path / "trace"
    runs = trace / "runs"
    runs.mkdir(parents=True)
    (trace / "maps.txt").write_text("00400000-00500000 r-xp 00000000 00:00 1 /custom/app\n")
    (trace / "branches.txt").write_text(f"123 1.000000: call 0 => {symbols['site']:x}\n" * 6)
    (runs / "runs.tsv").write_text("tid\tin\tdur\thook\tmethod\tj\tm\n" +
                                  "1\t1\t1\tany\ta_rare\t0\t0\n" +
                                  "1\t1\t1\tany\tz_common\t0\t0\n" * 5)
    for context, target in [("a_rare", "rare_target"), ("z_common", "common_target")]:
        (runs / f"list_{context}__m0.tsv").write_text(
            "#rank\tp\tidx_med\tus_med\tdso\telf_line\tsym+off\tpseq\n" +
            f"0\t1\t0\t0\tapp\t{symbols['site']:#x}\tsite\t0\n" +
            f"1\t1\t8\t1\tapp\t{symbols[target]:#x}\t{target}\t0\n")
    instrumentable = tmp_path / "sites.txt"
    instrumentable.write_text("site\n")
    for policy, expected, coverage in [("input-order", "rare_target", 100/12),
                                        ("support", "common_target", 500/12)]:
        output = tmp_path / f"{policy}.json"
        subprocess.run([sys.executable, str(ROOT.parent / "flat_codegen/dsb_build/media/ws/ws_plan_pass.py"),
                        str(runs), str(trace), str(output), "--symfs", str(symfs), "--exe", "/custom/app",
                        "--instrumentable", str(instrumentable), "--d", "1", "--dmax", "4",
                        "--k", "1", "--kmerge", "1", "--merge-policy", policy],
                       check=True, capture_output=True, text=True)
        result = json.loads(output.read_text())
        assert result["sites"]["site"]["t"][0][0] == expected
        metadata = json.loads(output.with_name(output.name + ".metadata.json").read_text())
        assert metadata["entry_candidate_weighted_coverage_pct"] == pytest.approx(coverage)
