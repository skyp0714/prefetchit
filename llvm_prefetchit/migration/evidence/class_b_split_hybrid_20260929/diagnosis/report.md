# Split75: measured frontend components and residual coverage

Completed campaigns remain separate. PMU windows follow clean endpoint timing; each has its own request denominator. Different event populations and overlapping stall counts are not an exclusive causal partition. Retired LBR ages do not measure prefetch issue-to-fetch lead. Branch-target association does not establish BTB/FDIP state. Top-down slots are not request critical-path time or an Amdahl bound.

## hybrid_screen

Raw Mongo3 counts/request, arithmetic mean of four trials.

| Event | original | split75 | early_t1 | early_it0 |
|---|---:|---:|---:|---:|
| Retired L2 | 5,457.543 | 2,059.483 | 2,078.104 | 2,075.928 |
| L2 code-read miss | 61,068.468 | 55,491.416 | 56,754.085 | 56,371.366 |
| I-cache stall cycles | 610,038.600 | 459,031.681 | 472,366.089 | 466,708.762 |
| ITLB walk-active cycles | 192,242.360 | 92,683.468 | 95,262.996 | 97,471.997 |
| Unknown-branch bubble cycles | 732,249.728 | 606,707.877 | 602,423.773 | 603,760.818 |
| Branch mispredictions | 19,514.025 | 19,701.967 | 19,876.768 | 20,023.186 |
| DSB uops | 1,338,713.691 | 1,343,373.974 | 1,344,585.129 | 1,352,731.598 |
| MITE uops | 1,057,973.087 | 1,071,414.875 | 1,091,116.280 | 1,094,608.155 |
| Late instruction prefetch | 0.000 | 0.000 | 0.000 | 1.372 |
| Speculative T1/T2 executions | 0.000 | 8,627.737 | 8,427.777 | 8,407.193 |
| L1D fill-buffer-full cycles | 12,982.995 | 13,685.890 | 13,762.627 | 13,630.779 |

Service MPKI uses retired user instructions from the same counter window. Speculative code-read requests and retired frontend miss events have different populations; neither is an exclusive measure of request waiting time. CPU shares are clean-ROI accounting ratios, not request-critical-path or Amdahl bounds.

| Service / policy | Retired L2 MPKI | Code-read MPKI | Service CPU us/request | Share of whole CPU |
|---|---:|---:|---:|---:|
| mongo_user / original | 3.161 | 35.249 | 531.650 | 8.978% |
| mongo_movie / original | 3.132 | 34.866 | 531.677 | 8.979% |
| mongo_storage / original | 8.388 | 96.171 | 173.162 | 2.924% |
| mongo_user / split75 | 1.118 | 31.390 | 487.349 | 8.348% |
| mongo_movie / split75 | 1.121 | 31.110 | 487.148 | 8.344% |
| mongo_storage / split75 | 3.868 | 87.994 | 157.573 | 2.699% |
| mongo_user / early_t1 | 1.134 | 32.039 | 496.577 | 8.477% |
| mongo_movie / early_t1 | 1.117 | 31.738 | 496.519 | 8.476% |
| mongo_storage / early_t1 | 3.830 | 87.508 | 160.582 | 2.741% |
| mongo_user / early_it0 | 1.122 | 31.809 | 496.242 | 8.476% |
| mongo_movie / early_it0 | 1.119 | 31.348 | 496.077 | 8.473% |
| mongo_storage / early_it0 | 3.934 | 88.805 | 160.685 | 2.744% |

Individual paired-log t95 reductions; negative means an increase. No multiplicity correction.

