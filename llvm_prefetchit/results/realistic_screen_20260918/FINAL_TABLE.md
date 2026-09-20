# Realistic-setting screen — final table (pinned cores, high-MPKI operating point; cause from the C6-off / one-core diagnostics)

| workload | realistic point (pinned) | L2I MPKI (user) | IPC | dominant cause |
|---|---|---:|---:|---|
| μSuite Router midtier | 1k qps, 4 cores, 3–8% util | 110.28 | 0.22 | cold (C6 wake) (C6 off 0.1, 1 core 0.9) |
| μSuite Router leaf | 1k qps, 4 cores, 3–8% util | 55.05 | 0.43 | cold (C6 wake) (C6 off 0.1, 1 core 1.0) |
| socialnetwork/user-timeline-redis-1 | 1 core(s), 6000 req/s, 12% util | 48.18 | 0.48 | n.d. |
| mediamicroservices/review-storage-mongodb-1 | 1 core(s), 2000 req/s, 15% util | 41.70 | 0.54 | cold (C6 wake) (C6 off 0.3) |
| socialnetwork/url-shorten-mongodb-1 | 1 core(s), 6000 req/s, 12% util | 40.45 | 0.52 | cold (C6 wake) (C6 off 0.8) |
| socialnetwork/social-graph-service-1 | 1 core(s), 6000 req/s, 8% util | 31.72 | 0.63 | cold (C6 wake) (C6 off 0.1) |
| socialnetwork/user-timeline-mongodb-1 | 1 core(s), 6000 req/s, 16% util | 28.11 | 0.76 | cold (C6 wake) (C6 off 1.5) |
| mediamicroservices/review-storage-service-1 | 1 core(s), 2000 req/s, 21% util | 23.51 | 0.73 | cold (C6 wake) (C6 off 0.1) |
| PostgreSQL 16 TPC-B | 4 backends on 4 cores, 28% util | 18.53 | 0.86 | cold (C6 wake): C6 off → 0.06; backends pinned → 3.9 |
| socialnetwork/post-storage-mongodb-1 | 1 core(s), 6000 req/s, 33% util | 18.31 | 0.70 | cold (C6 wake) (C6 off 2.3) |
| socialnetwork/home-timeline-redis-1 | 1 core(s), 6000 req/s, 26% util | 14.62 | 0.46 | cold (C6 wake) (C6 off 0.2) |
| socialnetwork/user-mention-service-1 | 1 core(s), 6000 req/s, 6% util | 14.50 | 0.87 | cold (C6 wake) (C6 off 0.3) |
| MariaDB 10.11 oltp_read_write (durable) | 4 threads on 4 cores, 40% util | 11.69 | 1.27 | cold (C6 wake) (C6 off 0.87, 1 core 1.07) |
| socialnetwork/url-shorten-service-1 | 1 core(s), 6000 req/s, 6% util | 11.28 | 1.11 | cold (C6 wake) (C6 off 0.2) |
| hotelreservation/recommendation-1 | 1 core(s), 3000 req/s, 17% util | 9.08 | 1.28 | cold (C6 wake) (C6 off 0.1) |
| MariaDB oltp_read_only (durable) | 4 threads on 4 cores, 42% util | 8.76 | 1.54 | same mechanism as read-write (not separately diagnosed) |
| CloudSuite web-serving | scale50, 4 cores, 15% util | 7.29 | 1.20 | mixed (cold 32% / capacity 68%) (at scale50: 7.29 → 4.98) |
| dacapo/tomcat | 4 pinned cores, JDK 21, 8 GB heap | 4.88 | 1.38 | capacity (C6 off 3.0, 1 core 3.9; 8 cores 10.8) |
| mediamicroservices/movie-id-service-1 | 1 core(s), 2000 req/s, 44% util | 4.83 | 0.95 | capacity / interleaving (survives C6 off) (C6 off 4.9) |
| mediamicroservices/compose-review-service-1 | 2 core(s), 2000 req/s, 68% util | 4.81 | 0.99 | capacity / interleaving (survives C6 off) (C6 off 3.8) |
| hotelreservation/geo-1 | 1 core(s), 3000 req/s, 29% util | 4.64 | 1.54 | cold (C6 wake) (C6 off 0.1) |
| CloudSuite web-search | w25, 4 cores, 4% util | 4.44 | 1.59 | capacity (at w50: 3.42 → 2.54) |
| hotelreservation/profile-1 | 1 core(s), 3000 req/s, 33% util | 4.26 | 1.62 | cold (C6 wake) (C6 off 0.3) |
| mediamicroservices/user-review-mongodb-1 | 1 core(s), 2000 req/s, 47% util | 3.99 | 1.86 | mixed (cold+capacity) (C6 off 1.4) |
| hotelreservation/search-1 | 2 core(s), 3000 req/s, 33% util | 3.98 | 1.61 | cold (C6 wake) (C6 off 0.4) |
| CloudSuite data-serving | rps5000, 4 cores, 26% util | 3.85 | 0.78 | capacity (at rps10000: 2.95 → 2.07) |
| mediamicroservices/movie-review-mongodb-1 | 1 core(s), 2000 req/s, 48% util | 3.84 | 1.78 | mixed (cold+capacity) (C6 off 1.4) |
| dacapo/cassandra | 4 pinned cores, JDK 21, 8 GB heap | 3.32 | 1.30 | capacity (C6 off 3.2, 1 core 22.5; 8 cores 2.4) |
| mediamicroservices/text-service-1 | 1 core(s), 2000 req/s, 11% util | 3.31 | 1.35 | cold (C6 wake) (C6 off 0.8) |
| mediamicroservices/unique-id-service-1 | 1 core(s), 2000 req/s, 14% util | 3.05 | 1.38 | cold (C6 wake) (C6 off 0.7) |
| dacapo/spring | 4 pinned cores, JDK 21, 8 GB heap | 2.75 | 1.85 | capacity (C6 off 2.9, 1 core 3.8; 8 cores 3.0) |
| dacapo/tradesoap | 4 pinned cores, JDK 21, 8 GB heap | 2.58 | 2.17 | mixed (cold+capacity) (C6 off 1.2, 1 core 0.8; 8 cores 3.0) |
| mediamicroservices/nginx-web-server-1 | 1 core(s), 2000 req/s, 46% util | 2.53 | 1.22 | capacity / interleaving (survives C6 off) (C6 off 3.6) |
| dacapo/avrora | 4 pinned cores, JDK 21, 8 GB heap | 2.49 | 1.31 | cold (C6 wake) (C6 off 0.0, 1 core 0.0; 8 cores 84.1) |
| mediamicroservices/user-review-service-1 | 1 core(s), 2000 req/s, 35% util | 2.42 | 1.06 | cold (C6 wake) (C6 off 0.7) |
| dacapo/kafka | 4 pinned cores, JDK 21, 8 GB heap | 2.41 | 1.30 | n.d.; 8 cores 3.0 |
| mediamicroservices/rating-service-1 | 1 core(s), 2000 req/s, 30% util | 2.30 | 1.13 | capacity / interleaving (survives C6 off) (C6 off 2.2) |
| mediamicroservices/movie-review-service-1 | 1 core(s), 2000 req/s, 34% util | 2.17 | 1.06 | cold (C6 wake) (C6 off 0.6) |
| dacapo/jme | 4 pinned cores, JDK 21, 8 GB heap | 2.16 | 1.74 | cold (C6 wake) (C6 off 0.4, 1 core 0.7; 8 cores 2.1) |
| socialnetwork/compose-post-service-1 | 1 core(s), 6000 req/s, 17% util | 1.95 | 1.42 | mixed (cold+capacity) (C6 off 1.0) |
| renaissance/dotty | 4 pinned cores, JDK 21, 8 GB heap | 1.87 | 1.76 | capacity (C6 off 1.9, 1 core 3.9; 8 cores 1.8) |
| socialnetwork/nginx-thrift-1 | 12 core(s), 6000 req/s, 88% util | 1.31 | 1.25 | capacity / interleaving (survives C6 off) (C6 off 1.2) |
| hotelreservation/rate-1 | 2 core(s), 3000 req/s, 39% util | 1.30 | 2.54 | cold (C6 wake) (C6 off 0.2) |
| CloudSuite data-caching | rps100000, 4 cores, 35% util | 1.28 | 0.89 | n.d. at this point; at rps200000 the misses are gone anyway (0.05 → 0.04) — low-load cold-wake regime |
| hotelreservation/frontend-1 | 2 core(s), 3000 req/s, 39% util | 1.25 | 1.36 | mixed (cold+capacity) (C6 off 0.5) |
| renaissance/finagle-chirper | 4 pinned cores, JDK 21, 8 GB heap | 1.18 | 2.07 | capacity (C6 off 1.2, 1 core 0.9; 8 cores 1.3) |
| mediamicroservices/user-service-1 | 1 core(s), 2000 req/s, 18% util | 1.18 | 1.50 | capacity / interleaving (survives C6 off) (C6 off 1.1) |
| dacapo/tradebeans | 4 pinned cores, JDK 21, 8 GB heap | 1.17 | 2.72 | cold (C6 wake) (C6 off 0.1, 1 core 0.1; 8 cores 1.4) |
| renaissance/log-regression | 4 pinned cores, JDK 21, 8 GB heap | 1.16 | 2.26 | capacity (C6 off 0.8, 1 core 1.0; 8 cores 1.5) |
| socialnetwork/user-timeline-service-1 | 1 core(s), 6000 req/s, 27% util | 1.15 | 1.93 | capacity / interleaving (survives C6 off) (C6 off 1.1) |
