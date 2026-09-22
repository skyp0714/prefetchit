#!/usr/bin/env bash
# WordPress (Ubuntu package) on nginx + php-fpm 8.3 + MariaDB; wrk load on the front page & posts; perf stat on php-fpm workers
set -u
until grep -q APT_DC_DONE /tmp/apt_dc.log; do sleep 15; done
dpkg -l wordpress php-fpm php-mysql nginx 2>/dev/null | awk '/^ii/{printf "%s ",$2}'; echo
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/wordpress_phpfpm; mkdir -p $OUT
S=ps101899
echo $S | sudo -S systemctl start mariadb php8.3-fpm nginx
echo $S | sudo -S mysql -e "CREATE DATABASE IF NOT EXISTS wordpress; CREATE USER IF NOT EXISTS 'wp'@'localhost' IDENTIFIED BY 'wp'; GRANT ALL ON wordpress.* TO 'wp'@'localhost'; FLUSH PRIVILEGES;"
echo $S | sudo -S bash -c "cat > /etc/wordpress/config-localhost.php" <<'P'
<?php
define('DB_NAME', 'wordpress');
define('DB_USER', 'wp');
define('DB_PASSWORD', 'wp');
define('DB_HOST', 'localhost');
define('WP_CONTENT_DIR', '/usr/share/wordpress/wp-content');
define('WP_DEBUG', false);
?>
P
echo $S | sudo -S bash -c "cat > /etc/nginx/sites-available/wordpress" <<'N'
server {
  listen 8081; server_name localhost; root /usr/share/wordpress; index index.php;
  location / { try_files $uri $uri/ /index.php?$args; }
  location ~ \.php$ { include snippets/fastcgi-php.conf; fastcgi_pass unix:/run/php/php8.3-fpm.sock; }
}
N
echo $S | sudo -S ln -sf /etc/nginx/sites-available/wordpress /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload; sleep 1
# raise php-fpm workers
echo $S | sudo -S sed -i 's/^pm.max_children = .*/pm.max_children = 16/; s/^pm = .*/pm = static/' /etc/php/8.3/fpm/pool.d/www.conf; echo $S | sudo -S systemctl restart php8.3-fpm; sleep 1
curl -s -o /dev/null -w "install page %{http_code}\n" "http://localhost:8081/wp-admin/install.php"
curl -s -o $OUT/install.html -d "weblog_title=Bench&user_name=admin&admin_password=Adminpass123!&admin_password2=Adminpass123!&pw_weak=on&admin_email=a@b.c&blog_public=0" "http://localhost:8081/wp-admin/install.php?step=2"; grep -c -i "success\|WordPress has been installed" $OUT/install.html
# generate posts via wp-admin? simpler: many hits on the front page and an existing post/permalink structure
curl -s -o /dev/null -w "front %{http_code} %{size_download}B\n" http://localhost:8081/
for p in $(pgrep -f "php-fpm: pool www"); do echo $S | sudo -S taskset -cp 50-57 $p > /dev/null; done
taskset -c 60-63 wrk -t4 -c32 -d15s http://localhost:8081/ > $OUT/warmup.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 50-57 -- taskset -c 60-63 wrk -t4 -c32 -d60s http://localhost:8081/ > $OUT/wrk.log 2>&1
python3 - $OUT/perf.csv $OUT/wrk.log <<'PY'
import csv,re,sys
perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
rps=re.search(r"Requests/sec:\s+([0-9.]+)",open(log).read())
print(f"wordpress php-fpm: rps={rps.group(1) if rps else 'n/a'} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G (php-fpm cores 50-57)")
PY
echo WORDPRESS_DONE
