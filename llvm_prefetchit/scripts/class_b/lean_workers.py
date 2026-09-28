#!/usr/bin/env python3
"""Post-ROI process CPU distribution, for interpreting fresh-stack variation."""
import os
from pathlib import Path
import time


def processes(cgroup):
    root=Path(cgroup)
    before=time.monotonic();rows=[];unavailable=[]
    for pid in sorted(set(map(int,(root/'cgroup.procs').read_text().split()))):
        try:
            text=Path(f'/proc/{pid}/stat').read_text()
            fields=text[text.rindex(')')+2:].split()
            # fields starts at proc stat field 3 (state), after arbitrary comm.
            rows.append(dict(pid=pid,comm=text[text.index('(')+1:text.rindex(')')],
                user_ticks=int(fields[11]),system_ticks=int(fields[12]),
                start_ticks=int(fields[19]),last_cpu=int(fields[36]),
                command=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()))
        except (FileNotFoundError,ProcessLookupError,PermissionError) as error:
            unavailable.append(dict(pid=pid,reason=type(error).__name__))
    return dict(cgroup=str(root),processes=rows,unavailable=unavailable,
        clock_ticks=os.sysconf('SC_CLK_TCK'),monotonic_before=before,monotonic_after=time.monotonic(),
        interpretation='Process lifetime CPU at a post-ROI snapshot, including startup/warmup. Not clean-ROI per-worker CPU or a causal explanation of variance.')
