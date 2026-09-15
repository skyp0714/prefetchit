#!/usr/bin/env python3
"""Paper-status summary graphs, 2026-08-21 (frozen-platform, prefetch-only
numbers; PGO/layout effects excluded per project direction)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({'font.size': 11, 'figure.dpi': 140})

# ---------------- Fig 1: headline prefetch-only speedups ----------------
workloads = [
    ('Verilator\n(EDA sim)', 7.8, 'C1 flattened-code', '#2b8cbe'),
    ('arcilator\n(EDA sim)', 5.1, 'C1 flattened-code', '#2b8cbe'),
    ('Django\n(DCPerf web)', 49.0, 'C2 dispatch', '#31a354'),
    ('FeedSim\n(DCPerf)', 7.3, 'C2 dispatch', '#31a354'),
    ('DSB socialNet\n(microsvc)', 0.0, 'C2 dispatch', '#31a354'),
    ('PostgreSQL\nTPC-C', 0.3, 'OLTP', '#e6550d'),
    ('tomcat\n(JVM)', 0.0, 'JVM real', '#756bb1'),
    ('cassandra\n(JVM)', 0.0, 'JVM real', '#756bb1'),
]
fig, ax = plt.subplots(figsize=(10, 4.6))
xs = np.arange(len(workloads))
vals = [w[1] for w in workloads]
cols = [w[3] for w in workloads]
bars = ax.bar(xs, vals, color=cols, edgecolor='black', linewidth=0.6)
for x, v in zip(xs, vals):
    ax.text(x, v + 0.8, f'+{v:.1f}%' if v > 0 else 'neutral',
            ha='center', fontsize=10,
            fontweight='bold' if v >= 5 else 'normal')
ax.set_xticks(xs)
ax.set_xticklabels([w[0] for w in workloads], fontsize=9)
ax.set_ylabel('Prefetch-only speedup (%)')
ax.set_title('Software instruction prefetch (prefetcht1): headline results\n'
             'Xeon 6787P, frozen clocks (core+uncore pinned), NOP-pair controlled')
ax.axhline(5, color='gray', ls='--', lw=0.8)
ax.text(len(workloads)-0.4, 5.4, '5% target', color='gray', fontsize=9, ha='right')
ax.set_ylim(-2, 55)
from matplotlib.patches import Patch
ax.legend(handles=[
    Patch(color='#2b8cbe', label='C1: flattened streaming code'),
    Patch(color='#31a354', label='C2: indirect-dispatch services'),
    Patch(color='#e6550d', label='OLTP databases'),
    Patch(color='#756bb1', label='JVM (real apps)'),
], loc='upper right', fontsize=9)
plt.tight_layout()
plt.savefig('fig1_headline_speedups.png')
plt.close()

# ------------- Fig 2: MPKI vs gain, annotated blocking condition -------------
pts = [
    # name, L2I MPKI, gain%, blocker ('' = win)
    ('Verilator', 58.6, 7.8, ''),
    ('arcilator', 79.0, 5.1, '(needs surgical plan:\nMSHR saturation)'),
    ('Django', 84.6, 49.0, ''),
    ('FeedSim', 7.2, 7.3, ''),
    ('DSB PostStorage', 19.4, 0.0, 'lead time + diffuse\n(3.6k sites)'),
    ('PostgreSQL TPC-C', 37.0, 0.3, 'L2 data eviction'),
    ('MariaDB TPC-C', 65.8, 0.0, 'L2 data eviction'),
    ('tomcat', 12.0, 0.0, 'L2-resident\n(L1I-bound)'),
    ('cassandra', 13.4, 0.0, 'L2-resident'),
    ('clang', 0.4, 0.0, 'no misses'),
    ('memcached', 0.04, 0.0, 'no misses'),
]
fig, ax = plt.subplots(figsize=(9.5, 5.4))
for name, mpki, gain, blocker in pts:
    win = gain >= 5
    ax.scatter(mpki, gain, s=130 if win else 80,
               color='#31a354' if win else ('#e6550d' if gain > 0 else '#c94040'),
               zorder=3, edgecolor='black', linewidth=0.6)
    dy = 1.6 if name != 'FeedSim' else -3.2
    label = name if not blocker else f'{name}\n{blocker}'
    ax.annotate(label, (mpki, gain), textcoords='offset points',
                xytext=(7, dy), fontsize=8.5)
ax.set_xscale('symlog', linthresh=1)
ax.set_xlabel('L2 instruction MPKI (under load)')
ax.set_ylabel('Prefetch-only speedup (%)')
ax.set_title('High MPKI is necessary but NOT sufficient\n'
             '(each failure is blocked by a different structural condition)')
ax.axhline(0, color='gray', lw=0.7)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig('fig2_mpki_vs_gain.png')
plt.close()

# ------------- Fig 3: DSB wave-8 in-lib typed plans, warm vs cold -------------
labels = ['CALL/IND\n(48 targets)', 'COND\n(27 targets)', 'deep lookahead\n+4-line burst (89t)']
warm_mpki = [-4.9, +2.6, -1.3]
cold_mpki = [-0.2, -1.3, -0.3]
warm_ipc = [+1.02, -0.65, -0.13]
cold_ipc = [+0.05, +0.40, -0.11]
x = np.arange(len(labels)); w = 0.2
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.bar(x - 1.5*w, warm_mpki, w, label='warm: ΔMPKI %', color='#fdae6b', edgecolor='black', lw=0.5)
ax.bar(x - 0.5*w, cold_mpki, w, label='cold: ΔMPKI %', color='#e6550d', edgecolor='black', lw=0.5)
ax.bar(x + 0.5*w, warm_ipc, w, label='warm: ΔIPC %', color='#a1d99b', edgecolor='black', lw=0.5)
ax.bar(x + 1.5*w, cold_ipc, w, label='cold: ΔIPC %', color='#31a354', edgecolor='black', lw=0.5)
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=9)
ax.axhline(0, color='black', lw=0.8)
ax.set_ylabel('Δ vs layout-identical NOP control (%)')
ax.set_title('DSB PostStorage: first VALID in-library injection (dynamic linking, GOT)\n'
             'typed + lookahead plans still neutral in cold regime (19 MPKI)')
ax.legend(fontsize=9, ncol=2)
ax.grid(axis='y', alpha=0.25)
plt.tight_layout()
plt.savefig('fig3_dsb_typed_plans.png')
plt.close()
print('saved 3 figures')
