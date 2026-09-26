"""Whole-thread admission must never retain a fragment of an errored thread."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'migration/schemes/class_b_extension_20260926'))
import trace_media


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'branches.txt').write_text(
            ' 17 1.000000: PERF_RECORD_SWITCH IN\n'
            ' 17 1.000001: tr strt 0 => 400000\n'
            ' 18 1.000002: tr strt 0 => 500000\n'
            ' 17 1.000003: call 400008 => 600000\n'
            ' 17 1.000004: PERF_RECORD_SWITCH OUT\n'
            ' 18 1.000005: PERF_RECORD_SWITCH OUT\n')
    def tearDown(self):self.temp.cleanup()
    def errors(self,text):(self.root/'decoder_errors.txt').write_text(text)
    def test_entire_thread_removed_before_and_after_error(self):
        self.errors('instruction trace error type 1 time 1.000002 cpu 32 pid 9 tid 17 ip 0x400000 code 7: Overflow packet\n')
        quality=trace_media.sanitize(self.root,[17])
        self.assertEqual(quality['excluded_tids'],[17])
        self.assertEqual((self.root/'branches.txt').read_text(),
                         ' 18 1.000002: tr strt 0 => 500000\n 18 1.000005: PERF_RECORD_SWITCH OUT\n')
        record=json.loads((self.root/'thread_filter.json').read_text())
        self.assertEqual(record['removed_lines'],{'17':4})
        self.assertNotEqual(record['original_sha256'],record['filtered_sha256'])
    def test_unknown_or_other_thread_errors_reject(self):
        for tid,code in [(18,7),(0,5),(17,5)]:
            self.errors(f'instruction trace error type 1 time 1.000002 cpu 32 pid 9 tid {tid} ip 0x400000 code {code}: error\n')
            with self.assertRaises(AssertionError):trace_media.sanitize(self.root,[17])
    def test_default_policy_still_rejects_any_error(self):
        self.errors('instruction trace error type 1 time 1.000002 cpu 32 pid 9 tid 17 ip 0x400000 code 7: Overflow packet\n')
        with self.assertRaises(AssertionError):trace_media.sanitize(self.root)


if __name__=='__main__':unittest.main()
