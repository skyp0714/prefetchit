import importlib.util
from pathlib import Path
import struct
import pytest

PATH=Path(__file__).resolve().parents[1]/'scripts/class_b/perf_record_quality.py'
SPEC=importlib.util.spec_from_file_location('record_quality_test',PATH)
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def fixture(tmp_path,records):
    data=b''.join(struct.pack('<IHH',kind,0,8+len(body))+body for kind,body in records)
    header=b'PERFILE2'+struct.pack('<8Q',72,144,72,0,72,len(data),72,0)
    path=tmp_path/'perf.data';path.write_bytes(header+data);return path


def test_loss_throttle_and_unknown_data_are_not_hidden(tmp_path):
    path=fixture(tmp_path,[(9,b'abcdefgh'),(2,b'12345678'),(5,b''),(6,b''),(13,b''),(82,b'')])
    assert m.counts(path)==dict(SAMPLE=1,LOST=1,THROTTLE=1,UNTHROTTLE=1,LOST_SAMPLES=1,FINISHED_INIT=1)
    for kind in (66,71,81,12345):
        with pytest.raises(AssertionError):m.counts(fixture(tmp_path,[(kind,b'')]))


def test_reject_truncation_and_bad_size(tmp_path):
    path=fixture(tmp_path,[(9,b'abcdefgh')]);path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(AssertionError):m.counts(path)
    path=fixture(tmp_path,[(9,b'abcdefgh')]);data=bytearray(path.read_bytes());struct.pack_into('<H',data,78,0);path.write_bytes(data)
    with pytest.raises(AssertionError):m.counts(path)
