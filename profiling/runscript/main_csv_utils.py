import csv
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

MAIN_FIELDS = [
    "Benchmark",
    "Mode",
    "CoreCount",
    "Instructions",
    "Event0",
    "Event1",
    "Event2",
    "Event3",
    "L1I_MPKI",
    "L2_MPKI",
    "iTLB_MPKI",
    "sTLB_MPKI",
    "DelayMS",
    "ElapsedSec",
    "ReturnCode",
    "SourceCSV",
]

ORDERED_KEYS = [
    ("tomcat", "jvm1c"),
    ("tomcat", "jvm86c"),
    ("finagle-http", "jvm1c"),
    ("finagle-http", "jvm86c"),
    ("finagle-chirper", "jvm1c"),
    ("finagle-chirper", "jvm86c"),
    ("verilator-qsort", "shared"),
    ("602.gcc_s", "shared"),
    ("605.mcf_s", "shared"),
    ("641.leela_s", "shared"),
]


def safe_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def safe_int(v: str, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def fmt_metric(v: float) -> str:
    return f"{v:.6f}"


def mpki_from_events(
    instructions: float,
    event0: float,
    event1: float,
    event2: float,
    event3: float,
) -> Tuple[float, float, float, float]:
    if instructions <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    l1i = (event0 * 1000.0) / instructions
    l2 = (event1 * 1000.0) / instructions
    stlb = (event2 * 1000.0) / instructions
    itlb = ((event2 + event3) * 1000.0) / instructions
    return l1i, l2, itlb, stlb


def row_key(row: Dict[str, str]) -> Tuple[str, str]:
    return (row.get("Benchmark", ""), row.get("Mode", ""))


def normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    out = {k: str(row.get(k, "")) for k in MAIN_FIELDS}
    return out


def load_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [normalize_row(r) for r in rows]


def write_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [normalize_row(r) for r in rows]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAIN_FIELDS)
        w.writeheader()
        w.writerows(sort_rows(materialized))


def upsert_rows(
    base_rows: Iterable[Dict[str, str]],
    updates: Iterable[Dict[str, str]],
) -> List[Dict[str, str]]:
    d: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in base_rows:
        d[row_key(row)] = normalize_row(row)
    for row in updates:
        d[row_key(row)] = normalize_row(row)
    return sort_rows(list(d.values()))


def sort_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rank = {k: i for i, k in enumerate(ORDERED_KEYS)}

    def _key(row: Dict[str, str]):
        key = row_key(row)
        return (rank.get(key, 10_000), key[0], key[1])

    return sorted(rows, key=_key)
