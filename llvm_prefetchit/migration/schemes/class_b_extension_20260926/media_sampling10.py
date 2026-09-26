"""Fresh Media training and evaluation with both Jaeger samplers at 10%."""
from common import *
from build import build
from pipeline import run_family

def main():
 assert os.geteuid()==0
 assert REPORT_SUFFIX=='_sampling10' and S.name=='sampling10' and T.name=='sampling10'
 assert os.environ.get('CLASS_B_MEDIA_SAMPLE_RATE')=='0.1'
 leads=json.loads(os.environ['CLASS_B_LEADS_BY_SERVICE']);assert leads=={'compose':[8],'rating':[16]}
 os.chdir(REPO);S.mkdir(parents=True,exist_ok=True);T.mkdir(parents=True,exist_ok=True);space()
 if not (S/'protocol.json').exists():
  save(S/'protocol.json',dict(started=datetime.datetime.now(datetime.timezone.utc).isoformat(),families=['media'],samplers=dict(native=.1,nginx=.1),reason='Separate normal-sampling validation; upstream Media uses 100% tracing',training='Fresh baseline qualification, Intel PT and plans at 10%; no reuse of 100% trace',qualification=dict(rates=[300,600,900],pool_util_min=15,shared_mpki_min=5,mpki_inflation_min=2),leads=leads,lead_selection='Each service uses the lead promoted by its completed 100% sampling screen: Compose8, Rating16; fixed before any 10% measurements',screen='3 fresh paired blocks: baseline, PF, exact-layout NOP',confirmation='7 independent blocks if screen CPU reduction >=1% against both controls; require mean >=1% and positive individual 95% CI against both controls',primary='Target user+kernel cgroup CPU per exact completed request; fixed arrival rate, not peak throughput'))
 for key in ['compose','rating']:
  if not (S/'media_build'/key/'base'/'binary.json').exists():build(key)
 qual=S/'media_qualification_v2'
 if not (qual/'selected.json').exists():platform('media_qualification_v2',['python3',B/'media.py','--out',qual,'--qualify'])
 save(S/'media_qualification_current.json',dict(path=str(qual)))
 run_family('media')
 run(['python3',B/'report.py'],S/'report.log')

if __name__=='__main__':main()