| Policy / control | Event | Reduction [95% CI] |
|---|---|---:|
| split75 / original | Retired L2 | +62.268% [+61.370, +63.144] |
| split75 / original | L2 code-read miss | +9.134% [+8.367, +9.894] |
| split75 / original | I-cache stall cycles | +24.757% [+23.783, +25.718] |
| split75 / original | ITLB walk-active cycles | +51.794% [+49.971, +53.551] |
| split75 / original | Unknown-branch bubble cycles | +17.144% [+16.690, +17.595] |
| split75 / original | Branch mispredictions | -0.974% [-3.759, +1.737] |
| split75 / original | DSB uops | -0.343% [-1.588, +0.887] |
| split75 / original | MITE uops | -1.272% [-2.667, +0.103] |
| split75 / original | L1D fill-buffer-full cycles | -5.543% [-14.861, +3.019] |
| early_t1 / original | Retired L2 | +61.925% [+61.209, +62.629] |
| early_t1 / original | L2 code-read miss | +7.067% [+6.212, +7.914] |
| early_t1 / original | I-cache stall cycles | +22.570% [+21.916, +23.218] |
| early_t1 / original | ITLB walk-active cycles | +50.455% [+49.352, +51.533] |
| early_t1 / original | Unknown-branch bubble cycles | +17.734% [+16.564, +18.888] |
| early_t1 / original | Branch mispredictions | -1.856% [-2.425, -1.289] |
| early_t1 / original | DSB uops | -0.442% [-1.049, +0.162] |
| early_t1 / original | MITE uops | -3.134% [-3.996, -2.279] |
| early_t1 / original | L1D fill-buffer-full cycles | -6.071% [-12.907, +0.350] |
| early_t1 / split75 | Retired L2 | -0.908% [-2.098, +0.269] |
| early_t1 / split75 | L2 code-read miss | -2.275% [-2.558, -1.993] |
| early_t1 / split75 | I-cache stall cycles | -2.907% [-4.188, -1.642] |
| early_t1 / split75 | ITLB walk-active cycles | -2.779% [-8.880, +2.980] |
| early_t1 / split75 | Unknown-branch bubble cycles | +0.712% [-1.239, +2.625] |
| early_t1 / split75 | Branch mispredictions | -0.873% [-3.997, +2.157] |
| early_t1 / split75 | DSB uops | -0.099% [-1.884, +1.655] |
| early_t1 / split75 | MITE uops | -1.838% [-3.189, -0.505] |
| early_t1 / split75 | Speculative T1/T2 executions | +2.319% [+1.587, +3.045] |
| early_t1 / split75 | L1D fill-buffer-full cycles | -0.501% [-6.606, +5.254] |
| early_it0 / original | Retired L2 | +61.962% [+61.707, +62.216] |
| early_it0 / original | L2 code-read miss | +7.692% [+7.200, +8.181] |
| early_it0 / original | I-cache stall cycles | +23.495% [+23.192, +23.797] |
| early_it0 / original | ITLB walk-active cycles | +49.302% [+46.925, +51.572] |
| early_it0 / original | Unknown-branch bubble cycles | +17.547% [+16.536, +18.545] |
| early_it0 / original | Branch mispredictions | -2.620% [-5.206, -0.098] |
| early_it0 / original | DSB uops | -1.053% [-1.948, -0.165] |
| early_it0 / original | MITE uops | -3.465% [-4.616, -2.327] |
| early_it0 / original | L1D fill-buffer-full cycles | -5.182% [-12.642, +1.784] |
| early_it0 / split75 | Retired L2 | -0.810% [-3.063, +1.394] |
| early_it0 / split75 | L2 code-read miss | -1.586% [-2.101, -1.074] |
| early_it0 / split75 | I-cache stall cycles | -1.677% [-3.092, -0.281] |
| early_it0 / split75 | ITLB walk-active cycles | -5.171% [-12.277, +1.486] |
| early_it0 / split75 | Unknown-branch bubble cycles | +0.486% [-0.206, +1.173] |
| early_it0 / split75 | Branch mispredictions | -1.631% [-2.141, -1.123] |
| early_it0 / split75 | DSB uops | -0.708% [-2.262, +0.823] |
| early_it0 / split75 | MITE uops | -2.165% [-2.609, -1.723] |
| early_it0 / split75 | Speculative T1/T2 executions | +2.557% [+1.960, +3.149] |
| early_it0 / split75 | L1D fill-buffer-full cycles | +0.342% [-1.674, +2.317] |
| early_it0 / early_t1 | Retired L2 | +0.097% [-1.825, +1.982] |
| early_it0 / early_t1 | L2 code-read miss | +0.673% [+0.215, +1.129] |
| early_it0 / early_t1 | I-cache stall cycles | +1.195% [-0.010, +2.386] |
| early_it0 / early_t1 | ITLB walk-active cycles | -2.327% [-8.105, +3.142] |
| early_it0 / early_t1 | Unknown-branch bubble cycles | -0.228% [-2.826, +2.305] |
| early_it0 / early_t1 | Branch mispredictions | -0.751% [-3.618, +2.037] |
| early_it0 / early_t1 | DSB uops | -0.608% [-1.348, +0.126] |
| early_it0 / early_t1 | MITE uops | -0.321% [-1.221, +0.570] |
| early_it0 / early_t1 | Speculative T1/T2 executions | +0.243% [-0.118, +0.604] |
| early_it0 / early_t1 | L1D fill-buffer-full cycles | +0.838% [-3.524, +5.017] |

## lead_screen

Raw Mongo3 counts/request, arithmetic mean of four trials.

| Event | split75 | residual_t1 | lead512_nop | lead512 |
|---|---:|---:|---:|---:|
| Retired L2 | 2,067.830 | 1,995.625 | 5,678.151 | 2,476.129 |
| L2 code-read miss | 55,412.938 | 55,598.478 | 62,991.345 | 55,963.605 |
| I-cache stall cycles | 459,263.485 | 457,861.554 | 640,762.964 | 469,089.504 |
| ITLB walk-active cycles | 96,197.817 | 94,860.443 | 192,197.984 | 101,612.538 |
| Unknown-branch bubble cycles | 606,912.123 | 608,874.203 | 800,183.898 | 629,936.804 |
| Branch mispredictions | 19,819.742 | 19,805.156 | 19,870.431 | 19,760.810 |
| DSB uops | 1,374,607.582 | 1,416,078.599 | 1,359,639.658 | 1,375,463.554 |
| MITE uops | 1,070,032.466 | 1,076,098.156 | 1,078,591.108 | 1,073,308.523 |
| Retired L1I | 16,011.824 | 16,038.517 | 15,983.566 | 15,854.296 |
| DSB-to-MITE penalty cycles | 47,811.160 | 48,120.849 | 48,101.189 | 47,939.646 |
| I-cache stall periods | 28,698.890 | 28,861.395 | 26,240.497 | 28,238.944 |
| Late instruction prefetch | 0.000 | 0.000 | 0.000 | 0.000 |
| Speculative T1/T2 executions | 8,615.099 | 8,637.794 | 0.000 | 8,938.647 |
| L1D fill-buffer-full cycles | 14,399.595 | 14,764.398 | 13,359.469 | 14,923.342 |

Service MPKI uses retired user instructions from the same counter window. Speculative code-read requests and retired frontend miss events have different populations; neither is an exclusive measure of request waiting time. CPU shares are clean-ROI accounting ratios, not request-critical-path or Amdahl bounds.

