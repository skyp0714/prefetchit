"""Runtime IP translation must respect ELF load VAs rather than file offsets."""
from pathlib import Path
import struct
import sys
from collections import Counter
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from lean_timeline import executable_maps,translate,attribute_ips,request_window


@pytest.mark.parametrize('va,start',[(0x1000,0x55555000),(0x401000,0x401000),(0x401000,0x7f001000)])
def test_mapping_for_pie_fixed_and_relocated_load_addresses(tmp_path,va,start):
    binary=tmp_path/'MovieIdService'
    data=bytearray(120);data[:6]=b'\x7fELF\x02\x01'
    struct.pack_into('<Q',data,32,64)
    struct.pack_into('<HH',data,54,56,1)
    struct.pack_into('<IIQQQQQQ',data,64,1,5,0x1000,va,va,0x1000,0x1000,0x1000)
    binary.write_bytes(data)
    text=f'{start:x}-{start+0x1000:x} r-xp 00001000 00:00 7 /custom/MovieIdService\n'
    text+=f'{start+0x2000:x}-{start+0x3000:x} r-xp 00000000 00:00 8 /lib/libother.so\n'
    maps=executable_maps(binary,text)
    assert translate(start+0x2b,maps)==va+0x2b
    assert translate(start+0x2000,maps) is None
    assert translate(start+0x1000,maps) is None
    with pytest.raises(AssertionError,match='No executable'):
        executable_maps(binary,text.replace('/custom/MovieIdService','/custom/another'))


def test_exact_ip_symbols_preserve_aliases_and_ambiguous_overlaps():
    ranges=[dict(start=100,end=120,names=['first','alias']),
            dict(start=110,end=125,names=['overlap']),
            dict(start=125,end=140,names=['next'])]
    result=attribute_ips(Counter({100:10,115:20,125:30,140:40}),ranges)
    assert result['top_unique_functions']==[
        dict(names=['next'],estimated_events=30),
        dict(names=['first','alias'],estimated_events=10)]
    assert result['ambiguous_events']==20 and result['unmapped_events']==40
    assert result['top_main_ips'][0]['function_ranges']==[]


def test_request_normalization_uses_completions_in_half_open_window():
    result=request_window([(0,1),(1,2),(2,3),(3,4)],2,4)
    assert result['completed_requests']==2 and result['seconds']==2
    with pytest.raises(AssertionError):request_window([(0,1)],2,3)
