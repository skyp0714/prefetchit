"""Validate uncompressed little-endian perf.data record framing and loss counts.

Layout: Linux tools/perf/util/header.h (perf_file_header); record headers/types:
include/uapi/linux/perf_event.h. AUXTRACE and compressed blocks need separate
payload framing, so this bounded PEBS/scheduler reader rejects them.
"""
import collections
import mmap
from pathlib import Path
import struct

NAMES={1:'MMAP',2:'LOST',3:'COMM',4:'EXIT',5:'THROTTLE',6:'UNTHROTTLE',7:'FORK',8:'READ',9:'SAMPLE',
    10:'MMAP2',11:'AUX',12:'ITRACE_START',13:'LOST_SAMPLES',14:'SWITCH',15:'SWITCH_CPU_WIDE',
    16:'NAMESPACES',17:'KSYMBOL',18:'BPF_EVENT',19:'CGROUP',20:'TEXT_POKE',21:'AUX_OUTPUT_HW_ID',
    64:'HEADER_ATTR',65:'HEADER_EVENT_TYPE',66:'HEADER_TRACING_DATA',67:'HEADER_BUILD_ID',68:'FINISHED_ROUND',
    69:'ID_INDEX',70:'AUXTRACE_INFO',71:'AUXTRACE',72:'AUXTRACE_ERROR',73:'THREAD_MAP',74:'CPU_MAP',
    75:'STAT_CONFIG',76:'STAT',77:'STAT_ROUND',78:'EVENT_UPDATE',79:'TIME_CONV',80:'HEADER_FEATURE',81:'COMPRESSED',82:'FINISHED_INIT'}


def counts(path):
    with Path(path).open('rb') as stream:
        with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            assert len(data)>=72 and data[:8]==b'PERFILE2','Unsupported perf.data header'
            header=struct.unpack_from('<9Q',data)
            offset,size=header[5:7];end=offset+size
            assert 72<=header[1]<=offset<=end<=len(data),'Invalid perf data section'
            result=collections.Counter()
            while offset<end:
                assert offset+8<=end,'Truncated record header'
                kind,misc,length=struct.unpack_from('<IHH',data,offset)
                assert kind not in (66,71,81),'Unsupported external/compressed record payload'
                assert length>=8 and offset+length<=end,'Truncated/invalid perf record'
                assert kind in NAMES,('Unknown record type',kind)
                result[NAMES[kind]]+=1;offset+=length
            assert offset==end
            return dict(result)
