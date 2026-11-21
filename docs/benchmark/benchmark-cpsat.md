# Benchmark (ortools-cpsat 9.15.6755)

Generated 2026-11-20T17:15:02Z on Intel(R) Core(TM) i5-6200U CPU @ 2.30GHz, 4 logical CPUs, 11.0 GB RAM, Linux 7.2.15+kali-amd64, Python 3.14.10.
Dataset `demo-bajaur-v1` sha256 `deebc2d838cbf143…` (synthetic).

| Measure | Median ms | Max ms | Target |
|---|---|---|---|
| default baseline run | 83 | 526 | — |
| default optimized run | 177 | 191 | ≤ 10,000 |
| default greedy run | 828 | 854 | — |
| 20-case stress suite (both plans) | 2029 | 2029 | ≤ 60,000 |

## Grid (coverage within 45 min, %)

| Budget PKR | Units | Equity floor | Baseline | Greedy | Optimized | Opt − greedy (pp) |
|---|---|---|---|---|---|---|
| 0 | 0 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 0 | 0 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 0 | 1 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 0 | 1 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 0 | 2 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 0 | 2 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 150,000 | 0 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 150,000 | 0 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 150,000 | 1 | 0% | 48.61 (—) | 62.32 (N02) | 62.79 (N04) | 0.47 |
| 150,000 | 1 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 150,000 | 2 | 0% | 48.61 (—) | 62.32 (N02) | 62.79 (N04) | 0.47 |
| 150,000 | 2 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 300,000 | 0 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 300,000 | 0 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 300,000 | 1 | 0% | 48.61 (—) | 62.32 (N02) | 62.79 (N04) | 0.47 |
| 300,000 | 1 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 300,000 | 2 | 0% | 48.61 (—) | 73.07 (N02,N04) | 74.66 (N04,N07) | 1.59 |
| 300,000 | 2 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 450,000 | 0 | 0% | 48.61 (—) | 48.61 (—) | 48.61 (—) | 0.0 |
| 450,000 | 0 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 450,000 | 1 | 0% | 48.61 (—) | 62.32 (N02) | 62.79 (N04) | 0.47 |
| 450,000 | 1 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |
| 450,000 | 2 | 0% | 48.61 (—) | 73.07 (N02,N04) | 74.66 (N04,N07) | 1.59 |
| 450,000 | 2 | 10% | NO_SOLUTION | NO_SOLUTION | NO_SOLUTION | — |

Audit pass rate on completed runs: 100%. Optimized never below greedy: True.
Ties are reported as ties. NO_SOLUTION means the equity floor cannot be met; no numbers are shown for it.
