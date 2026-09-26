from common import *
from build import build,build_support
from pipeline import run_family
import argparse
def main():
 p=argparse.ArgumentParser();p.add_argument('--qualify-only',action='store_true');a=p.parse_args()
 os.chdir(REPO)
 if not (S/'social_build/support/binaries.json').exists():build_support('social')
 for key in ['composepost','usertimeline']:
  if not (S/'social_build'/key/'base/binary.json').exists():build(key)
 removed=[]
 for name in ['ComposePostService','UserTimelineService']:
  path=S/'social_build/support'/name
  if path.exists():removed.append(dict(path=str(path),bytes=path.stat().st_size,sha256=sha(path),reason='Unused dynamic duplicate: stack always uses separately built fat-static target baseline or treatment'));path.unlink()
 if removed:save(S/'social_build/support/unused_target_cleanup.json',dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed)))
 qual=S/'social_qualification'
 if not (qual/'selected.json').exists():platform('social_qualification',['python3',B/'social.py','--out',qual,'--qualify'])
 if not a.qualify_only:run_family('social')
if __name__=='__main__':main()
