# PrefetchIT migration

This directory is the portable source of truth for moving the project to a new
server. Git contains source, small plans/results, exact revisions, local source
patches, and SPEC configuration. It intentionally excludes benchmark datasets,
build trees, containers, `perf.data`, LBR dumps, generated protobuf, and binaries.

Read [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the canonical results,
invalidated historical peaks, experimental controls, acceptance criteria, and
the complete destination-server command sequence.

## Restore order

1. Clone the umbrella repository and this repository:

   ```bash
   git clone git@github.com:skyp0714/prefetchit.git
   cd prefetchit
   git clone git@github.com:skyp0714/llvm_prefetchit_injection.git llvm_prefetchit
   ```

2. Install common Ubuntu dependencies, then restore first-party repositories:

   ```bash
   llvm_prefetchit/migration/install_host_deps_ubuntu.sh
   llvm_prefetchit/migration/bootstrap.sh --root "$PWD"
   ```

3. Restore pinned benchmark source and source-level modifications:

   ```bash
   llvm_prefetchit/migration/bootstrap.sh --root "$PWD" \
     --with-benchmarks --apply-patches
   ```

4. Install licensed SPEC CPU suites from their ISO media and copy only the
   PrefetchIT configs:

   ```bash
   llvm_prefetchit/migration/bootstrap.sh --root "$PWD" --copy-spec-configs
   ```

5. Run each suite's installer to regenerate dependencies and datasets. DCPerf's
   Django patch is intentionally deferred until its installer creates
   `benchmarks/dcperf/benchmarks/django_workload/django-workload`; rerun
   `migration/apply_patches.sh` afterward.

6. Build the LLVM pass and profiling Python environment:

   ```bash
   cmake -S llvm_prefetchit -B llvm_prefetchit/build \
     -DLLVM_DIR="$(llvm-config-19 --cmakedir)"
   cmake --build llvm_prefetchit/build -j"$(nproc)"
   profiling/setup_venv.sh
   llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build
   ```

7. Validate the source-only restore, then the complete host toolchain and
   downloaded tool artifacts from `tools.lock.tsv`:

   ```bash
   llvm_prefetchit/migration/verify.sh --root "$PWD" --source-only
   llvm_prefetchit/migration/verify.sh --root "$PWD"
   ```

## What is preserved

- `repos.lock.tsv`: every first-party GitHub repository, branch, and exact SHA.
- `core_results.tsv`: machine-readable canonical and negative result index.
- `benchmarks.lock.tsv`: primary benchmark/tool source SHAs and archive hashes.
- `tools.lock.tsv`: exact versions/hashes for externally downloaded binaries.
- `patches/`: DCPerf/FeedSim/Django, TailBench, MicroSuite, memcached,
  PostgreSQL, Redis, HAProxy, CacheLib, Chipyard, gem5, and OpenJDK changes that
  previously existed only in local third-party checkouts or ignored work trees.
- `config/spec20xx/`: active custom SPEC configs. SPEC source and data are not
  copied because they are licensed.
- `HOST_REFERENCE.md` and `kernel-6.0.0.config`: hardware, toolchain, and kernel
  reference needed to interpret or reproduce performance results.

## What must be regenerated

- All benchmark install/build directories and Docker images.
- Serverless benchmark input data (`benchmarks-data` submodule); bootstrap only
  restores its `third-party/pypapi` source dependency.
- SPEC binaries and run directories.
- PEBS/LBR traces, `perf.data`, symbolized dumps, and plan sweep work dirs.
- Large experiment outputs. Durable result summaries and plotting inputs remain
  in the umbrella and LLVM repositories.
- DaCapo/Renaissance scratch data, Chipyard toolchains, CIRCT, Verilator, JDK,
  and GraalVM distributions. Match the versions in `tools.lock.tsv`.

## Host requirements

PEBS/LBR event availability is CPU-specific. The existing event encodings target
Granite Rapids. On another CPU, update `profiling/config/gnr_frontend_perf_events.txt`
only after validating equivalent events. `perf` must match the running kernel,
and profiling needs permission for PMU access (`sudo`, capabilities, or an
appropriate `perf_event_paranoid` policy). Performance runs should also restore
the project's core isolation, per-thread affinity, and frequency protocol; those
are experimental controls, not bootstrap defaults.

No script stores a sudo password. Authenticate with `sudo -v` or configure a
narrow sudoers policy for `perf`, CPU frequency controls, and cache eviction.
