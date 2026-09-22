import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "prune_plan_by_residual_targets.py"


class ResidualPlanPruningTest(unittest.TestCase):
    def test_selects_reduced_target_and_updates_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "input.json"
            baseline = root / "baseline.csv"
            residual = root / "residual.csv"
            output = root / "output.json"
            plan.write_text(
                json.dumps(
                    {
                        "injections": [
                            {"target": {"demangled": "keep"}, "site": {}},
                            {"target": {"demangled": "drop"}, "site": {}},
                        ],
                        "prefetch": {"byte_offsets": [0]},
                        "options": {},
                        "stats": {},
                    }
                )
            )
            for path, counts in ((baseline, (100, 100)), (residual, (40, 120))):
                with path.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["target", "samples"])
                    writer.writeheader()
                    writer.writerow({"target": "keep:/tmp/a.cc:1", "samples": counts[0]})
                    writer.writerow({"target": "drop:/tmp/b.cc:2", "samples": counts[1]})

            subprocess.run(
                [
                    "python3",
                    str(TOOL),
                    "--input-plan",
                    str(plan),
                    "--baseline-targets",
                    str(baseline),
                    "--residual-targets",
                    str(residual),
                    "--output",
                    str(output),
                    "--label",
                    "test",
                    "--min-reduction-pct",
                    "20",
                    "--byte-offsets",
                    "0,64",
                ],
                check=True,
            )
            result = json.loads(output.read_text())
            self.assertEqual(["keep"], [row["target"]["demangled"] for row in result["injections"]])
            self.assertEqual([0, 64], result["prefetch"]["byte_offsets"])
            self.assertEqual(2, result["stats"]["planned_prefetches"])

    def test_aggregates_repeated_profile_csvs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "input.json"
            output = root / "output.json"
            plan.write_text(
                json.dumps(
                    {
                        "injections": [
                            {"target": {"demangled": "keep"}, "site": {}}
                        ],
                        "prefetch": {"byte_offsets": [0]},
                        "options": {},
                        "stats": {},
                    }
                )
            )

            profile_args = []
            for kind, counts in (("baseline", (30, 20)), ("residual", (20, 10))):
                for index, count in enumerate(counts):
                    path = root / f"{kind}{index}.csv"
                    count_field = "samples" if index == 0 else "count"
                    with path.open("w", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=["target", count_field])
                        writer.writeheader()
                        writer.writerow({"target": "keep:/tmp/a.cc:1", count_field: count})
                    profile_args.extend([f"--{kind}-targets", str(path)])

            subprocess.run(
                [
                    "python3",
                    str(TOOL),
                    "--input-plan",
                    str(plan),
                    *profile_args,
                    "--output",
                    str(output),
                    "--label",
                    "repeated",
                    "--min-absolute-reduction",
                    "20",
                ],
                check=True,
            )
            result = json.loads(output.read_text())
            self.assertEqual(1, result["stats"]["selected_injections"])
            self.assertEqual(
                20,
                result["injections"][0]["residual_target_delta"]["reduction_samples"],
            )


if __name__ == "__main__":
    unittest.main()
