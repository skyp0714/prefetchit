#!/usr/bin/env python3
"""Read existing Jaeger spans only after diagnostic load/counters have stopped."""
import collections
import hashlib
import json
from pathlib import Path
import statistics
import time
import urllib.parse
import urllib.request
import dense_build as b

LIMIT=('Bounded late-window Jaeger sample from existing 100% tracing, fetched after load and PMU end. '
       'The query can return a recent subset and applies Jaeger UI clock adjustment. '
       'Span durations include waiting and child work; they are not CPU cost, independent E2E latency observations, '
       'or an exclusive critical-path decomposition. Span tags, logs and process environment are not collected.')


def collect(stack,out,load):
    protocol=dict(source_sha256=b.sha(__file__),query_limit=200,window_seconds=5,
        fetch_started_epoch=time.time(),load_end_epoch=load['epoch']+load['seconds'],
        source='https://raw.githubusercontent.com/jaegertracing/jaeger/v1.57.0/cmd/query/app/http_handler.go',limitation=LIMIT)
    try:
        assert protocol['fetch_started_epoch']>=protocol['load_end_epoch']
        info=stack.states['jaeger']
        ips=[v['IPAddress'] for v in info['NetworkSettings']['Networks'].values() if v.get('IPAddress')]
        assert len(ips)==1
        query=dict(service='nginx',start=int((protocol['load_end_epoch']-5)*1e6),
                   end=int(protocol['load_end_epoch']*1e6),limit=200)
        url='http://'+ips[0]+':16686/api/traces?'+urllib.parse.urlencode(query)
        protocol['query']=query;protocol['url']=url
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url,timeout=10) as response:
            raw=response.read(16*2**20+1)
            assert len(raw)<=16*2**20,'Trace response exceeds compact capture budget'
        result=json.loads(raw);protocol.update(response_bytes=len(raw),response_sha256=hashlib.sha256(raw).hexdigest(),
            api_errors=result.get('errors'),fetch_completed_epoch=time.time())
        traces=[];operations=collections.defaultdict(list);quality=collections.Counter()
        for trace in result.get('data') or []:
            processes={key:value['serviceName'] for key,value in trace.get('processes',{}).items()}
            spans=[dict({key:span[key] for key in ['traceID','spanID','operationName','startTime','duration','processID']},
                        references=span.get('references') or []) for span in trace['spans']]
            span_ids={span['spanID'] for span in spans}
            roots=[];missing=0
            for span in spans:
                parents=[ref for ref in span['references'] if ref['refType']=='CHILD_OF']
                missing+=sum(ref['traceID']!=trace['traceID'] or ref['spanID'] not in span_ids for ref in parents)
                if not parents:roots.append(span['spanID'])
                service=processes.get(span['processID'],'unknown')
                operations[(service,span['operationName'])].append(span['duration'])
            warnings=sum(bool(span.get('warnings')) for span in trace['spans'])
            quality['traces']+=1;quality['spans']+=len(spans)
            quality['traces_with_missing_parent']+=bool(missing)
            quality['traces_without_root']+=not roots
            quality['traces_with_multiple_roots']+=len(roots)>1
            quality['spans_with_api_warnings']+=warnings
            traces.append(dict(traceID=trace['traceID'],processes=processes,spans=spans,
                roots=roots,missing_parent_references=missing,span_warning_count=warnings))
        assert traces,'No nginx request traces in the specified diagnostic window'
        grouped=[]
        for (service,operation),values in sorted(operations.items()):
            grouped.append(dict(service=service,operation=operation,spans=len(values),
                mean_us=statistics.mean(values),median_us=statistics.median(values),
                min_us=min(values),max_us=max(values)))
        b.save(out/'request_path_traces.json',dict(protocol=protocol,quality=dict(quality),traces=traces))
        b.save(out/'request_path_summary.json',dict(valid=not result.get('errors'),protocol=protocol,
            quality=dict(quality),operations=grouped,limitation=LIMIT))
    except Exception as error:
        # A trace-query failure cannot invalidate or be silently retried as a
        # performance trial. Preserve it separately from completed PMU windows.
        b.save(out/'request_path_summary.json',dict(valid=False,protocol=protocol,error=repr(error),limitation=LIMIT))


def aggregate(root):
    records=[]
    for row in json.loads((root/'rows.json').read_text()):
        path=Path(row['output'])/'request_path_summary.json'
        records.append(dict(block=row['block'],arm=row['arm'],**json.loads(path.read_text())))
    b.save(root/'request_paths.json',dict(records=records,limitation=LIMIT))
