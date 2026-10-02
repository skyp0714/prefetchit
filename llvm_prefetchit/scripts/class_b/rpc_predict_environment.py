#!/usr/bin/env python3
"""Low-rate aggregate host observations; no unrelated process identities."""
import argparse
import json
from pathlib import Path
import time


def cpus():
    output={}
    for line in Path('/proc/stat').read_text().splitlines():
        fields=line.split()
        if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():
            values=list(map(int,fields[1:9]));output[int(fields[0][3:])]=(sum(values),values[3]+values[4])
    return output


def main(root):
    rows=[];before=cpus();started=time.time();previous=started
    initial=root/'screen/rows.json'
    protocol=dict(start_epoch=started,interval_s=30,screen_trials_already_complete=len(json.loads(initial.read_text())) if initial.exists() else 0,
        purpose='Aggregate observational context only; cannot describe conditions before observer start or justify timing exclusions.',
        privacy='CPU counters and MemAvailable only; no process names, command lines or PIDs.')
    (root/'aggregate_environment_protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    while not (root/'all_measurements_complete.json').exists():
        time.sleep(30);after=cpus();now=time.time();groups={}
        for label,indices in {'server':set(range(32,40)),'client':set(range(16,20)),
                'other_host':set(after)-set(range(32,40))-set(range(16,20))-{84,85}}.items():
            total=sum(after[i][0]-before[i][0] for i in indices)
            idle=sum(after[i][1]-before[i][1] for i in indices)
            groups[label]=100*(1-idle/total) if total else None
        mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')}
        rows.append(dict(start_epoch=previous,end_epoch=now,cpu_busy_pct=groups,**mem))
        (root/'aggregate_environment.json').write_text(json.dumps(rows,separators=(',',':'))+'\n')
        before=after;previous=now


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);main(parser.parse_args().root)