| Service / policy | Retired L2 MPKI | Code-read MPKI | Service CPU us/request | Share of whole CPU |
|---|---:|---:|---:|---:|
| mongo_user / split75 | 1.119 | 30.996 | 489.338 | 8.375% |
| mongo_movie / split75 | 1.107 | 30.935 | 486.894 | 8.333% |
| mongo_storage / split75 | 3.917 | 87.371 | 157.615 | 2.698% |
| mongo_user / residual_t1 | 1.059 | 30.754 | 488.188 | 8.378% |
| mongo_movie / residual_t1 | 1.053 | 30.676 | 488.332 | 8.380% |
| mongo_storage / residual_t1 | 3.849 | 87.589 | 157.799 | 2.708% |
| mongo_user / lead512_nop | 3.240 | 35.917 | 548.640 | 9.128% |
| mongo_movie / lead512_nop | 3.214 | 35.582 | 547.968 | 9.117% |
| mongo_storage / lead512_nop | 8.680 | 97.144 | 179.521 | 2.987% |
| mongo_user / lead512 | 1.384 | 31.435 | 492.500 | 8.421% |
| mongo_movie / lead512 | 1.388 | 31.230 | 493.214 | 8.433% |
| mongo_storage / lead512 | 3.824 | 86.670 | 156.832 | 2.682% |

Individual paired-log t95 reductions; negative means an increase. No multiplicity correction.

| Policy / control | Event | Reduction [95% CI] |
|---|---|---:|
| residual_t1 / split75 | Retired L2 | +3.501% [+2.248, +4.738] |
| residual_t1 / split75 | L2 code-read miss | -0.333% [-0.963, +0.292] |
| residual_t1 / split75 | I-cache stall cycles | +0.311% [-0.819, +1.429] |
| residual_t1 / split75 | ITLB walk-active cycles | +1.407% [-1.924, +4.628] |
| residual_t1 / split75 | Unknown-branch bubble cycles | -0.323% [-0.880, +0.230] |
| residual_t1 / split75 | Branch mispredictions | +0.073% [-0.821, +0.960] |
| residual_t1 / split75 | DSB uops | -2.961% [-9.523, +3.209] |
| residual_t1 / split75 | MITE uops | -0.567% [-0.976, -0.160] |
| residual_t1 / split75 | Retired L1I | -0.167% [-0.364, +0.029] |
| residual_t1 / split75 | DSB-to-MITE penalty cycles | -0.645% [-1.565, +0.266] |
| residual_t1 / split75 | I-cache stall periods | -0.566% [-0.721, -0.412] |
| residual_t1 / split75 | Speculative T1/T2 executions | -0.264% [-1.083, +0.549] |
| residual_t1 / split75 | L1D fill-buffer-full cycles | -2.468% [-9.020, +3.690] |
| lead512_nop / split75 | Retired L2 | -174.609% [-177.819, -171.437] |
| lead512_nop / split75 | L2 code-read miss | -13.676% [-13.717, -13.636] |
| lead512_nop / split75 | I-cache stall cycles | -39.518% [-40.111, -38.928] |
| lead512_nop / split75 | ITLB walk-active cycles | -99.785% [-102.600, -97.010] |
| lead512_nop / split75 | Unknown-branch bubble cycles | -31.845% [-33.323, -30.383] |
| lead512_nop / split75 | Branch mispredictions | -0.256% [-1.182, +0.663] |
| lead512_nop / split75 | DSB uops | +1.072% [-7.786, +9.203] |
| lead512_nop / split75 | MITE uops | -0.800% [-1.122, -0.479] |
| lead512_nop / split75 | Retired L1I | +0.176% [-0.501, +0.848] |
| lead512_nop / split75 | DSB-to-MITE penalty cycles | -0.606% [-1.507, +0.287] |
| lead512_nop / split75 | I-cache stall periods | +8.566% [+8.064, +9.066] |
| lead512_nop / split75 | L1D fill-buffer-full cycles | +7.586% [+0.690, +14.004] |
| lead512 / split75 | Retired L2 | -19.734% [-21.638, -17.860] |
| lead512 / split75 | L2 code-read miss | -0.989% [-1.873, -0.114] |
| lead512 / split75 | I-cache stall cycles | -2.133% [-3.408, -0.874] |
| lead512 / split75 | ITLB walk-active cycles | -5.621% [-7.417, -3.856] |
| lead512 / split75 | Unknown-branch bubble cycles | -3.794% [-4.124, -3.464] |
| lead512 / split75 | Branch mispredictions | +0.297% [-0.875, +1.454] |
| lead512 / split75 | DSB uops | -0.064% [-0.778, +0.644] |
| lead512 / split75 | MITE uops | -0.305% [-1.218, +0.599] |
| lead512 / split75 | Retired L1I | +0.985% [+0.332, +1.633] |
| lead512 / split75 | DSB-to-MITE penalty cycles | -0.268% [-1.357, +0.810] |
| lead512 / split75 | I-cache stall periods | +1.603% [+1.232, +1.973] |
| lead512 / split75 | Speculative T1/T2 executions | -3.756% [-4.163, -3.350] |
| lead512 / split75 | L1D fill-buffer-full cycles | -3.518% [-7.442, +0.261] |
| lead512 / lead512_nop | Retired L2 | +56.398% [+55.310, +57.460] |
| lead512 / lead512_nop | L2 code-read miss | +11.160% [+10.378, +11.936] |
| lead512 / lead512_nop | I-cache stall cycles | +26.796% [+25.854, +27.726] |
| lead512 / lead512_nop | ITLB walk-active cycles | +47.133% [+46.499, +47.759] |
| lead512 / lead512_nop | Unknown-branch bubble cycles | +21.276% [+20.367, +22.174] |
| lead512 / lead512_nop | Branch mispredictions | +0.551% [-0.368, +1.462] |
| lead512 / lead512_nop | DSB uops | -1.149% [-10.517, +7.425] |
| lead512 / lead512_nop | MITE uops | +0.491% [-0.407, +1.381] |
| lead512 / lead512_nop | Retired L1I | +0.810% [+0.058, +1.557] |
| lead512 / lead512_nop | DSB-to-MITE penalty cycles | +0.336% [-1.037, +1.690] |
| lead512 / lead512_nop | I-cache stall periods | -7.615% [-8.174, -7.060] |
| lead512 / lead512_nop | L1D fill-buffer-full cycles | -12.016% [-18.531, -5.859] |
| lead512 / residual_t1 | Retired L2 | -24.078% [-26.339, -21.858] |
| lead512 / residual_t1 | L2 code-read miss | -0.654% [-1.514, +0.199] |
| lead512 / residual_t1 | I-cache stall cycles | -2.452% [-3.297, -1.613] |
| lead512 / residual_t1 | ITLB walk-active cycles | -7.128% [-11.255, -3.154] |
| lead512 / residual_t1 | Unknown-branch bubble cycles | -3.459% [-4.261, -2.664] |
| lead512 / residual_t1 | Branch mispredictions | +0.224% [-0.521, +0.963] |
| lead512 / residual_t1 | DSB uops | +2.813% [-3.860, +9.058] |
| lead512 / residual_t1 | MITE uops | +0.260% [-0.610, +1.123] |
| lead512 / residual_t1 | Retired L1I | +1.150% [+0.519, +1.777] |
| lead512 / residual_t1 | DSB-to-MITE penalty cycles | +0.375% [-0.573, +1.315] |
| lead512 / residual_t1 | I-cache stall periods | +2.157% [+1.780, +2.532] |
| lead512 / residual_t1 | Speculative T1/T2 executions | -3.483% [-4.068, -2.901] |
| lead512 / residual_t1 | L1D fill-buffer-full cycles | -1.025% [-4.235, +2.086] |

