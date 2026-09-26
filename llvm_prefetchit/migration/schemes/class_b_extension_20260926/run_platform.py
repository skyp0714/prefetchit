#!/usr/bin/env python3
"""Run one command with fixed 2 GHz cores; restore nested platform contexts."""
import argparse,contextlib,json,os,signal,subprocess
from pathlib import Path
from platform_context import platform

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--cpus',required=True);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
 cores=[]
 for part in a.cpus.split(','):
  lo,_,hi=part.partition('-');cores.extend(range(int(lo),int(hi or lo)+1))
 if os.geteuid()!=0 or not cores or not a.command:p.error('root, CPUs and command required')
 controller_cores=sorted(os.sched_getaffinity(0)-set(cores))[-2:]
 if controller_cores:os.sched_setaffinity(0,set(controller_cores))
 a.out.mkdir(parents=True,exist_ok=False)
 (a.out/'command.json').write_text(json.dumps({'cpus':cores,'controller_cpus':controller_cores,'command':a.command},indent=2))
 def interrupt(signum,frame):raise KeyboardInterrupt(f'signal {signum}')
 signal.signal(signal.SIGTERM,interrupt)
 with contextlib.ExitStack() as stack:
  for cpu in cores:
   d=a.out/f'cpu{cpu}';d.mkdir();stack.enter_context(platform(cpu,d))
  child=subprocess.Popen(a.command,start_new_session=True)
  try: rc=child.wait()
  finally:
   if child.poll() is None:
    os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
  if rc:raise SystemExit(rc)
if __name__=='__main__':main()
