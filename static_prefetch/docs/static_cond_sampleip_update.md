# Static COND Target Selection Update: Sample-IP Truth

## Correction

Earlier COND target-selection experiments evaluated static candidates against
`LBR[0].to`. That is not always the actual L2I miss address. In the PEBS/LBR
trace, the first field is the sampled miss IP, while `LBR[0]` describes the most
recent branch edge.

For COND samples in the aggregated baseline traces:

| Relation | Share |
|---|---:|
| sample IP cacheline == `LBR[0].to` cacheline | 71.09% |
| sample IP exactly == `LBR[0].to` | 53.26% |
| sample IP cacheline == `LBR[0].from` cacheline | 39.28% |
| `LBR[0].from` and `LBR[0].to` are same cacheline | 38.06% |

Therefore, `LBR[0].to` is a useful branch-edge feature, but the evaluation truth
and profile-guided plan target must use the actual PEBS sample IP.

## Static Candidate Model

The static COND generator now supports:

```text
--candidate-targets taken|source|both
--target-window-lines N
```

The current best sample-IP-oriented static candidate set is:

```text
candidate-targets = both
base cachelines   = conditional branch source + explicit taken target
window            = next 16 cachelines after each base cacheline
ranking           = tail-sparse
```

This captures the common case where the miss lands inside the target block, not
exactly on the first instruction of the taken edge.

## Recall Against Sample-IP Truth

Ground truth: 47,577 resolved COND samples, 24,638 unique sample-IP cachelines.

| Static rule | Top 50k | Top 100k | Top 150k | Top 200k | Top 250k | Top 300k |
|---|---:|---:|---:|---:|---:|---:|
| source+taken, no window | 38.65% | 64.95% | 75.09% | 87.06% | - | - |
| source+taken, window 4 | 39.89% | 52.13% | 71.23% | 79.19% | 92.73% | 92.73% |
| source+taken, window 8 | 40.36% | 50.58% | 71.71% | 79.34% | 94.18% | 94.19% |
| source+taken, window 16 | 40.41% | 49.17% | 72.19% | 79.62% | 95.61% | 95.61% |

The windowed rule improves high-coverage recall substantially, at the cost of a
larger static candidate list and lower early precision.

## Injection Policies Under Test

Profile-guided COND plans use sample-IP targets and existing LBR-depth site
selection:

```text
sample branch type = COND
prefetch target    = PEBS sample IP cacheline
site candidates    = LBR depth 4..24
site policy        = top-sites, budget 8 per target
prefetch lines     = target + 0 and +64 bytes
coverage points    = 25%, 50%, 75%, 100%
```

Static plans under test:

```text
static_win16_top50k_current
  target = static source/taken/window16 candidate
  site   = current conditional branch
  prefetch lines = target only

static_win16_top100k_current
  same as above, larger target set

static_win16_top50k_prev4
  target = static source/taken/window16 candidate
  site   = four preceding branch sites in the same function
  prefetch lines = target only
```

The `prev4` policy increases lead time but also increases instruction count
substantially.