## l1_screen

Raw Mongo3 counts/request, arithmetic mean of four trials.

| Event | split75 | extra_nop | extra_t1 | extra_it0 |
|---|---:|---:|---:|---:|
| Retired L2 | 2,051.607 | 2,066.026 | 2,069.967 | 2,102.803 |
| L2 code-read miss | 55,519.599 | 55,757.988 | 55,630.043 | 55,414.316 |
| I-cache stall cycles | 458,747.959 | 463,486.387 | 464,352.273 | 464,960.728 |
| ITLB walk-active cycles | 93,721.292 | 95,252.278 | 95,698.862 | 94,458.607 |
| Unknown-branch bubble cycles | 608,338.130 | 613,617.597 | 607,342.288 | 610,256.621 |
| Branch mispredictions | 19,760.747 | 19,855.677 | 19,838.031 | 19,851.759 |
| DSB uops | 1,414,076.358 | 1,354,725.504 | 1,356,006.505 | 1,363,210.981 |
| MITE uops | 1,072,245.614 | 1,074,776.234 | 1,076,705.244 | 1,072,738.658 |
| Retired L1I | 15,986.298 | 15,966.521 | 15,972.702 | 16,051.862 |
| DSB-to-MITE penalty cycles | 48,213.542 | 47,778.939 | 47,613.068 | 48,100.958 |
| I-cache stall periods | 28,658.540 | 28,680.101 | 28,662.506 | 28,955.689 |
| Late instruction prefetch | 0.000 | 0.000 | 0.000 | 25.319 |
| Speculative T1/T2 executions | 8,634.680 | 8,613.943 | 9,835.835 | 8,604.156 |
| L1D fill-buffer-full cycles | 14,771.950 | 14,387.508 | 14,368.500 | 14,737.334 |

Service MPKI uses retired user instructions from the same counter window. Speculative code-read requests and retired frontend miss events have different populations; neither is an exclusive measure of request waiting time. CPU shares are clean-ROI accounting ratios, not request-critical-path or Amdahl bounds.

| Service / policy | Retired L2 MPKI | Code-read MPKI | Service CPU us/request | Share of whole CPU |
|---|---:|---:|---:|---:|
| mongo_user / split75 | 1.095 | 30.850 | 488.048 | 8.365% |
| mongo_movie / split75 | 1.096 | 30.622 | 487.563 | 8.357% |
| mongo_storage / split75 | 3.840 | 87.744 | 157.500 | 2.700% |
| mongo_user / extra_nop | 1.113 | 31.163 | 489.581 | 8.345% |
| mongo_movie / extra_nop | 1.104 | 31.043 | 488.267 | 8.322% |
| mongo_storage / extra_nop | 3.922 | 87.771 | 158.248 | 2.697% |
| mongo_user / extra_t1 | 1.119 | 31.190 | 488.647 | 8.319% |
| mongo_movie / extra_t1 | 1.108 | 30.935 | 488.406 | 8.314% |
| mongo_storage / extra_t1 | 3.896 | 87.356 | 158.216 | 2.693% |
| mongo_user / extra_it0 | 1.142 | 30.960 | 490.384 | 8.387% |
| mongo_movie / extra_it0 | 1.116 | 30.704 | 489.143 | 8.366% |
| mongo_storage / extra_it0 | 3.934 | 87.115 | 158.510 | 2.711% |

Individual paired-log t95 reductions; negative means an increase. No multiplicity correction.

