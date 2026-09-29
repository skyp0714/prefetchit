import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import balanced_load as load


class Connection:
    def __init__(self,close_first=False):self.sock=object();self.close_first=close_first
    def request(self,*args,**kwargs):assert self.sock is not None
    def getresponse(self):
        time.sleep(.003)
        closed=self.close_first;self.close_first=False
        if closed:self.sock=None
        class Response:
            status=500 if closed else 200
            def read(self):return b'initial duplicate insert' if closed else b''
        return Response()
    def close(self):self.sock=None


class WarmupRecovery(unittest.TestCase):
    def setup_connections(self,master,port,out):
        (out/'connection_balance.json').write_text(json.dumps(dict(worker_pids=[11,22,33,44])))
        return [Connection(close_first=True) for _ in range(4)]

    def test_warmup_recovers_original_owner_and_retains_errors(self):
        def reconnect(master,port,owner,deadline):
            self.assertLess(time.time(),deadline)
            return Connection(),dict(owner=owner,completed_epoch=time.time(),attempts=[])
        with tempfile.TemporaryDirectory() as temp,patch.object(load,'connect_balanced',self.setup_connections),patch.object(load,'reconnect_worker',side_effect=reconnect) as repair:
            result=load.run(Path(temp),1.05,1,18081,9999,warmup=1.)
        self.assertEqual(result['errors'],4)
        self.assertEqual(result['steady_errors'],0)
        self.assertTrue(result['mapping_preserved'])
        self.assertEqual(sorted(r['owner'] for r in result['warmup_reconnects']),[11,22,33,44])
        self.assertEqual(repair.call_count,4)
        self.assertGreater(result['completed'],100)

    def test_no_reconnect_after_warmup(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(load,'connect_balanced',self.setup_connections),patch.object(load,'reconnect_worker') as repair:
            with self.assertRaises(RuntimeError):load.run(Path(temp),.2,1,18081,9999,warmup=0)
            result=json.loads((Path(temp)/'load.json').read_text())
        repair.assert_not_called()
        self.assertFalse(result['mapping_preserved'])
        self.assertGreater(result['steady_errors'],0)


if __name__=='__main__':unittest.main()
