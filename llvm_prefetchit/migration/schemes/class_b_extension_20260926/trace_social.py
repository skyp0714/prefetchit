from common import *
from social import Stack,TARGETS,BUILD
from trace_media import capture,decode
def main():
 out=S/'social_trace_stack';out.mkdir(exist_ok=False);selected=json.loads((S/'social_qualification/audited_selected.json').read_text());eligible={k:v for k,v in selected.items() if 'rate' in v}
 if not eligible:save(out/'skipped.json',selected);return
 stack=Stack(out);client=None
 def interrupt(signum,frame):raise KeyboardInterrupt(signum)
 signal.signal(signal.SIGTERM,interrupt)
 try:
  stack.start();stack.layout('shared')
  for rate in sorted({v['rate'] for v in eligible.values()}):
   d=out/str(rate);d.mkdir();cmd=['python3',str(B/'load.py'),'--out',str(d),'--rate',str(rate),'--seconds','125','--seed','37','--workload','social','--port','18082']
   with (d/'client.log').open('w') as log:client=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   time.sleep(55);assert client.poll() is None
   for key,v in eligible.items():
    if v['rate']==rate:capture(stack,key,T/key)
   rc=client.wait(timeout=180);client=None;info=json.loads((d/'load.json').read_text());assert rc==0 and not info.get('steady_errors',info['errors']) and not info.get('steady_drops',info['dropped']);stack.check()
 finally:stop(client);stack.close()
 for key in eligible:decode(T/key)
 save(out/'completed.json',dict(services=list(eligible),status='all captures, full load validation and offline decodes passed'))
if __name__=='__main__':main()
