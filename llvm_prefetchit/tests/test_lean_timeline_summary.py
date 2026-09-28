"""Keep request, main-image, and all-event denominators distinct."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from lean_timeline_summary import summarize


def test_residual_coverage_is_conditional_on_main_image_not_all_events(tmp_path):
    def save(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data))
    save(tmp_path/'protocol.json',dict(trials=[dict(name='selected',concurrency=4)]))
    save(tmp_path/'complete.json',dict(trials=1))
    trial=tmp_path/'00_selected';capture=trial/'movie_p3'
    save(trial/'complete.json',dict(valid=True,captures=[str(capture)]))
    bins=[dict(lo_us=0,hi_us=10,estimated_events=12),dict(lo_us=10,hi_us=20,estimated_events=30)]
    save(capture/'timeline.json',dict(bins=bins,quality={},median_run_us=12,p90_run_us=30))
    save(capture/'target_overlap.json',dict(bins=[dict(bins[0],main=9,static_target_line=6),
        dict(bins[1],main=30,static_target_line=6)],coverage_applicable=True,
        target_lines=2,top_unique_functions=[]))
    save(capture/'request_window.json',dict(completed_requests=6))
    row=summarize(tmp_path)['rows'][0]
    assert row['all']['estimated_events_per_request']==7
    assert row['all']['static_target_overlap_pct_of_main']==pytest.approx(100*12/39)
    assert row['peak10_20']['estimated_events_per_request']==5
    assert row['peak10_20']['static_target_overlap_pct_of_main']==20
    assert row['peak10_20']['share_pct']==pytest.approx(100*30/42)


def test_counter_only_window_never_invents_miss_rates(tmp_path):
    trial=tmp_path/'00_counters';trial.mkdir()
    (tmp_path/'protocol.json').write_text(json.dumps(dict(trials=[dict(name='counters',concurrency=4)])))
    (tmp_path/'complete.json').write_text(json.dumps(dict(trials=1)))
    (trial/'complete.json').write_text(json.dumps(dict(valid=True,gate_only=True,captures=[])))
    (trial/'gate_only.json').write_text(json.dumps(dict(services={'movie':dict(delta=dict(checks=5,eligible=2))},
        request_window=dict(completed_requests=100))))
    row=summarize(tmp_path)['rows'][0]
    assert row['gate_only'] and row['counter_build'] and row['period'] is None
    assert row['gate']['eligible']==2
    assert 'bins' not in row and 'peak10_20' not in row
