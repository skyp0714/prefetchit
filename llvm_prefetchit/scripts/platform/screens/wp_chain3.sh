#!/usr/bin/env bash
set -u
until grep -q DSB4_DONE /tmp/dsb4.log; do sleep 15; done
S=ps101899
echo $S | sudo -S apparmor_parser -C -r /etc/apparmor.d/php-fpm 2>&1 | tail -1; echo "php-fpm profile set to complain"
echo $S | sudo -S systemctl restart php8.3-fpm; sleep 3; echo "php-fpm: $(systemctl is-active php8.3-fpm)"
echo $S | sudo -S ln -sf /etc/nginx/sites-available/wordpress /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload; sleep 1
curl -s -o /dev/null -w "front %{http_code}\n" http://localhost:8081/
curl -s -o /dev/null -d "weblog_title=Bench&user_name=admin&admin_password=Adminpass123!&admin_password2=Adminpass123!&pw_weak=on&admin_email=a@b.c&blog_public=0" "http://localhost:8081/wp-admin/install.php?step=2"
curl -s -o /dev/null -w "front after install %{http_code}\n" http://localhost:8081/; curl -s http://localhost:8081/ | grep -o "<title>[^<]*" | head -1
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/wordpress_phpfpm
for p in $(pgrep -f "php-fpm: pool www"); do echo $S | sudo -S taskset -cp 72-79 $p > /dev/null; done
taskset -c 80-83 wrk -t4 -c32 -d15s http://localhost:8081/ > $OUT/warmup.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 72-79 -- taskset -c 80-83 wrk -t4 -c32 -d60s http://localhost:8081/ > $OUT/wrk.log 2>&1
python3 - $OUT/perf.csv $OUT/wrk.log <<'PY'
import csv,re,sys
perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
w=open(log).read(); rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w)
print(f"WORDPRESS RESULT3: rps={rps.group(1) if rps else 'n/a'} non2xx={bad.group(1) if bad else 0} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G")
PY
echo $S | sudo -S rm -f /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload 2>/dev/null
echo WP3_DONE