| Policy / control | Event | Reduction [95% CI] |
|---|---|---:|
| extra_nop / split75 | Retired L2 | -0.707% [-2.142, +0.708] |
| extra_nop / split75 | L2 code-read miss | -0.427% [-1.582, +0.714] |
| extra_nop / split75 | I-cache stall cycles | -1.030% [-1.528, -0.535] |
| extra_nop / split75 | ITLB walk-active cycles | -1.617% [-9.897, +6.040] |
| extra_nop / split75 | Unknown-branch bubble cycles | -0.868% [-1.594, -0.148] |
| extra_nop / split75 | Branch mispredictions | -0.481% [-1.116, +0.149] |
| extra_nop / split75 | DSB uops | +4.002% [-3.408, +10.881] |
| extra_nop / split75 | MITE uops | -0.236% [-0.661, +0.187] |
| extra_nop / split75 | Retired L1I | +0.125% [-0.556, +0.800] |
| extra_nop / split75 | DSB-to-MITE penalty cycles | +0.899% [-0.556, +2.332] |
| extra_nop / split75 | I-cache stall periods | -0.075% [-0.432, +0.281] |
| extra_nop / split75 | Speculative T1/T2 executions | +0.241% [-0.447, +0.924] |
| extra_nop / split75 | L1D fill-buffer-full cycles | +2.986% [-4.906, +10.284] |
| extra_t1 / split75 | Retired L2 | -0.902% [-2.569, +0.737] |
| extra_t1 / split75 | L2 code-read miss | -0.195% [-1.578, +1.168] |
| extra_t1 / split75 | I-cache stall cycles | -1.223% [-1.522, -0.925] |
| extra_t1 / split75 | ITLB walk-active cycles | -2.090% [-11.032, +6.133] |
| extra_t1 / split75 | Unknown-branch bubble cycles | +0.164% [-0.754, +1.074] |
| extra_t1 / split75 | Branch mispredictions | -0.392% [-1.657, +0.858] |
| extra_t1 / split75 | DSB uops | +3.917% [-3.512, +10.812] |
| extra_t1 / split75 | MITE uops | -0.415% [-1.428, +0.588] |
| extra_t1 / split75 | Retired L1I | +0.085% [-0.088, +0.258] |
| extra_t1 / split75 | DSB-to-MITE penalty cycles | +1.243% [-0.464, +2.922] |
| extra_t1 / split75 | I-cache stall periods | -0.013% [-0.373, +0.345] |
| extra_t1 / split75 | Speculative T1/T2 executions | -13.911% [-14.522, -13.302] |
| extra_t1 / split75 | L1D fill-buffer-full cycles | +3.038% [-2.558, +8.330] |
| extra_t1 / extra_nop | Retired L2 | -0.194% [-0.559, +0.170] |
| extra_t1 / extra_nop | L2 code-read miss | +0.231% [-0.100, +0.561] |
| extra_t1 / extra_nop | I-cache stall cycles | -0.191% [-0.966, +0.577] |
| extra_t1 / extra_nop | ITLB walk-active cycles | -0.465% [-2.525, +1.553] |
| extra_t1 / extra_nop | Unknown-branch bubble cycles | +1.024% [+0.306, +1.736] |
| extra_t1 / extra_nop | Branch mispredictions | +0.089% [-0.692, +0.864] |
| extra_t1 / extra_nop | DSB uops | -0.089% [-2.280, +2.056] |
| extra_t1 / extra_nop | MITE uops | -0.178% [-1.117, +0.752] |
| extra_t1 / extra_nop | Retired L1I | -0.040% [-0.625, +0.543] |
| extra_t1 / extra_nop | DSB-to-MITE penalty cycles | +0.348% [-0.659, +1.344] |
| extra_t1 / extra_nop | I-cache stall periods | +0.061% [-0.363, +0.483] |
| extra_t1 / extra_nop | Speculative T1/T2 executions | -14.186% [-14.688, -13.685] |
| extra_t1 / extra_nop | L1D fill-buffer-full cycles | +0.054% [-2.937, +2.958] |
| extra_it0 / split75 | Retired L2 | -2.508% [-3.826, -1.207] |
| extra_it0 / split75 | L2 code-read miss | +0.191% [-0.922, +1.292] |
| extra_it0 / split75 | I-cache stall cycles | -1.359% [-2.151, -0.572] |
| extra_it0 / split75 | ITLB walk-active cycles | -0.792% [-6.952, +5.013] |
| extra_it0 / split75 | Unknown-branch bubble cycles | -0.315% [-0.705, +0.073] |
| extra_it0 / split75 | Branch mispredictions | -0.461% [-1.633, +0.697] |
| extra_it0 / split75 | DSB uops | +3.451% [-1.964, +8.579] |
| extra_it0 / split75 | MITE uops | -0.046% [-0.337, +0.245] |
| extra_it0 / split75 | Retired L1I | -0.408% [-1.334, +0.509] |
| extra_it0 / split75 | DSB-to-MITE penalty cycles | +0.233% [-0.805, +1.261] |
| extra_it0 / split75 | I-cache stall periods | -1.036% [-1.409, -0.665] |
| extra_it0 / split75 | Speculative T1/T2 executions | +0.354% [-0.465, +1.167] |
| extra_it0 / split75 | L1D fill-buffer-full cycles | +0.305% [-1.846, +2.411] |
| extra_it0 / extra_nop | Retired L2 | -1.788% [-3.161, -0.434] |
| extra_it0 / extra_nop | L2 code-read miss | +0.616% [+0.484, +0.747] |
| extra_it0 / extra_nop | I-cache stall cycles | -0.325% [-1.557, +0.892] |
| extra_it0 / extra_nop | ITLB walk-active cycles | +0.811% [-4.739, +6.068] |
| extra_it0 / extra_nop | Unknown-branch bubble cycles | +0.548% [-0.252, +1.342] |
| extra_it0 / extra_nop | Branch mispredictions | +0.020% [-0.853, +0.884] |
| extra_it0 / extra_nop | DSB uops | -0.574% [-3.596, +2.360] |
| extra_it0 / extra_nop | MITE uops | +0.190% [-0.264, +0.642] |
| extra_it0 / extra_nop | Retired L1I | -0.534% [-0.842, -0.226] |
| extra_it0 / extra_nop | DSB-to-MITE penalty cycles | -0.672% [-1.816, +0.460] |
| extra_it0 / extra_nop | I-cache stall periods | -0.961% [-1.376, -0.548] |
| extra_it0 / extra_nop | Speculative T1/T2 executions | +0.114% [-0.233, +0.459] |
| extra_it0 / extra_nop | L1D fill-buffer-full cycles | -2.764% [-10.297, +4.255] |
| extra_it0 / extra_t1 | Retired L2 | -1.591% [-2.865, -0.333] |
| extra_it0 / extra_t1 | L2 code-read miss | +0.386% [-0.020, +0.789] |
| extra_it0 / extra_t1 | I-cache stall cycles | -0.134% [-0.646, +0.377] |
| extra_it0 / extra_t1 | ITLB walk-active cycles | +1.271% [-3.303, +5.642] |
| extra_it0 / extra_t1 | Unknown-branch bubble cycles | -0.480% [-1.633, +0.659] |
| extra_it0 / extra_t1 | Branch mispredictions | -0.069% [-1.103, +0.954] |
| extra_it0 / extra_t1 | DSB uops | -0.485% [-4.295, +3.187] |
| extra_it0 / extra_t1 | MITE uops | +0.368% [-0.523, +1.250] |
| extra_it0 / extra_t1 | Retired L1I | -0.494% [-1.292, +0.298] |
| extra_it0 / extra_t1 | DSB-to-MITE penalty cycles | -1.023% [-2.191, +0.131] |
| extra_it0 / extra_t1 | I-cache stall periods | -1.023% [-1.710, -0.340] |
| extra_it0 / extra_t1 | Speculative T1/T2 executions | +12.523% [+12.231, +12.813] |
| extra_it0 / extra_t1 | L1D fill-buffer-full cycles | -2.819% [-7.645, +1.791] |

