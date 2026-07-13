#!/usr/bin/env python3

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "tools" / "prefetchit_external_got_plan.py"


@unittest.skipUnless(shutil.which("cc") and shutil.which("addr2line"), "toolchain required")
class ExternalGotPlanTest(unittest.TestCase):
    def test_lbr0_to_is_external_target_and_from_is_site(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            source = tmp / "fixture.c"
            binary = tmp / "fixture"
            trace = tmp / "trace"
            out = tmp / "plan.json"
            source.write_text("int main(void) { return 0; }\n", encoding="ascii")
            subprocess.run(
                ["cc", "-O0", "-g", "-fno-omit-frame-pointer", str(source), "-o", str(binary)],
                check=True,
            )
            nm = subprocess.run(
                ["nm", "-n", str(binary)],
                check=True,
                text=True,
                capture_output=True,
            ).stdout
            main_addr = int(
                next(line.split()[0] for line in nm.splitlines() if line.endswith(" T main")),
                16,
            )

            trace.mkdir()
            symbolic = (
                f"{main_addr:x} main+0x0 "
                "main+0x0/malloc+0x46/P/-/-/1/CALL/-\n"
                f"{main_addr:x} main+0x0 "
                "main+0x0/cfree@GLIBC_2.2.5+0x0/P/-/-/1/CALL/-\n"
            )
            raw = (
                f"{main_addr:x} main+0x0 "
                f"0x{main_addr:x}/0x7f0000000046/P/-/-/1/CALL/-\n"
                f"{main_addr:x} main+0x0 "
                f"0x{main_addr:x}/0x7f0000001000/P/-/-/1/CALL/-\n"
            )
            (trace / "lbr_symbolic_dump.txt").write_text(symbolic, encoding="ascii")
            (trace / "lbr_raw_dump.txt").write_text(raw, encoding="ascii")

            subprocess.run(
                [
                    "python3",
                    str(PLANNER),
                    "--trace-dir",
                    str(trace),
                    "--binary",
                    str(binary),
                    "--output",
                    str(out),
                    "--summary-dir",
                    str(tmp / "summary"),
                    "--depth-min",
                    "1",
                    "--depth",
                    "1",
                    "--site-budget-per-target",
                    "1",
                    "--prefetch-mnemonic",
                    "prefetcht1",
                    "--addr2line",
                    "addr2line",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            plan = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(plan["stats"]["external_lbr0_samples"], 2)
            self.assertEqual(plan["stats"]["parsed_external_samples"], 2)
            self.assertEqual(len(plan["injections"]), 2)
            by_target = {row["target"]["mangled"]: row for row in plan["injections"]}
            injection = by_target["malloc"]
            self.assertEqual(injection["target"]["mangled"], "malloc")
            self.assertEqual(injection["target"]["symbol_offset"], "0x40")
            self.assertEqual(injection["target"]["operand"], "got-symbol-offset")
            self.assertEqual(injection["site"]["mangled"], "main")
            self.assertEqual(by_target["free"]["target"]["symbol_offset"], "0x0")


if __name__ == "__main__":
    unittest.main()
