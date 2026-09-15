#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# TPC-H query loop against local Trino via CLI. Prints per-round wall time.
# Usage: run_tpch_loop.sh <rounds> [schema=sf10]
set -e
cd "$(dirname "$0")"
ROUNDS=${1:-3}
SCHEMA=${2:-sf10}
CLI=trino-cli-419-executable.jar
JAVA="${TRINO_JAVA:-${JDK}/bin/java}"

# Q1, Q3, Q6, Q12, Q14-style aggregation/join queries over tpch connector
QF=/tmp/tpch_queries.sql
cat > $QF << 'EOF'
SELECT returnflag, linestatus, sum(quantity), sum(extendedprice), avg(discount), count(*) FROM tpch.SCHEMA.lineitem WHERE shipdate <= DATE '1998-09-02' GROUP BY returnflag, linestatus;
SELECT l.orderkey, sum(l.extendedprice*(1-l.discount)) rev, o.orderdate FROM tpch.SCHEMA.customer c JOIN tpch.SCHEMA.orders o ON c.custkey=o.custkey JOIN tpch.SCHEMA.lineitem l ON l.orderkey=o.orderkey WHERE c.mktsegment='BUILDING' AND o.orderdate < DATE '1995-03-15' AND l.shipdate > DATE '1995-03-15' GROUP BY l.orderkey, o.orderdate ORDER BY rev DESC LIMIT 10;
SELECT sum(extendedprice*discount) FROM tpch.SCHEMA.lineitem WHERE shipdate >= DATE '1994-01-01' AND shipdate < DATE '1995-01-01' AND discount BETWEEN 0.05 AND 0.07 AND quantity < 24;
SELECT l.shipmode, sum(CASE WHEN o.orderpriority IN ('1-URGENT','2-HIGH') THEN 1 ELSE 0 END) hi, count(*) FROM tpch.SCHEMA.orders o JOIN tpch.SCHEMA.lineitem l ON o.orderkey=l.orderkey WHERE l.shipmode IN ('MAIL','SHIP') AND l.receiptdate >= DATE '1994-01-01' AND l.receiptdate < DATE '1995-01-01' GROUP BY l.shipmode;
SELECT 100.0*sum(CASE WHEN p.type LIKE 'PROMO%%' THEN l.extendedprice*(1-l.discount) ELSE 0 END)/sum(l.extendedprice*(1-l.discount)) FROM tpch.SCHEMA.lineitem l JOIN tpch.SCHEMA.part p ON l.partkey=p.partkey WHERE l.shipdate >= DATE '1995-09-01' AND l.shipdate < DATE '1995-10-01';
EOF
sed -i "s/SCHEMA/${SCHEMA}/g" $QF

for r in $(seq 1 "$ROUNDS"); do
  t0=$(date +%s.%N)
  $JAVA -jar $CLI --server http://localhost:8090 -f $QF --output-format NULL > /dev/null 2>&1
  t1=$(date +%s.%N)
  echo "round $r elapsed $(python3 -c "print(f'{$t1-$t0:.2f}')")s"
done
