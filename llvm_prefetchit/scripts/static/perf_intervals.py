"""Strict interval aggregation, allowing only a wholly empty process-exit footer."""
import csv

def read_intervals(path):
    rows=[x for x in csv.reader(path.open()) if x and not x[0].startswith('#')]
    assert rows and all(len(x)>5 for x in rows)
    stamps=[float(x[0]) for x in rows];assert stamps==sorted(stamps)
    last=stamps[-1];footer=[x for x in rows if float(x[0])==last]
    empty=[x for x in rows if x[1]=='<not counted>']
    ignored=[]
    if empty:
        assert empty==footer,'Uncounted interval is partial or not the final footer'
        assert all(float(x[4])==0 and float(x[5])==100 for x in footer),'Uncounted event had nonzero running time'
        previous=[x for x in rows if float(x[0])!=last]
        assert previous and {x[3] for x in previous}=={x[3] for x in footer}
        assert len({x[3] for x in footer})==len(footer)
        ignored=[{'timestamp':last,'events':len(footer),'reason':'All events have zero running time in final process-exit footer'}]
        rows=previous
    counts={}
    for x in rows:
        value=float(x[1]);assert value>=0 and float(x[5])>=99.99,x
        counts[x[3]]=counts.get(x[3],0)+value
    return counts,{'perf_elapsed_s':last,'empty_exit_footer':ignored,'numeric_records':len(rows)}
