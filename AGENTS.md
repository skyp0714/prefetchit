# Experiment artifact retention

- User instruction: after each failed, rejected, or superseded experiment, retain its results and remove its generated bulk artifacts immediately. Do not wait until the campaign ends.
- Preserve compact measurements, negative-result summaries, operating settings, commands, source/patch records, binary hashes, and exclusion reasons before cleanup.
- Remove the experiment's unused executables, object files, build directories, generated indices, and decoded trace copies once their needed results have been extracted. Keep only the original and currently useful winning/reference/control artifacts needed for subsequent experiments.
- Never delete benchmark source/input datasets, original packages, shared dependencies, unrelated work, or active experiment artifacts as part of this cleanup. Do not follow symlinks into those resources.
- Check free space before each build/run and budget for temporary copies and service logs. If space is insufficient, clean completed artifacts before starting another experiment. Record paths and bytes removed, then check the recovered space.
- User-authorized cold storage: create project subdirectories under `/fast-lab-share/hnpark2` for confirmed binaries and reusable data that do not need local I/O speed. Keep compact results and the current measurement working set local.
- NAS stability is mandatory: transfer with **rsync**, one transfer process at a time, conservatively rate-limited (default `--bwlimit=20480`, 20 MiB/s). Do not use parallel copies, bulk `cp`/`mv`, unbounded checksum scans, or `--delete` on the shared NAS. Use a fresh destination and resumable partial files.
- Verify each NAS copy with a sequential, rate-limited SHA-256 read before removing any local bytes. Preserve a manifest and existing access paths where appropriate. Stage an offloaded executable or input back onto local storage using the same controlled rsync process before timing it; do not benchmark through a NAS symlink.
