#!/usr/bin/env bash
set -u
until grep -q DSBDBG2_DONE /tmp/dsb_debug2.log; do sleep 10; done
S=ps101899; OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/wordpress_phpfpm
curl -s -o /dev/null -w "install POST %{http_code}\n" -d "weblog_title=Bench&user_name=admin&admin_password=Adminpass123%21&admin_password2=Adminpass123%21&pw_weak=on&admin_email=admin%40example.com&blog_public=0&Submit=Install+WordPress&language=" "http://localhost:8082/wp-admin/install.php?step=2"
echo $S | sudo -S mysql -e "select count(*) as wp_tables from information_schema.tables where table_schema='wordpress'" | tail -1
curl -sI http://localhost:8082/ | grep -iE "^HTTP|^location" | tr -d '\r'
curl -s -o /dev/null -w "post page %{http_code} %{size_download}B\n" "http://localhost:8082/?p=1"
for p in $(pgrep -f "php-fpm: pool www"); do echo $S | sudo -S taskset -cp 72-79 $p > /dev/null; done
for u in "/" "/?p=1"; do
  URL="http://localhost:8082$u"; tag=$( [[ "$u" == "/" ]] && echo front || echo post )
  taskset -c 80-83 wrk -t4 -c32 -d15s $URL > $OUT/warmup_$tag.log 2>&1
  perf stat -x, -o $OUT/perf_$tag.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 72-79 -- taskset -c 80-83 wrk -t4 -c32 -d60s $URL > $OUT/wrk_$tag.log 2>&1
  python3 - $OUT/perf_$tag.csv $OUT/wrk_$tag.log $tag <<'PY'
import csv,re,sys
perf,log,tag=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
w=open(log).read(); rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w)
print(f"WORDPRESS RESULT5 ({tag}): rps={rps.group(1) if rps else 'n/a'} non2xx={bad.group(1) if bad else 0} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G")
PY
done
echo WP5_DONE
