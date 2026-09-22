# Host setup and restore (state as of 2026-09-15; layout and boot state updated 2026-09-22)

This is the destination-host log of the September 2026 restore, written so the
next restore does not have to rediscover the same problems. The canonical
manifest and scripts are still `llvm_prefetchit/migration/` (`README.md`,
`REPRODUCIBILITY.md`, `bootstrap.sh`, `verify.sh`); this file records what had
to be done differently on this host.

## 1. Layout

**One repository since 2026-09-22.** `git clone git@github.com:skyp0714/prefetchit.git`
brings the whole project: the six former component repositories
(`llvm_prefetchit_injection`, `frontend_profiling`, `icache_microbenchmark`,
`static_return_prefetch`, `flat_codegen`, `jit_prefetch`) were merged in with
their history, each under the *short* directory name the scripts already used
(`ROOT/llvm_prefetchit`, `ROOT/profiling`, ...). The old GitHub repositories are
archived read-only; `icache_microbenchmark/` is its old `prefetch_benefit`
branch (layout `microbench/src`).

After cloning, enable the artifact guard:

```bash
git config core.hooksPath .githooks   # rejects tracked files >10 MB
```

Tracked blobs over 10 MB were dropped from the merged history. They were raw
perf/PT dumps (`events.txt` 4.7 GB, `lbr_symbolic_dump.txt` 320 MB, ...) that
GitHub's 100 MB limit had made unpushable, which is why the old `flat_codegen`
repository had 93 commits that never left the host. Results go into git as
summaries only (`runs.csv`, `*_stats*.txt`, `counters.csv`, plans).

## 2. Host

- Intel Xeon 6787P (86 cores, no SMT, 64 KiB L1I / 2 MiB L2 / 336 MiB L3),
  629 GiB RAM, Ubuntu 24.04.4, kernel 6.8.0-138-generic, `perf` 6.8.12.
  `linux-tools-6.8.0-139` is also installed for the next kernel.
- Shared machine: `/etc/default/grub` carries other users' edits. Coordinate
  before changing boot parameters.
