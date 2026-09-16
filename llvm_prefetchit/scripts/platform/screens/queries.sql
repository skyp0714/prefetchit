SELECT k % 10000 AS g, count(), sum(v), avg(v), uniq(s) FROM hits GROUP BY g ORDER BY g LIMIT 10
SELECT d, count(), sumIf(v, v > 50) FROM hits GROUP BY d ORDER BY count() DESC LIMIT 10
SELECT length(s), count() FROM hits WHERE s LIKE '%77%' GROUP BY length(s) ORDER BY count() DESC LIMIT 10
SELECT quantile(0.9)(v), median(v), max(k), min(r) FROM hits WHERE k < 1000000
SELECT a.k, count() FROM hits a INNER JOIN (SELECT k FROM hits WHERE v = 7 LIMIT 2000000) b ON a.k = b.k GROUP BY a.k ORDER BY count() DESC LIMIT 10
SELECT toStartOfMonth(d) m, uniqExact(k), count() FROM hits GROUP BY m ORDER BY m LIMIT 40
