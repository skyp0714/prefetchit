# Mechanism references (not predicted native-software gains)

- [Hierarchical Prefetching, ASPLOS 2025](https://ease-lab.github.io/ease_website/pubs/HP_ASPLOS25.pdf): statically formed functional bundles plus hardware footprint recording/replay target stable coarse code regions. This motivates checking whether warming only a scheduler callback entry misses its actual cold callees. Its hardware machinery and speedups are not available in our T1 prototype.
- [Software Prefetching for Indirect Memory Accesses, CGO 2017](https://www.research.ed.ac.uk/en/publications/software-prefetching-for-indirect-memory-accesses/): compiler-generated prefetches for indirect accesses motivate separating pointer-address preparation from target-code preparation. Our immutable function arrays are a restricted case, not a general safe pointer-hoisting pass.
- [Call-chain Software Instruction Prefetching in J2EE Server Applications](https://sites.cs.ucsb.edu/~ckrintz/papers/nagpurkar_pact07.pdf): retain the earlier lead/coverage/overhead motivation. Measure current-machine effects rather than importing another platform's improvement.

Additional primary-source reading during serialized timings:

- Call Graph Prefetching for Database Applications, TOCS 2003:
  https://pages.cs.wisc.edu/~jignesh/publ/CGP-TOCS.pdf
  The software variant uses a profiled call graph to select likely next functions;
  the evaluated system also uses tagged next-line hardware for within-function
  coverage. This supports examining offline successor rules, but its gains are
  not evidence for native data-T1 on our machine. The software and hardware
  components must not be conflated.
- APT-GET, EuroSys 2022:
  https://homes.cs.washington.edu/~baris/public/aptget.pdf
  Uses LBR-derived timing distributions to separate computation from miss delay
  when choosing data-prefetch distance and insertion site. Static code size in
  our queued FeedSim experiment is only a proxy; an average measured callback
  duration includes the stalls that effective prefetching would remove.
- Presage, arXiv v1, 18 September 2026:
  https://arxiv.org/html/2609.22636
  Recent data-prefetch research emphasizes interactions among independently
  selected hints and transformations around their address computations. It
  motivates separate/combined controls, not importing its data-workload gains
  into instruction prefetch results. It is a preprint and not evidence that
  code-target prefetch generalizes across our A classes. No external prompts,
  skills, or agent orchestration described by this paper were adopted.


Intel Granite Rapids core-event definitions checked 2026-09-24:
https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/
- FRONTEND_RETIRED.LATENCY_GE_64: qualifying retired instructions following
  at least 64 no-uop frontend cycles without an intervening backend stall;
  event C6/03, frontend filter 604006. Counts instructions/events, not cycles.
- ICACHE_DATA.STALLS: L1-instruction-miss fetch-stall cycles, 80/04.
- CYCLE_ACTIVITY.STALLS_L1D_MISS: execution stalls with an outstanding demand
  L1D miss, A3/0C, cmask0C. It can overlap other stall categories.
- BACLEARS.ANY: unknown-branch frontend resteers, 60/01; not a count of every
  BTB miss or every branch misprediction. Do not label changes as BTB warming.
The separate FeedSim diagnostic uses these existing harness event groups;
no diagnostic observations are pooled with the five-pair CPU confirmation.

Additional primary-source check during the component run (2026-09-24):

- [DEER, 2025 author preprint](https://arxiv.org/abs/2504.20387): profile-derived lookahead skips loop/recursion repetition; hardware consumes metadata and handles return paths. Its gem5 hardware/software result is not evidence that native T1 insertion alone produces the same gain. Relevant inference for this work: call count is a weak distance proxy when intervening work differs.
- [IP-CaT, 2026 author manuscript, labelled to appear at ISCA 2026](https://arxiv.org/abs/2605.12433): jointly changes translation handling and replacement for instruction prefetches. Relevant inference: obtaining a correct future line and keeping it useful are distinct problems. No IP-CaT hardware mechanism is implemented here, and changing T1/T2 is not claimed to reproduce its replacement policy.
- [IBM's primary PACT 2007 publication page](https://research.ibm.com/publications/call-chain-software-instruction-prefetching-in-j2ee-server-applications) separately identifies prefetch distance and count as parameters of the call-chain software scheme. Our immutable-array target experiments remain distinct from a general caller/callee algorithm.
- [Twig, MICRO 2021 author page](https://users.ece.cmu.edu/~asrirama/publication/micro21/) explicitly introduces BTB prefetch instructions. This does not establish that the data-prefetch hints used here repair BTB misses.


2026-09-24 final PMU scheduling check: Intel Granite Rapids lists L2_RQSTS.CODE_RD_MISS, ICACHE_DATA.STALLS, CYCLE_ACTIVITY.STALLS_L1D_MISS, ITLB_MISSES.WALK_ACTIVE and BACLEARS.ANY on programmable counters0–3. The forthcoming A1/NTA group therefore omits BACLEAR to fit four restricted counters without multiplexing; FeedSim stall-only group keeps BACLEAR because it does not also collect L2 code misses. Verified against https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/ . ITLB WALK_ACTIVE counts cycles with an instruction-fetch page walk active, not L1 ITLB misses or a disjoint stall total.
