#!/usr/bin/env python3
"""Serialize prepared kernel and full-stack experiments, keeping evidence local."""
import argparse
from pathlib import Path
import time
import fullset as h


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preparation-pid',type=int,required=True)
    a=p.parse_args()
    while Path(f'/proc/{a.preparation_pid}').exists():time.sleep(10)
    assert (h.OUT/'candidates.json').exists()
    assert any('CANDIDATES_COMPLETE' in log.read_text() for log in h.OUT.glob('candidates*.log'))
    h.c.run(['python3',Path(__file__).with_name('kernel_emission_study.py'),'campaign'],
            h.OUT/'kernel_emission.log',timeout=14400)
    h.c.run(['python3',Path(__file__).with_name('fullset_study.py'),'streams'],
            h.OUT/'streams.log',timeout=28800)
    h.c.save(h.OUT/'all_measurements_complete.json',dict(complete=True))


if __name__=='__main__':main()