## latency_screen

Raw Mongo3 counts/request, arithmetic mean of four trials.

| Event | original | split75 | extra_t1 | latency_t1 |
|---|---:|---:|---:|---:|
| Retired L2 | 5,472.722 | 2,058.521 | 2,081.412 | 2,063.406 |
| L2 code-read miss | 61,169.154 | 55,580.051 | 55,684.621 | 55,522.344 |
| I-cache stall cycles | 613,603.379 | 460,052.692 | 466,309.451 | 462,198.053 |
| ITLB walk-active cycles | 192,627.719 | 94,753.815 | 94,085.807 | 95,181.724 |
| Unknown-branch bubble cycles | 732,423.187 | 606,831.641 | 610,128.038 | 607,958.157 |
| Branch mispredictions | 19,804.512 | 19,829.219 | 19,848.424 | 19,788.764 |
| DSB uops | 1,382,681.627 | 1,387,341.160 | 1,388,880.908 | 1,393,793.350 |
| MITE uops | 1,063,082.881 | 1,069,607.147 | 1,074,615.785 | 1,074,630.826 |
| Retired L1I | 14,797.271 | 16,029.049 | 15,979.210 | 16,033.158 |
| DSB-to-MITE penalty cycles | 49,761.152 | 48,012.232 | 47,640.194 | 48,244.824 |
| I-cache stall periods | 24,380.352 | 28,724.733 | 28,686.519 | 28,780.387 |
| Late instruction prefetch | 0.000 | 0.000 | 0.000 | 0.000 |
| Speculative T1/T2 executions | 0.000 | 8,635.185 | 9,849.826 | 9,866.002 |
| L1D fill-buffer-full cycles | 14,733.901 | 15,399.410 | 15,306.184 | 15,456.822 |
| Frontend gaps >=128 cycles | 2,543.929 | 1,073.999 | 1,097.935 | 1,075.750 |

Service MPKI uses retired user instructions from the same counter window. Speculative code-read requests and retired frontend miss events have different populations; neither is an exclusive measure of request waiting time. CPU shares are clean-ROI accounting ratios, not request-critical-path or Amdahl bounds.

| Service / policy | Retired L2 MPKI | Code-read MPKI | Service CPU us/request | Share of whole CPU |
|---|---:|---:|---:|---:|
| mongo_user / original | 3.081 | 34.569 | 532.452 | 8.953% |
| mongo_movie / original | 3.056 | 33.873 | 532.341 | 8.951% |
| mongo_storage / original | 8.425 | 95.443 | 173.917 | 2.924% |
| mongo_user / split75 | 1.100 | 30.711 | 487.762 | 8.360% |
| mongo_movie / split75 | 1.081 | 30.465 | 487.609 | 8.358% |
| mongo_storage / split75 | 3.905 | 87.482 | 158.106 | 2.710% |
| mongo_user / extra_t1 | 1.102 | 30.688 | 488.516 | 8.373% |
| mongo_movie / extra_t1 | 1.093 | 30.511 | 488.319 | 8.370% |
| mongo_storage / extra_t1 | 3.957 | 87.247 | 158.596 | 2.718% |
| mongo_user / latency_t1 | 1.103 | 30.386 | 489.237 | 8.385% |
| mongo_movie / latency_t1 | 1.069 | 30.281 | 488.064 | 8.365% |
| mongo_storage / latency_t1 | 3.883 | 87.222 | 157.388 | 2.698% |

Individual paired-log t95 reductions; negative means an increase. No multiplicity correction.

