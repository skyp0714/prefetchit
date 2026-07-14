import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "validate_prefetch_asm.py"
SPEC = importlib.util.spec_from_file_location("validate_prefetch_asm", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValidatePrefetchAsmTest(unittest.TestCase):
    def test_total_injected_count_sums_translation_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "build.log"
            log.write_text(
                "prefetchit-inject: injected=2 duplicate=0\n"
                "unrelated output\n"
                "prefetchit-inject: injected=3 duplicate=0\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.total_injected_count(log), 5)


if __name__ == "__main__":
    unittest.main()
