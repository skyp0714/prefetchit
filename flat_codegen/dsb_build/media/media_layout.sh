#!/usr/bin/env bash
# Partial interleaving as an MPKI knob: the target service shares GROUP_CORES with SHARE_WITH, everything else gets the rest.
# Usage: media_layout.sh "movie-id-service compose-review-service" 0-1 2-31
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
GROUP="$1"; GC="$2"; REST="$3"
for c in $(docker ps --format '{{.Names}}' | grep '^mediamicroservices'); do
  hit=0; for g in $GROUP; do [[ $c == mediamicroservices-$g-1 ]] && hit=1; done
  [[ $hit == 1 ]] && docker update --cpuset-cpus $GC $c > /dev/null || docker update --cpuset-cpus $REST $c > /dev/null
done
echo "group [$GROUP] on $GC, the rest on $REST"
