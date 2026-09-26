"""Use private configuration copies; keep tracing enabled with explicit sampling."""
from common import *
import yaml

def prepare(out,source,sample_rate):
 config_dir=source/'config';nginx_path=source/'nginx-web-server/jaeger-config.json'
 native=yaml.safe_load((config_dir/'jaeger-config.yml').read_text());nginx=json.loads(nginx_path.read_text());before=dict(native=native.get('sampler'),nginx=nginx.get('sampler'))
 if sample_rate is not None:
  assert 0<float(sample_rate)<=1
  private=out/'runtime_config';shutil.copytree(config_dir,private);config_dir=private
  native['sampler']=dict(type='probabilistic',param=float(sample_rate));nginx['sampler']=dict(type='probabilistic',param=float(sample_rate))
  (config_dir/'jaeger-config.yml').write_text(yaml.safe_dump(native,sort_keys=False));nginx_path=out/'nginx_jaeger.json';save(nginx_path,nginx)
 save(out/'tracing_configuration.json',dict(original=before,effective=dict(native=native.get('sampler'),nginx=nginx.get('sampler')),native_config_sha256=sha(config_dir/'jaeger-config.yml'),nginx_config_sha256=sha(nginx_path),source_config_modified=False,tracing_enabled=True))
 return config_dir,nginx_path
