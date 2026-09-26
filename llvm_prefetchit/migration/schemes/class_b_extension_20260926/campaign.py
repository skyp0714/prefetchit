"""Serial class-B extension, invoked while the parent controller owns its lock."""
from common import *
import sys
def main():
 assert os.geteuid()==0;os.chdir(REPO);S.mkdir(exist_ok=True);T.mkdir(exist_ok=True);space()
 save(S/'protocol.json',dict(started=datetime.datetime.now(datetime.timezone.utc).isoformat(),workloads=['Media ComposeReview','Media Rating','SocialNetwork ComposePost','SocialNetwork UserTimeline'],setting='normal upstream request fields, info logging, complete stack, 8-core shared pool; two dedicated cores per target in isolation diagnostic',qualification=dict(rates=[300,600,900],pool_util_min=15,shared_mpki_min=5,mpki_inflation_min=2,p99_max_ms=100,rate_tolerance_pct=4),measurement='clean cgroup CPU divided by exact completed external requests, separate later PMU; group services are not independent applications',comparison='three fresh cyclic-order exploratory blocks base/PF/exact-layout NOP; candidates >=1% vs both controls receive seven fresh confirmation blocks; keep exploration separate',plans='train only on baseline; first-touch per run and post-call targets; two lead windows d8/d16; no artificial flush, busy-spin neighbour, disabled tracing, or request simplification'))
 from build import build
 for key in ['compose','rating']:
  if not (S/'media_build'/key/'base'/'binary.json').exists():build(key)
 qual=S/'media_qualification_v2'
 if not (qual/'selected.json').exists():platform('media_qualification_v2',['python3',B/'media.py','--out',qual,'--qualify'])
 save(S/'media_qualification_current.json',dict(path=str(qual)))
 # The next stage is developed while qualification runs; never start an incomplete driver.
 while not (B/'PIPELINE_READY').exists():time.sleep(5)
 run(['python3',B/'pipeline.py'],S/'pipeline.log',timeout=86400)
if __name__=='__main__':main()
