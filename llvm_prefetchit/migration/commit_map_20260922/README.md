# Commit map of the 2026-09-22 repository merge

The six component repositories were merged into `skyp0714/prefetchit` with
`git filter-repo --strip-blobs-bigger-than 10M --to-subdirectory-filter <dir>`,
which rewrites every commit id. Any commit id written down before that date —
in `docs/`, in the campaign READMEs, in a notebook — refers to the *old* id.

Each `<component>.tsv` is filter-repo's map, `old-id new-id` (space-separated, one header
line). To translate:

```bash
grep ^<old-prefix> llvm_prefetchit/migration/commit_map_20260922/<component>.tsv
```

Paths changed too: what was `results/x` in `llvm_prefetchit_injection` is
`llvm_prefetchit/results/x` here, so `git -C llvm_prefetchit show SHA:results/x`
becomes `git show <new-id>:llvm_prefetchit/results/x`.

The pre-merge repositories are archived read-only on GitHub, and the original
`.git` directories (including the >10 MB blobs that were stripped) are on this
host in `~/prefetchit_oldgit_20260922/` plus the tarball
`~/prefetchit_git_backup_20260922.tar`.
