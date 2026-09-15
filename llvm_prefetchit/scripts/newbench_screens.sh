#!/usr/bin/env bash
# L2I MPKI screens for never-tested workload candidates.
# Each screen: service pinned to SERVER_CORES, load from CLIENT_CORES,
# perf stat on the server cores mid-run. One row per candidate.
set -uo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
NB="${ROOT}/llvm_prefetchit/results/paper_goal_20260815/newbench"
SERVER_CORES="${SERVER_CORES:-1-8}"
CLIENT_CORES="${CLIENT_CORES:-31-50}"
DURATION="${DURATION:-40}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
CSV="${NB}/screen.csv"
mkdir -p "${NB}"
[[ -s "${CSV}" ]] || echo 'workload,throughput,instructions,cycles,l2i_misses,l2i_mpki,ipc' > "${CSV}"

record() {
  local name="$1" thr="$2" pf="$3"
  python3 - "${CSV}" "${name}" "${thr}" "${pf}" <<'PY'
import csv, sys
out, name, thr, pf = sys.argv[1:]
ev = {}
for row in csv.reader(open(pf)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
i, c, m = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
csv.writer(open(out, "a", newline="")).writerow(
    [name, thr, int(i), int(c), int(m),
     f"{1000*m/i if i else 0:.4f}", f"{i/c if c else 0:.4f}"])
PY
}

screen_mariadb() {
  grep -q '^mariadb_slap,' "${CSV}" && return
  # mariadb service is system-managed (not core-pinned); measure its PIDs' cores
  # via system-wide -C is wrong for unpinned server -> pin via cgroup is overkill
  # for a screen: measure the mysqld PID directly.
  local pid
  pid="$(pgrep -o mariadbd || pgrep -o mysqld)"
  [[ -z "${pid}" ]] && { echo "[skip] mariadb not running"; return; }
  sudo -n taskset -c "${CLIENT_CORES}" mysqlslap --create-schema=slap_screen \
    --auto-generate-sql --auto-generate-sql-load-type=mixed \
    --concurrency=32 --iterations=1 --number-of-queries=2000000 \
    > "${NB}/mariadb_slap.log" 2>&1 &
  local cpid=$!
  sleep 3
  perf stat -x, -o "${NB}/mariadb.perf.csv" -p "${pid}" \
    -e instructions,cycles,"${EVENT}" -- sleep "${DURATION}" 2>/dev/null
  kill "${cpid}" 2>/dev/null; wait "${cpid}" 2>/dev/null
  record mariadb_slap "c32_mixed" "${NB}/mariadb.perf.csv"
  echo "[done] mariadb"
}

screen_node() {
  grep -q '^node_http,' "${CSV}" && return
  taskset -c "${SERVER_CORES}" node "${NB}/node_server.js" > "${NB}/node_server.log" 2>&1 &
  local spid=$!
  sleep 2
  taskset -c "${CLIENT_CORES}" python3 "${NB}/http_load.py" 18080 64 "$((DURATION + 10))" \
    > "${NB}/node_client.log" 2>&1 &
  local cpid=$!
  sleep 5
  perf stat -x, -o "${NB}/node.perf.csv" -p "${spid}" \
    -e instructions,cycles,"${EVENT}" -- sleep "${DURATION}" 2>/dev/null
  wait "${cpid}"
  local qps; qps="$(grep -oP 'qps=\K[\d.]+' "${NB}/node_client.log")"
  kill "${spid}" 2>/dev/null
  record node_http "${qps:-0}" "${NB}/node.perf.csv"
  echo "[done] node qps=${qps}"
}

screen_cassandra() {
  grep -q '^cassandra_stress,' "${CSV}" && return
  local CASS="${ROOT}/benchmarks/dcperf/benchmarks/django_workload/apache-cassandra"
  # dedicated instance on a scratch data dir
  local cdata="${NB}/cassandra_data"
  export CASSANDRA_HOME="${CASS}"
  export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
  pgrep -f 'CassandraDaemon' >/dev/null && { echo "[skip] cassandra already running"; return; }
  mkdir -p "${cdata}"
  taskset -c "${SERVER_CORES}" env JVM_OPTS="-Dcassandra.storagedir=${cdata}" \
    "${CASS}/bin/cassandra" -R -f > "${NB}/cassandra_server.log" 2>&1 &
  local spid=$!
  for _ in $(seq 1 60); do
    grep -q "state jump to NORMAL\|Starting listening for CQL" "${NB}/cassandra_server.log" 2>/dev/null && break
    sleep 2
  done
  sleep 5
  # write a seed dataset first so mixed reads hit existing keys
  taskset -c "${CLIENT_CORES}" env JAVA_HOME="${JAVA_HOME}" \
    "${CASS}/tools/bin/cassandra-stress" write n=200000 -rate threads=16 \
    > "${NB}/cassandra_seed.log" 2>&1
  taskset -c "${CLIENT_CORES}" env JAVA_HOME="${JAVA_HOME}" \
    "${CASS}/tools/bin/cassandra-stress" mixed 'ratio(write=1,read=3)' \
    duration=$((DURATION + 20))s -pop 'dist=UNIFORM(1..200000)' -rate threads=32 \
    > "${NB}/cassandra_stress.log" 2>&1 &
  local cpid=$!
  sleep 15
  local jpid
  jpid="$(pgrep -f 'org.apache.cassandra.service.CassandraDaemon' | head -1)"
  perf stat -x, -o "${NB}/cassandra.perf.csv" -p "${jpid}" \
    -e instructions,cycles,"${EVENT}" -- sleep "${DURATION}" 2>/dev/null
  kill "${cpid}" 2>/dev/null; wait "${cpid}" 2>/dev/null
  local thr; thr="$(grep -oP 'Op rate\s*:\s*\K[\d,]+' "${NB}/cassandra_stress.log" | tail -1 | tr -d ,)"
  kill "${spid}" 2>/dev/null
  record cassandra_stress "${thr:-0}" "${NB}/cassandra.perf.csv"
  echo "[done] cassandra thr=${thr}"
}

case "${1:-all}" in
  mariadb)   screen_mariadb ;;
  node)      screen_node ;;
  cassandra) screen_cassandra ;;
  all)       screen_mariadb; screen_node; screen_cassandra ;;
esac
column -t -s, "${CSV}"
