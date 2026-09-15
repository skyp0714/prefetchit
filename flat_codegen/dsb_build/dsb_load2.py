#!/usr/bin/env python3
"""DSB socialNetwork load driver: multiprocess, mixed workload, latency stats.

Usage: dsb_load2.py [--procs 4] [--threads 16] [--duration 75] [--tag x]
Mix: 10% compose, 60% home-timeline read, 30% user-timeline read (wrk2-like).
Prints total QPS and latency percentiles (ms) across all processes.
"""
import argparse, urllib.request, urllib.parse, threading, time, random
import multiprocessing as mp

BASE = 'http://localhost:8080/wrk2-api'


def worker(wid, stop_t, lat, cnt, err):
    rng = random.Random(wid * 7919 + 13)
    while time.time() < stop_t:
        uid = rng.randint(1, 900)
        r = rng.random()
        t0 = time.time()
        try:
            if r < 0.1:
                d = urllib.parse.urlencode({
                    'username': f'username_{uid}', 'user_id': uid,
                    'text': f'hello world {rng.random()} @username_{rng.randint(1,900)}',
                    'media_ids': '[]', 'media_types': '[]',
                    'post_type': '0'}).encode()
                urllib.request.urlopen(f'{BASE}/post/compose', data=d,
                                       timeout=5).read()
            elif r < 0.7:
                urllib.request.urlopen(
                    f'{BASE}/home-timeline/read?user_id={uid}&start=0&stop=10',
                    timeout=5).read()
            else:
                urllib.request.urlopen(
                    f'{BASE}/user-timeline/read?user_id={uid}&start=0&stop=10',
                    timeout=5).read()
            lat.append(time.time() - t0)
            cnt[0] += 1
        except Exception:
            err[0] += 1


def proc_main(pid, dur, nthreads, q, barrier):
    lat, cnt, err = [], [0], [0]
    barrier.wait()
    stop_t = time.time() + dur
    ts = [threading.Thread(target=worker,
                           args=(pid * 100 + i, stop_t, lat, cnt, err))
          for i in range(nthreads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    q.put((cnt[0], err[0], lat))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--threads', type=int, default=16)
    ap.add_argument('--duration', type=float, default=75)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    q = mp.Queue()
    barrier = mp.Barrier(a.procs)
    ps = [mp.Process(target=proc_main,
                     args=(i, a.duration, a.threads, q, barrier))
          for i in range(a.procs)]
    [p.start() for p in ps]
    tot = terr = 0
    lats = []
    for _ in ps:
        c, e, l = q.get()
        tot += c
        terr += e
        lats.extend(l)
    [p.join() for p in ps]
    lats.sort()
    def pct(p):
        return lats[min(len(lats) - 1, int(len(lats) * p))] * 1000 if lats else -1
    print(f'{a.tag} reqs {tot} err {terr} qps {tot/a.duration:.1f} '
          f'p50 {pct(.50):.1f}ms p95 {pct(.95):.1f}ms p99 {pct(.99):.1f}ms')


if __name__ == '__main__':
    main()