- **Kernel command line vs GRUB file disagree.** The running kernel was booted
  with `intel_pstate=disable iommu=pt intel_iommu=on sm_on no5lvl`, but
  `/etc/default/grub` now only has `quiet splash efi=nosoftreserve` (the old
  line is commented out). Consequences:
  - **resolved 2026-09-22**: the host rebooted (11:11) into 6.8.0-139 *without*
    `intel_pstate=disable`, so the driver is now `intel_pstate` in active/HWP
    mode, 0.8-3.8 GHz, and **`MODE=3.8ghz` works again** (it was impossible
    under `acpi-cpufreq`). The protocol itself does not change: after every
    reboot `freeze_platform.sh show` prints `governor=powersave ... no_turbo=0`
    with the uncore floating, C6 back on and `perf_event_paranoid=4`, and it
    must print a frozen state before any measurement;
  - before that reboot: cpufreq driver = `acpi-cpufreq`, P-states 0.8-2.0 GHz
    plus a global boost flag; only `MODE=2ghz` was available. Kernel 6.8.0-139
    with intel_pstate/HWP is the configuration under which the canonical
    results were taken
    (README §4; forensics history: `git show 2777fce:llvm_prefetchit/results/paper_goal_20260815/CONFIG_LOG.md`, "Platform
    forensics"). The reference host additionally used
    `isolcpus=10-31 nohz_full=10-31 rcu_nocbs=10-31`; the campaign scripts pin
    threads explicitly, so isolation is optional.
- `kernel.perf_event_paranoid=-1` / `kptr_restrict=0` are not persisted
  (`/etc/sysctl.d/10-kernel-hardening.conf` sets `kptr_restrict=1`);
  `freeze_platform.sh` sets both at run time.
- Do **not** install `cpufrequtils`: its init script switches every core to
  `ondemand` on install.

## 3. Toolchain

| need | what was done | why |
|---|---|---|
| clang/opt/llc 19 | official LLVM 19.1.7 tarball in `/opt/llvm-19.1.7`, symlinked as `/usr/local/bin/{clang,clang++,opt,llc,llvm-config,llvm-objdump,llvm-nm,llvm-addr2line,llvm-profgen,llvm-symbolizer,lld,...}-19` | apt `clang-19` depends on `libobjc-13-dev`, which conflicts with the jammy-PPA `gcc-13.4` that owns the system toolchain; the tarball also matches the reference host's 19.1.7 exactly |
| gfortran | skipped | same PPA conflict; nothing in the flow needs it |
| ninja, jq, rg, siege, memcached, help2man, libcups/fontconfig/alsa/X11 dev headers | apt | pass build, DCPerf, OpenJDK build |
| Python 3.10 | `ppa:deadsnakes/ppa` → `python3.10{,-dev,-venv,-distutils}` | DCPerf Django ships cp310 wheels; system Python is 3.12 |
| JDK 11 (Cassandra 3.11) | apt `openjdk-11-jdk-headless` | `find_java_home.py` picks JDK 21 → export `JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64` for Django runs |
| Boot JDK 17.0.18+8 (Temurin), GraalVM CE 17.0.9, Renaissance 0.16.1, DaCapo 23.11-MR2-chopin, CIRCT firtool-1.75.0 (`circt-full-shared-linux-x64`), Verilator 5.046 (source build) | downloaded/built into `benchmarks/tools/` (archives cached in `.cache/prefetchit/`) | all hashes in `tools.lock.tsv` verified; the DaCapo jar is the entry at the *root* of the 6 GB zip, the `dacapo-23.11-MR2-chopin/` data directory must sit beside it |
| profiling Python env | `profiling/setup_venv.sh` (+ `pytest`) | plan tools/tests |

## 4. Benchmark sources

`bootstrap.sh --with-benchmarks` was run in pieces because two pinned
revisions are local commits that were never pushed:

| path | pinned | available | used |
|---|---|---|---|
| `benchmarks/DeathStarBench` | `358029c7` | no | `origin/master` (`6ecb097`) + submodules |
| `benchmarks/datacenter_sources/MicroSuite` | `57e4340e` | no | `origin/master` (`cb81f7b`) + `microsuite-local.patch` (applies cleanly) |
| `benchmarks/chipyard` | `63c15068` | yes | checked out + `chipyard-local.patch`; set up with chipyard's own flow (below), **not** `git submodule update --recursive` (that pulls the RISC-V LLVM/GCC toolchains through `generators/ara`) |
| everything else | as pinned | yes | as pinned, patches applied |
| SPEC CPU2017/2026 | licensed media | – | deferred (`--copy-spec-configs` after install) |

`git submodule update --init --recursive` on chipyard must **not** be used;
it is what the manifest says but it fetches >20 GB of toolchain repositories.

### Chipyard / Verilator simulator (stage-2 reference workload)

```bash
# conda (no root): Miniforge into benchmarks/tools/miniforge3
bash Miniforge3-Linux-x86_64.sh -b -p benchmarks/tools/miniforge3
export PATH=$PWD/benchmarks/tools/miniforge3/bin:$PATH
cd benchmarks/chipyard
./scripts/init-submodules-no-riscv-tools.sh              # minimal generator set (no --full)
./build-setup.sh riscv-tools --use-lean-conda --skip-submodules --skip-ctags --skip-firesim --skip-marshal --skip-clean
#   ~1 h: regenerates the conda lockfile for glibc 2.39, builds riscv-tests (qsort.riscv), precompiles Scala, installs firtool
source env.sh
# reference simulator: our Verilator 5.046 first, clang-19 with debug info (profiling/archive/.../launch_prefetchit_builds.sh recipe)
export PATH=$ROOT/benchmarks/tools/verilator-5.046-install/bin:$PATH VERILATOR_ROOT=$ROOT/benchmarks/tools/verilator-5.046-install/share/verilator
cd sims/verilator && make CONFIG=DualMegaBoomAndSingleRocketConfig CC=clang-19 CXX=clang++-19 LINK=clang++-19 \
  EXTRA_SIM_CXXFLAGS='-g -fno-omit-frame-pointer -std=c++20 -Wno-c++11-narrowing' -j64
```

`source env.sh` must run without `set -u` (the conda activate hook references an unset `RISCV`). The simulator build took ~37 min (single-TU clang-19 -O3 -g).

`bench_common.sh` expects the RISC-V toolchain at
`benchmarks/tools/rocket-tools/riscv`; it is a symlink to
`benchmarks/chipyard/.conda-env/riscv-tools`. The chipyard Makefile patch sets
`VM_PARALLEL_BUILDS=$(nproc)`, which (≠1) makes Verilator emit the single
`VTestDriver__ALL.cpp` translation unit — the same structure the pass-injected
variants are compiled from, so baseline and variants differ only by the plan.
Verilator 5.046 puts `OPT_FAST` (-Os) before chipyard's `-O3`, so both are -O3.

## 5. Builds that were regenerated

```bash
# LLVM pass + tests
cmake -S llvm_prefetchit -B llvm_prefetchit/build -G Ninja \
  -DLLVM_DIR="$(llvm-config-19 --cmakedir)" -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19
cmake --build llvm_prefetchit/build
llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build
profiling/.venv/bin/python -m pytest llvm_prefetchit/tests

# thread-pin shim used by the Django harness
llvm_prefetchit/scripts/platform/build_pthread_core_pin.sh

# microbenchmark (clang, -march=graniterapids)
make -C icache_microbenchmark/microbench/src all prefetch_test icache_flush_dummy

# patched OpenJDK 17u (jit_prefetch/openjdk, ~15 min on 48 jobs)
cd jit_prefetch/openjdk
bash configure --with-boot-jdk=$ROOT/benchmarks/tools/jdk17 --enable-headless-only \
  --disable-warnings-as-errors --with-native-debug-symbols=none   # X11 dev headers still required
make images CONF=linux-x86_64-server-release JOBS=48
# JCodeStream / WideApi: javac with the built JDK (see jit_prefetch/README.md)
```

### DCPerf FeedSim (rootless)

```bash
cd benchmarks/dcperf
DCPERF_ROOTLESS=1 BP_CC=gcc BP_CXX=g++ bash packages/feedsim/install_feedsim_x86_64_ubuntu.sh
```

On Ubuntu 24.04 the installer skips its Ubuntu-22 compatibility patches, and
folly then fails with gcc 13 (`std::system_error`, `numeric_limits` not
declared). Apply them by hand once, then rerun the installer:

```bash
cd benchmarks/feedsim/src/third_party
git -C folly apply ../../../../../packages/feedsim/patches/ubuntu-22-compatibility/folly.diff
git -C rsocket-cpp apply ../../../../../packages/feedsim/patches/ubuntu-22-compatibility/rsocket-cpp.diff
```

`llvm_prefetchit/scripts/dispatch/build_feedsim_manual_variants.sh` now reproduces
the installer's environment (vendored boost/glog/gflags paths, staged cmake
3.14.5, `lib64→lib` ninja fixup); without it the relink picks the system glog
and fails on `google::kLogSiteUninitialized`.

