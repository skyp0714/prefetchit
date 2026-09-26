"""Validate the cgroup CSV field layout against raw files, before policy selection."""
from common import *
import argparse
def compact(root):
 assert (root/'audited_summary.json').exists() and (root/'audited_selected.json').exists()
 receipt=root/'qualification_timestamp_cleanup.json'
 removed=json.loads(receipt.read_text())['removed'] if receipt.exists() else []
 for path in sorted(root.glob('*/requests.json.gz')):
  assert not path.is_symlink()
  removed.append(dict(path=str(path),bytes=path.stat().st_size,sha256=sha(path)));path.unlink()
 save(receipt,dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed),reason='Exact ROI counts, rates, latencies, load validation and audited raw PMU counters retained; completed qualification timestamps no longer used'))
def audit(family):
 root=S/('media_qualification_v2' if family=='media' else 'social_qualification');rows=json.loads((root/'summary.json').read_text());changes=[]
 for row in rows:
  for key,v in row['services'].items():
   fresh=counters(root/f"{row['layout']}_{row['rate']}"/(key+'.perf.csv'))
   assert fresh['counters']==v['post_pmu']['counters']
   if fresh['fully_scheduled']!=v['post_pmu']['fully_scheduled']:
    changes.append(dict(rate=row['rate'],layout=row['layout'],key=key,old=v['post_pmu']['fully_scheduled'],new=fresh['fully_scheduled']))
   v['post_pmu']['fully_scheduled']=fresh['fully_scheduled'];v['valid'] &= fresh['fully_scheduled']
 selected={}
 for key in rows[0]['services']:
  good=[]
  for rate in sorted({r['rate'] for r in rows}):
   pair={r['layout']:r for r in rows if r['rate']==rate};shared=pair['shared']['services'][key];alone=pair['alone']['services'][key];mpki=shared['post_pmu']['mpki'];ratio=mpki/alone['post_pmu']['mpki']
   if shared['valid'] and alone['valid'] and pair['shared']['pool_util_pct']>=15 and mpki>=5 and ratio>=2:good.append(dict(rate=rate,mpki=mpki,alone_mpki=alone['post_pmu']['mpki'],inflation=ratio))
  selected[key]=max(good,key=lambda x:x['mpki']) if good else dict(status='No valid >=15% pool utilization, >=5 shared MPKI and >=2x MPKI inflation point')
 save(root/'counter_format_audit.json',dict(changes=changes,rule='PID perf CSV uses percentage field4; cgroup CSV inserts group field and uses field5 (zero based)',all_raw_counters_unchanged=True))
 save(root/'audited_summary.json',rows);save(root/'audited_selected.json',selected)
 compact(root)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('family',choices=['media','social']);a=p.parse_args();audit(a.family)
