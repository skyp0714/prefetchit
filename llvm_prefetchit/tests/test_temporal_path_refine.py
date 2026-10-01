import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from temporal_path_refine import next_line_description, share_anchors


def test_next_line_requires_same_destination_image_and_free_slot():
    call=dict(targets=[64])
    assert next_line_description('source',call,'source',128)==dict(kind='local',target=128)
    assert next_line_description('source',call,'other',128) is None
    assert next_line_description('source',call,'source',64) is None
    assert next_line_description('source',call,'source',192) is None
    assert next_line_description('source',dict(targets=list(range(0,512,64))),'source',512) is None


def test_next_line_reuses_the_original_got_anchor():
    call=dict(targets=[],got_targets=[dict(target_sha='target',target=192,got=8192,anchor=1000,addend=-808)])
    assert next_line_description('source',call,'target',260)==dict(kind='cross',target=260,got=8192,anchor=1000,addend=-740)
    assert next_line_description('source',call,'source',260) is None


def test_shared_anchor_preserves_targets_and_reuses_one_load():
    plan=dict(calls=[dict(targets=[123],got_targets=[
        dict(target_sha='library',target=192,got=8192,anchor=1000,addend=-808),
        dict(target_sha='library',target=1024,got=16384,anchor=2000,addend=-976)])])
    anchors={('source','library'):[dict(got=8192,anchor=1000,observations=2),dict(got=16384,anchor=2000,observations=20)]}
    result=share_anchors('source',plan,anchors)
    assert result['calls'][0]['targets']==[123]
    hints=result['calls'][0]['got_targets']
    assert {t['got'] for t in hints}=={16384}
    assert {t['anchor']+t['addend'] for t in hints}=={192,1024}
    assert plan['calls'][0]['got_targets'][0]['got']==8192
