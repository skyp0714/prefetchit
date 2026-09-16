CREATE TABLE t ENGINE = Memory AS SELECT number AS id, intHash64(number) % 1000000 AS k, toString(intHash64(number*7)) AS s, rand() % 100 AS v, toDate('2020-01-01') + number % 1000 AS d FROM numbers(40000000);
SELECT k % 1000 AS g, count(), sum(v), avg(v), uniq(s) FROM t GROUP BY g ORDER BY g LIMIT 5;
SELECT d, count(), sumIf(v, v > 50) FROM t GROUP BY d ORDER BY count() DESC LIMIT 5;
SELECT a.k, count() FROM t a INNER JOIN (SELECT k FROM t WHERE v = 7 LIMIT 500000) b ON a.k = b.k GROUP BY a.k ORDER BY count() DESC LIMIT 5;
SELECT length(s), count() FROM t WHERE s LIKE '%77%' GROUP BY length(s) ORDER BY count() DESC LIMIT 5;
SELECT quantile(0.9)(v), median(v), max(k) FROM t;
