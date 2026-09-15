#!/usr/bin/env python3
"""Load driver for WideApi: uniform shuffled walk over all N endpoints
(the wide-API traffic shape). Multiprocess, latency percentiles.

Usage: load_wideapi.py [--procs 4] [--threads 8] [--duration 60] [--n 4000]
"""
import argparse, urllib.request, threading, time, random
import multiprocessing as mp

BASE = 'http://localhost:8123/api'


def worker(wid, n, stop_t, lat, cnt, err):
    rng = random.Random(wid * 104729 + 7)
    order = list(range(n))
    rng.shuffle(order)
    pos = 0
    while time.time() < stop_t:
        ep = order[pos]
        pos = (pos + 1) % n
        t0 = time.time()
        try:
            urllib.request.urlopen(f'{BASE}/{ep}/{pos}', timeout=5).read()
            lat.append(time.time() - t0)
            cnt[0] += 1
        except Exception:
            err[0] += 1


def proc_main(pid, a, q, barrier):
    lat, cnt, err = [], [0], [0]
    barrier.wait()
    stop_t = time.time() + a.duration
    ts = [threading.Thread(target=worker,
                           args=(pid * 100 + i, a.n, stop_t, lat, cnt, err))
          for i in range(a.threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    q.put((cnt[0], err[0], lat))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--duration', type=float, default=60)
    ap.add_argument('--n', type=int, default=4000)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    q = mp.Queue()
    barrier = mp.Barrier(a.procs)
    ps = [mp.Process(target=proc_main, args=(i, a, q, barrier))
          for i in range(a.procs)]
    [p.start() for p in ps]
    tot = terr = 0
    lats = []
    for _ in ps:
        c, e, l = q.get()
        tot += c; terr += e; lats.extend(l)
    [p.join() for p in ps]
    lats.sort()
    def pct(p):
        return lats[min(len(lats)-1, int(len(lats)*p))]*1000 if lats else -1
    print(f'{a.tag} reqs {tot} err {terr} qps {tot/a.duration:.1f} '
          f'p50 {pct(.5):.2f}ms p99 {pct(.99):.2f}ms')


if __name__ == '__main__':
    main()
