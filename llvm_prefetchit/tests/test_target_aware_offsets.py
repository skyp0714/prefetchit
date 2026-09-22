import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "apply_target_aware_offsets.py"
SPEC = importlib.util.spec_from_file_location("apply_target_aware_offsets", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TargetAwareOffsetsTest(unittest.TestCase):
    def test_parse_offsets_deduplicates_in_order(self):
        self.assertEqual(MODULE.parse_offsets("0,64,0,128"), [0, 64, 128])

    def test_read_symbol_sizes_handles_versions(self):
        self.assertEqual(MODULE.parse_int("0x45"), 0x45)
        self.assertIsNone(MODULE.parse_int("not-an-offset"))


if __name__ == "__main__":
    unittest.main()
