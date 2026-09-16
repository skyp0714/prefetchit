#!/usr/bin/env bash
# WordPress: finish the install if the front page still redirects, then measure a real page render
set -u
until grep -q DSBDSO_DONE /tmp/dsb_dso.log; do sleep 15; done
S=ps101899; OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/wordpress_phpfpm
echo $S | sudo -S systemctl is-active php8.3-fpm >/dev/null || { echo $S | sudo -S systemctl restart php8.3-fpm; sleep 2; }
echo $S | sudo -S ln -sf /etc/nginx/sites-available/wordpress /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload; sleep 1
curl -sI http://localhost:8081/ | grep -iE "^HTTP|^location" | tr -d '\r'
curl -s -o /dev/null -w "install step2 %{http_code}\n" -d "weblog_title=Bench&user_name=admin&admin_password=Adminpass123%21&admin_password2=Adminpass123%21&pw_weak=on&admin_email=a%40b.c&blog_public=0&Submit=Install+WordPress&language=" "http://localhost:8081/wp-admin/install.php?step=2"
curl -sI http://localhost:8081/ | grep -iE "^HTTP|^location" | tr -d '\r'
curl -s http://localhost:8081/ | grep -o "<title>[^<]*" | head -1
# if still redirecting to install, give up; else measure
if curl -sI http://localhost:8081/ | grep -qi "install.php"; then echo "WORDPRESS: install did not complete"; else
  for p in $(pgrep -f "php-fpm: pool www"); do echo $S | sudo -S taskset -cp 72-79 $p > /dev/null; done
  URL="http://localhost:8081/?p=1"; curl -s -o /dev/null -w "post page %{http_code} %{size_download}B\n" $URL
  taskset -c 80-83 wrk -t4 -c32 -d15s $URL > $OUT/warmup.log 2>&1
  perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 72-79 -- taskset -c 80-83 wrk -t4 -c32 -d60s $URL > $OUT/wrk.log 2>&1
  python3 - $OUT/perf.csv $OUT/wrk.log <<'PY'
import csv,re,sys
perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
w=open(log).read(); rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w)
print(f"WORDPRESS RESULT4 (post page): rps={rps.group(1) if rps else 'n/a'} non2xx={bad.group(1) if bad else 0} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G")
PY
fi
echo $S | sudo -S rm -f /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload 2>/dev/null
echo WP4_DONE
