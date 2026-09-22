#!/usr/bin/env bash
set -u
F=/tmp/claude-1006/-home-hnpark2-prefetchit/d5b98158-c5f3-5c64-8010-4e07621651c4/tasks/biwqyqjn8.output
until grep -q WORDPRESS_DONE $F 2>/dev/null; do sleep 15; done
echo ps101899 | sudo -S rm -f /etc/nginx/sites-enabled/wordpress; echo ps101899 | sudo -S nginx -s reload 2>/dev/null
R=3000 bash /home/hnpark2/prefetchit/flat_codegen/dsb_build/dsb_screen.sh > /tmp/dsb_screen3.log 2>&1
grep -E "DSB socialNetwork|instr=|init" /tmp/dsb_screen3.log | head -30
echo DSB3_DONE