| Policy / control | Event | Reduction [95% CI] |
|---|---|---:|
| split75 / original | Retired L2 | +62.385% [+62.030, +62.737] |
| split75 / original | L2 code-read miss | +9.136% [+8.415, +9.851] |
| split75 / original | I-cache stall cycles | +25.020% [+24.093, +25.936] |
| split75 / original | ITLB walk-active cycles | +50.812% [+48.623, +52.908] |
| split75 / original | Unknown-branch bubble cycles | +17.147% [+16.779, +17.513] |
| split75 / original | Branch mispredictions | -0.125% [-1.009, +0.751] |
| split75 / original | DSB uops | -0.323% [-1.882, +1.212] |
| split75 / original | MITE uops | -0.614% [-1.177, -0.054] |
| split75 / original | Retired L1I | -8.324% [-8.713, -7.936] |
| split75 / original | DSB-to-MITE penalty cycles | +3.514% [+3.131, +3.896] |
| split75 / original | I-cache stall periods | -17.820% [-18.480, -17.165] |
| split75 / original | L1D fill-buffer-full cycles | -4.523% [-8.134, -1.032] |
| split75 / original | Frontend gaps >=128 cycles | +57.782% [+56.974, +58.574] |
| extra_t1 / original | Retired L2 | +61.972% [+61.230, +62.700] |
| extra_t1 / original | L2 code-read miss | +8.963% [+7.995, +9.921] |
| extra_t1 / original | I-cache stall cycles | +24.002% [+22.966, +25.024] |
| extra_t1 / original | ITLB walk-active cycles | +51.159% [+50.121, +52.176] |
| extra_t1 / original | Unknown-branch bubble cycles | +16.697% [+16.216, +17.175] |
| extra_t1 / original | Branch mispredictions | -0.223% [-1.108, +0.655] |
| extra_t1 / original | DSB uops | -0.433% [-2.857, +1.933] |
| extra_t1 / original | MITE uops | -1.085% [-1.973, -0.205] |
| extra_t1 / original | Retired L1I | -7.989% [-8.580, -7.401] |
| extra_t1 / original | DSB-to-MITE penalty cycles | +4.263% [+3.882, +4.642] |
| extra_t1 / original | I-cache stall periods | -17.665% [-18.789, -16.551] |
| extra_t1 / original | L1D fill-buffer-full cycles | -3.983% [-9.187, +0.974] |
| extra_t1 / original | Frontend gaps >=128 cycles | +56.843% [+55.891, +57.776] |
| extra_t1 / split75 | Retired L2 | -1.098% [-3.193, +0.955] |
| extra_t1 / split75 | L2 code-read miss | -0.190% [-0.808, +0.424] |
| extra_t1 / split75 | I-cache stall cycles | -1.358% [-2.305, -0.419] |
| extra_t1 / split75 | ITLB walk-active cycles | +0.705% [-4.934, +6.042] |
| extra_t1 / split75 | Unknown-branch bubble cycles | -0.543% [-0.866, -0.221] |
| extra_t1 / split75 | Branch mispredictions | -0.097% [-0.665, +0.467] |
| extra_t1 / split75 | DSB uops | -0.110% [-1.244, +1.011] |
| extra_t1 / split75 | MITE uops | -0.468% [-0.838, -0.100] |
| extra_t1 / split75 | Retired L1I | +0.309% [-0.383, +0.996] |
| extra_t1 / split75 | DSB-to-MITE penalty cycles | +0.776% [+0.145, +1.404] |
| extra_t1 / split75 | I-cache stall periods | +0.132% [-0.422, +0.683] |
| extra_t1 / split75 | Speculative T1/T2 executions | -14.066% [-15.131, -13.011] |
| extra_t1 / split75 | L1D fill-buffer-full cycles | +0.517% [-3.111, +4.016] |
| extra_t1 / split75 | Frontend gaps >=128 cycles | -2.222% [-4.574, +0.076] |
| latency_t1 / original | Retired L2 | +62.301% [+61.663, +62.929] |
| latency_t1 / original | L2 code-read miss | +9.234% [+8.441, +10.020] |
| latency_t1 / original | I-cache stall cycles | +24.674% [+24.326, +25.022] |
| latency_t1 / original | ITLB walk-active cycles | +50.587% [+49.348, +51.796] |
| latency_t1 / original | Unknown-branch bubble cycles | +16.995% [+16.553, +17.434] |
| latency_t1 / original | Branch mispredictions | +0.080% [-0.867, +1.019] |
| latency_t1 / original | DSB uops | -0.794% [-3.355, +1.703] |
| latency_t1 / original | MITE uops | -1.086% [-1.992, -0.188] |
| latency_t1 / original | Retired L1I | -8.354% [-9.250, -7.465] |
| latency_t1 / original | DSB-to-MITE penalty cycles | +3.047% [+2.509, +3.582] |
| latency_t1 / original | I-cache stall periods | -18.049% [-19.200, -16.909] |
| latency_t1 / original | L1D fill-buffer-full cycles | -4.880% [-6.733, -3.060] |
| latency_t1 / original | Frontend gaps >=128 cycles | +57.712% [+56.830, +58.576] |
| latency_t1 / split75 | Retired L2 | -0.222% [-2.258, +1.773] |
| latency_t1 / split75 | L2 code-read miss | +0.108% [-0.714, +0.923] |
| latency_t1 / split75 | I-cache stall cycles | -0.461% [-1.558, +0.623] |
| latency_t1 / split75 | ITLB walk-active cycles | -0.458% [-3.304, +2.310] |
| latency_t1 / split75 | Unknown-branch bubble cycles | -0.184% [-1.027, +0.652] |
| latency_t1 / split75 | Branch mispredictions | +0.205% [-0.328, +0.735] |
| latency_t1 / split75 | DSB uops | -0.470% [-2.613, +1.628] |
| latency_t1 / split75 | MITE uops | -0.469% [-0.813, -0.127] |
| latency_t1 / split75 | Retired L1I | -0.028% [-1.111, +1.044] |
| latency_t1 / split75 | DSB-to-MITE penalty cycles | -0.484% [-1.372, +0.396] |
| latency_t1 / split75 | I-cache stall periods | -0.194% [-0.628, +0.238] |
| latency_t1 / split75 | Speculative T1/T2 executions | -14.254% [-14.589, -13.920] |
| latency_t1 / split75 | L1D fill-buffer-full cycles | -0.342% [-4.680, +3.816] |
| latency_t1 / split75 | Frontend gaps >=128 cycles | -0.165% [-1.530, +1.181] |
| latency_t1 / extra_t1 | Retired L2 | +0.866% [-0.402, +2.119] |
| latency_t1 / extra_t1 | L2 code-read miss | +0.298% [-1.075, +1.651] |
| latency_t1 / extra_t1 | I-cache stall cycles | +0.884% [-0.078, +1.837] |
| latency_t1 / extra_t1 | ITLB walk-active cycles | -1.172% [-5.672, +3.137] |
| latency_t1 / extra_t1 | Unknown-branch bubble cycles | +0.357% [-0.415, +1.123] |
| latency_t1 / extra_t1 | Branch mispredictions | +0.302% [-0.763, +1.356] |
| latency_t1 / extra_t1 | DSB uops | -0.359% [-1.858, +1.117] |
| latency_t1 / extra_t1 | MITE uops | -0.001% [-0.314, +0.311] |
| latency_t1 / extra_t1 | Retired L1I | -0.338% [-0.908, +0.229] |
| latency_t1 / extra_t1 | DSB-to-MITE penalty cycles | -1.270% [-1.968, -0.577] |
| latency_t1 / extra_t1 | I-cache stall periods | -0.327% [-0.843, +0.186] |
| latency_t1 / extra_t1 | Speculative T1/T2 executions | -0.165% [-0.836, +0.502] |
| latency_t1 / extra_t1 | L1D fill-buffer-full cycles | -0.863% [-7.338, +5.221] |
| latency_t1 / extra_t1 | Frontend gaps >=128 cycles | +2.012% [-1.057, +4.988] |

