# First-epoch IT0 and ordinary-path T1 experiment

This is an experimental extension of the byte-preserving direct-call rewriter.
Validation and application results belong in the campaign records; merely
building the variant is not evidence of a speedup.

The existing scheduler-clock module publishes the incoming task's selection
time. It performs no IT0 injection. The first selected user-space call that
observes a new CPU epoch before the 10 microsecond deadline issues at most eight
RIP-relative IT0 hints. Later selected calls use the existing cost75 T1 target
lists. First-call targets contain that call's T1 list and additional unique code
lines ranked from training miss observations. Heldout and E2E outcomes do not
select these targets.

The gate uses RDPID and per-CPU seen-epoch words on its common path. A newly
observed epoch additionally uses RDTSCP, rejects an observed CPU/epoch change,
and checks the deadline. The original register values, flags, stack arguments,
return addresses, instruction addresses and data remain intact. Appended stubs
have CFA rules for each stack-changing path and a merged GNU unwind table.
Executable and writable regions are separate.

`hybrid_map.c` is a preload constructor. It finds the specially named, zero-file
ELF BSS reservation and replaces only its clock half with the module's read-only
mapping. It checks CPU features, slot ABI and mapping bounds, and fails startup
when the selected executable cannot obtain its clock. Ordinary container
entrypoint/privilege-drop/Mongo-shell executables have no such sections and are
left alone. The process-private seen-epoch half remains writable. The experiment
temporarily permits read-only access to the timestamp-only device for MongoDB's
unchanged uid; module unload removes the device after all containers exit.

Controls retain the same executable layout and guard path:

- IT0 in the first burst, then T1 at ordinary calls.
- T1 in the first burst and at ordinary calls.
- NOP at every inserted hint, preserving timing checks and branches.
- Original and the existing unguarded cost75 T1 binary as separate references.

The diagnostic ELF additionally records gate checks, qualifying bursts, expired
epochs, observed races, qualifying-age sum/max and the number in the first half
of the window. It is excluded from E2E timing. Counters describe architectural
gate outcomes, not cache fills or all speculative hint execution. A separate
post-ROI `FRONTEND_RETIRED.LATE_SWPF` window counts demand misses overlapping
ongoing PREFETCHIT0/1 fetches. Zero counts do not prove successful delivery or
an empty fetch queue.

The shared clock starts before the architectural context switch. Consequently,
the gate's age includes remaining kernel work, and the first inserted call may
occur after earlier user instructions. Preemption, migration and speculation
prevent an exact hardware once-per-switch guarantee; stale choices affect only
optional prefetches. No measurement here directly observes fetch-queue occupancy
or establishes that IT0 requires a completely empty queue.

`scripts/class_b/hybrid_campaign.py` runs native ABI/flag/return/unwind tests,
the real-module mapping/age diagnostic, and fresh full Media C4 comparisons with
one persistent connection per Nginx worker. Clean E2E timing uses 50 seconds of
warmup and a 60-second ROI; PMU collection follows it. Throughput, mean/p99,
whole-stack and pool CPU/request must accompany retired-L2 and speculative L2
code-read counts. The experiment does not replace existing results or claim
maximum-throughput validation.

Instruction semantics: [Intel ISA extension reference](https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf).
Counter semantics: [Intel Granite Rapids PMU reference](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).
