"""Exercise actual HTTP concurrency and rejection of ambiguous scheduler data."""
import importlib.util
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

scripts=Path(__file__).resolve().parents[1]/'scripts/class_b'


def module(name):
    spec=importlib.util.spec_from_file_location(name,scripts/(name+'.py'))
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    return loaded


def test_closed_loop_obeys_concurrency_and_retains_response_errors(tmp_path):
    load=module('closed_loop_load');lock=threading.Lock();state=dict(active=0,peak=0,status=200)
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            with lock:
                state['active']+=1;state['peak']=max(state['peak'],state['active'])
            time.sleep(.01)
            self.send_response(state['status']);self.send_header('Content-Length','0');self.end_headers()
            with lock:state['active']-=1
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        result=load.run_load(tmp_path/'good',2,.25,1,server.server_port,['title'],0)
        assert result['completed']>=4 and result['errors']==0 and state['peak']==2
        state.update(status=500,peak=0)
        result=load.run_load(tmp_path/'bad',1,.1,1,server.server_port,['title'],0)
        assert result['completed']==0 and result['steady_errors']>0 and result['error_examples']
        assert state['peak']==1
    finally:
        server.shutdown();server.server_close();thread.join()


def test_payload_is_dispatch_index_deterministic():
    load=module('closed_loop_load')
    assert load.payload(1,5,['title'])==load.payload(1,5,['title'])
    assert load.payload(1,5,['title'])!=load.payload(1,6,['title'])


def test_scheduler_version_fields_and_missing_cpu_are_checked():
    study=module('concurrency_study')
    text='version 15\ntimestamp 20\ncpu32 0 0 0 0 0 0 100 30 5\ncpu33 0 0 0 0 0 0 200 40 7\n'
    assert study.schedstat(text,{32})=={32:dict(run_ns=100,wait_ns=30,timeslices=5)}
    with pytest.raises(ValueError):study.schedstat(text.replace('version 15','version 17'),{32})
    with pytest.raises(ValueError):study.schedstat(text,{34})
