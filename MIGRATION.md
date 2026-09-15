# PrefetchIT migration entry point

The canonical migration manifest and scripts live in
`llvm_prefetchit/migration/README.md`. They preserve all first-party repositories,
exact third-party source revisions, local benchmark/OpenJDK patches, active SPEC
configs, and the reference host/toolchain contract.

The performance acceptance contract and canonical result index are in
`llvm_prefetchit/migration/REPRODUCIBILITY.md` and `core_results.tsv`.

The migration intentionally does not copy benchmark installations, licensed SPEC
media, datasets, containers, build trees, traces, or raw result directories. Those
are regenerated on the destination host.

The tested migration entry-point revision is
`3b7976f08b0f02eb278c33e864a747217e4ec314` (tag
`migration-2026-09-14-r3`). Check it out explicitly when
reproducing this handoff rather than assuming a future `main` is identical.

After cloning this repository and `llvm_prefetchit_injection`, run:

```bash
git -C llvm_prefetchit checkout 3b7976f08b0f02eb278c33e864a747217e4ec314
llvm_prefetchit/migration/bootstrap.sh --root "$PWD" \
  --with-benchmarks --apply-patches
llvm_prefetchit/migration/verify.sh --root "$PWD" --source-only
```

See the canonical guide before installing SPEC or starting profiling.
