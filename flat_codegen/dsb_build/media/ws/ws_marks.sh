#!/usr/bin/env bash
# Extract the wake-stream mark call sites from a binary: "id dso elf_addr" (addr = the call instruction). Usage: ws_marks.sh BIN > marks.txt
objdump -d --no-show-raw-insn "$1" | awk -v dso=$(basename "$1") '
  /cmpq +\$0x0,.*ws_mark/ {inm=1; id=""; next}
  inm && /mov +\$0x[0-9a-f]+,%edi/ {match($0, /\$0x[0-9a-f]+/); id=strtonum(substr($0, RSTART+1, RLENGTH-1))}
  inm && /call +[0-9a-f]+ <ws_mark@plt>/ {split($1, a, ":"); if (id != "") print id, dso, a[1]; inm=0}
  inm && /^$/ {inm=0}'
