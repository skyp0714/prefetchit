# A-3 prospective protocol (2026-09-23)

No workload setting changes. A-3 means runtime-readable future function targets;
A-2 means static graph targets. No new successful arbitrary-C++ claim is assumed.

FleetBench: unchanged Arena, workset 10, seed 0, CPU36, fixed2GHz/HWP20,
uncore fixed, turbo/C6 off. Private protobuf override, same compiler/build flags.
First screen 50 iterations, 1 randomized paired round, base plus five policies
and exact NOP twins. Selection considers baseline AND twin CPU/wall, not MPKI.
A positive candidate >=0.5% vs both merits fresh five-pair confirmation at 100
iterations. If none qualifies, report screening negatives and optionally measure
a fixed selected policy with static graph to test interactions; never call the
screen maximum a confirmed win. Seed1/NoArena holdout only for a confirmed win.

Compare independent builds base/F/G/FG for deployment gain. Within FG also
remove register hints, RIP hints, or both after verifying graph GOT count zero;
those four binaries isolate hint interaction at one layout. Pointer-load and
insertion overhead stay in the NOP controls. Gains are ratios of work-normalized
CPU time; interaction multiplier = speedup_FG/(speedup_F*speedup_G), interpreted
with paired uncertainty. Five-pair log-t95% intervals (df4) and all pairs retained.

FeedSim: existing valid full v2 40QPS operating point. Preserve all request,
feature, story, DLRM, TLS and compression work. No new burst waiting or artificial
queueing. Static graph plans are generated without performance profiles.
Compare base/F/G/FG; controls retain address/cursor work. Source prototypes are
not claimed as generic compiler transforms. Policy screens are not pooled with
confirmation. Record actual eligible/emitted sites, all negative arms, rate,
errors, p95 <=700ms and perf scheduling. Fixed-rate gain is CPU efficiency.

Serialize builds, tests, heavy analysis and measurements. Restore platform state
at every boundary. Keep compact audit/summary/evidence only in review archive;
source snapshots, binaries, full disassembly and plans remain ignored.
