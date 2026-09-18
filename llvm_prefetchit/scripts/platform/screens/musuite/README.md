# μSuite (wenischlab/MicroSuite) on this host — 2026-09-17
Build (`musuite_build.sh`): distro gRPC 1.51 / protobuf 3.21 / OpenBLAS (MKL cblas calls replaced), `-include cstdint`, `-std=c++17`,
`-Wl,--copy-dt-needed-entries`, `boost/core/noncopyable.hpp` added to the circular-buffer headers. Recommend's leaf (cf_server) does not build
against mlpack 4 (μSuite targets mlpack 2.2.5). HDSearch mid-tier needs the patched FLANN bundled in `src/HDSearch/mid_tier_service`
(CMake: `add_library(... SHARED "")` → give it `empty.cpp`; install to `MicroSuite/flann_local`).
Datasets: mirror `http://akshithasriraman.eecs.umich.edu/dataset/` works over plain HTTP (TLS cert broken, no index listing):
HDSearch/image_feature_vectors.dat (2.8 GB), SetAlgebra/wordIDs_mapped_to_posting_lists.txt (11.4 GB; a 1 GB prefix suffices),
Recommend/user_to_movie_ratings.csv (0.7 GB). Query sets are not on the mirror — generated from the datasets (see chat log / generator in RESULTS).
Screen: `musuite_screen.sh SERVICE OUTCSV QPS` (shared 0-42 vs isolated 36-39, leaf and mid-tier measured), `musuite_chain.sh` adds the DSB noise loop.

## Router static A/B (2026-09-17 22:07, `router_ab.sh` + `build_router_variants.sh`)
seq D=4 KB K=40 on the app binaries: leaf 0.988x (MPKI 29.3→29.2), mid-tier 0.984x (45.9→45.3) isolated; shared within ±2% of the NOP twins.
prefetchit0/1 = twins. The misses live in the prebuilt gRPC/protobuf/libstdc++ shared libraries, not in the app TUs; `router_dso.sh ARM` gives the
per-DSO L2I-miss breakdown. Cold-path variants (`cold`, `cold_seq` + twins) are built; `chain_router_cold.sh` runs their A/B (deferred, low priority).
