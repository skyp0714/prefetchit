import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from temporal_path_residual import policy_index


def test_cross_image_witness_uses_original_target_identity():
    known={
        'patched_source':dict(source_sha256='source',patches=[dict(
            stub=100,terminal_jumps=[140],targets=[64],got_targets=[dict(target_sha='target',target=192)])]),
        'patched_target':dict(source_sha256='target',patches=[]),
    }
    jumps,targets,ranges=policy_index(['patched_source','patched_target'],known)
    assert jumps[0,140]=={(0,1),(1,3)}
    assert targets=={0:{1},1:{3}}
    assert ranges[0]==[(100,145)]


def test_legacy_plain_stub_and_reject_missing_got_witness():
    policy=dict(source_sha256='source',patches=[dict(stub=100,targets=[128,192])])
    assert policy_index(['patched'],{'patched':policy})[0][0,114]=={(0,2),(0,3)}
    policy['patches'][0]['got_targets']=[dict(target_sha='target',target=64)]
    with pytest.raises(AssertionError,match='terminal jump'):
        policy_index(['patched','target'],{'patched':policy})
