# shared settings for the media (mediaMicroservices) capacity experiments — alone regime, C6 off on the target service's cores
MM=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/mediaMicroservices; W=$MM/../wrk2/wrk
DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; MD=$DB/media; R18=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
SVC=${SVC:-movie-id-service}; SVCBIN=${SVCBIN:-MovieIdService}; OUTPFX=${OUTPFX:-mid}; CONT=mediamicroservices-$SVC-1
LUA=${LUA:-$R18/media_compose_review.lua}; WRK_URL=${WRK_URL:-http://localhost:8080/wrk2-api/review/compose}; RATE=${RATE:-2000}; CONN=${CONN:-64}
SVC_CORES=${SVC_CORES:-30-31}     # the target service alone on its own cores (screen: movie-id 2 cores at 23% util)
POOL=${POOL:-0-29}                # everything else
CL_CORES=${CL_CORES:-32-35}       # wrk2
cstate() { local mode=$1 cc; for cc in $(python3 -c "import re;print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)','$SVC_CORES') for i in range(int(a),int(b or a)+1)))"); do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pin_all() { local c; for c in $(docker ps --format '{{.Names}}' | grep '^mediamicroservices'); do [[ $c == $CONT ]] && docker update --cpuset-cpus $SVC_CORES $c > /dev/null || docker update --cpuset-cpus $POOL $c > /dev/null; done; }
svc_pid() { docker inspect -f '{{.State.Pid}}' $CONT; }