## Selected targets among remaining misses

Separate PEBS/LBR diagnostics; split instructions use the calibrated continuation-line model. Static selected-line membership does not prove a hint executed. Missing matching hints may be outside finite LBR history; observed retirement age is not issue-to-fetch lead.

| Policy / service | Main samples | On a selected target line | Matching hint in LBR | Matching hint age >=512 | Split instruction | Added stub |
|---|---:|---:|---:|---:|---:|---:|
| split75 / user-review-mongodb | 27,287 | 5.175% | 0.924% | 0.227% | 34.899% | 11.599% |
| split75 / movie-review-mongodb | 27,296 | 4.832% | 0.839% | 0.231% | 35.324% | 11.987% |
| lead512 / user-review-mongodb | 36,036 | 5.517% | 0.522% | 0.425% | 28.399% | 8.017% |
| lead512 / movie-review-mongodb | 36,359 | 5.380% | 0.459% | 0.355% | 28.518% | 8.177% |

## Residual retired-L2 samples on split75

Independent padding train/heldout captures. Denominator: all main-image samples. A sample near a taken-branch destination is not necessarily a branch instruction.

| Capture / service | Main samples | Within 64 B of prior taken target | Prior branch mispredicted | Added prefetch stub | Sample is a branch instruction |
|---|---:|---:|---:|---:|---:|
| train:user-review-mongodb | 28,011 | 88.687% | 27.525% | 12.545% | 13.341% |
| train:movie-review-mongodb | 26,848 | 89.552% | 25.752% | 12.161% | 12.925% |
| heldout:user-review-mongodb | 28,524 | 89.784% | 28.618% | 11.043% | 13.175% |
| heldout:movie-review-mongodb | 28,205 | 89.083% | 27.520% | 11.094% | 12.462% |

Existing-padding qualification: 34 targets; train coverage 2.601%, heldout 2.228%. Compiled: False. Train-only minimum was 5%; no endpoint measurement is inferred.

Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

## L1I-guided supplement: independent training and heldout captures

Both captures use the unchanged split75 binary. Retain all main-image samples in the coverage denominator, including split instructions and added stubs that the new selector cannot target. These are modeled paths, not observed prefetch acceptance or a prediction of endpoint speedup.

| Capture / service | Main samples | Within 64 B of prior taken target | Prior branch mispredicted | Eligible after exclusions | Split instruction excluded |
|---|---:|---:|---:|---:|---:|
| train:user-review-mongodb | 59,833 | 93.666% | 21.105% | 52.127% | 26.395% |
| train:movie-review-mongodb | 60,305 | 93.782% | 21.031% | 52.065% | 26.583% |
| heldout:user-review-mongodb | 61,750 | 93.589% | 21.218% | 51.723% | 26.824% |
| heldout:movie-review-mongodb | 61,085 | 93.760% | 21.486% | 52.180% | 26.537% |

Train-only selected hints: 256; train coverage 8.524%, heldout coverage 7.393%. The heldout capture did not select targets. Existing T1 targets remain unchanged. Incremental IT0/T1/NOP variants have identical layout and added target addresses; only the new-slot opcodes differ. There are no new call sites, jumps, or timing guards. The added instruction bytes can still change frontend work and cache layout versus split75.

## Long frontend-stall retargeting

The training event selects retired instructions after frontend delivery gaps of at least 128 cycles, not interrupted by a backend stall. It can include branch and translation effects; it is not a code-cache-miss event or a request critical-path measure. Only supplemental target displacements may change. Static call sites, hint counts per call, code layout and all original split75 T1 hints are preserved.

| Capture | Old supplemental target coverage | Retargeted coverage |
|---|---:|---:|
| train | 5.245% | 11.877% |
| heldout | 4.458% | 10.531% |

Changed displacements: 21. Compiled: True. Frozen train-only thresholds: coverage >=5% and improvement >=1.5 percentage points. No endpoint improvement is inferred from modeled coverage.

Both captures used the existing extra_t1 binary. Denominator: all main-image long-stall samples. Association with the preceding taken branch does not prove BTB absence, FDIP failure, or that branch recovery exclusively caused the entire interval.

| Capture / service | Main samples | Within 64 B of taken target | Prior taken branch mispredicted | Added stub |
|---|---:|---:|---:|---:|
| train:user-review-mongodb | 13,832 | 99.422% | 55.335% | 11.618% |
| train:movie-review-mongodb | 14,425 | 99.147% | 58.198% | 11.501% |
| heldout:user-review-mongodb | 14,430 | 99.293% | 56.341% | 11.906% |
| heldout:movie-review-mongodb | 14,370 | 99.102% | 57.022% | 10.974% |
