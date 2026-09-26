# Granite Rapids event semantics

Machine: Intel Xeon6787P. Intel's Granite Rapids event table confirms the raw PEBS config already used in this campaign: eventC6/umask03/PEBS_FRONTEND13 is FRONTEND_RETIRED.L2_MISS. It samples retired instructions with an instruction-L2 true miss; it is different from the demand-request L2_RQSTS.CODE_RD_MISS counter used for MPKI.

The separate FE64 diagnostic uses eventC6/umask03/PEBS_FRONTEND604006, FRONTEND_RETIRED.LATENCY_GE_64: instructions following at least64cycles of frontend starvation without a backend-stall interruption. Its cause need not be an L2 miss. Separate L2 and FE64 captures are NOT an event intersection, a per-miss hidden-stall fraction, or a speedup upper bound. Both use LBR32 and stable JIT metadata mapping. Sampling period2003,18s perprocess/event; serial recordings, no timing-gain claims.

FRONTEND_RETIRED.LATE_SWPF applies specifically to PREFETCHIT0/1. Our current emitter uses data PREFETCHT1, so that counter is not a valid direct lateness metric here.

Primary source: https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/

Optional post-timing pilot counters: ITLB_MISSES.WALK_COMPLETED usesevent11/umask0E, and ITLB_MISSES.STLB_HIT uses11/20 onthisGNR CPU (not older0x85). Both are speculative. Normalize by completed queries in that separate PMU window and retain full-scheduling/rate/drop checks. A lower walk count alone is not proof of prefetch speedup or causal attribution.

The GNR event table was rechecked: L2_RQSTS.CODE_RD_MISS is24H/24H and is speculative; BR_INST_RETIRED.INDIRECT isC4H/80H, excludes returns, and includes indirect jumps as well as calls. It is not a Java virtual-call counter. ITLB and L2-request events are constrained to programmable counters0–3; optional diagnostics must check full scheduling. NMI watchdog remains at the host default1.