### DCPerf Django (rootless)

```bash
mkdir -p /tmp/py310bin && ln -sf /usr/bin/python3.10 /tmp/py310bin/python3
printf '#!/bin/bash\nexit 0\n' > /tmp/py310bin/apt && chmod +x /tmp/py310bin/apt   # installer calls apt
sudo mkdir -p /data/cassandra && sudo chown $USER /data/cassandra
mkdir -p benchmarks/dcperf/benchmarks/siege/bin && ln -sf /usr/bin/siege benchmarks/dcperf/benchmarks/siege/bin/siege
cd benchmarks/dcperf
PATH=/tmp/py310bin:$PATH OUT=$PWD/benchmarks/django_workload IBCC=/usr/bin/c++ \
  bash packages/django_workload/install_django_workload_x86_64_ubuntu22.sh
# the installer applies DCPerf's own template patches; replace them with the project patch:
cd benchmarks/django_workload/django-workload && git checkout -- . && \
  git apply $ROOT/llvm_prefetchit/migration/patches/django-workload-local.patch
```

The Django variant builder needs the 24 `ICacheBuster.part*.o` objects that
used to live in an ignored work tree; regenerate them once with
`gen_icache_buster.py --num_methods=100000 --num_splits=24` and
`clang++ -O2 -g -fno-omit-frame-pointer -fPIC -c` into
`llvm_prefetchit/work/datacenter_goal_20260708/django/icb_base/`.

## 6. Freezing the platform

```bash
sudo MODE=2ghz  llvm_prefetchit/scripts/platform/freeze_platform.sh   # services, JVM
sudo MODE=3.8ghz llvm_prefetchit/scripts/platform/freeze_platform.sh  # single-core, intel_pstate only
sudo MODE=restore llvm_prefetchit/scripts/platform/freeze_platform.sh
llvm_prefetchit/scripts/platform/freeze_platform.sh show
```

It replaces `configure_fixed_frequency{,_v2}.sh` (intel_pstate only) and works
with acpi-cpufreq. `campaign_common.sh`'s `fc_assert_frequency` accepts the
resulting state (governor=performance, min=max, boost off).

## 7. Verification

`llvm_prefetchit/migration/verify.sh --root $ROOT` passes on this host (host
tools and `tools.lock.tsv` hashes); `--source-only` passes as well.
