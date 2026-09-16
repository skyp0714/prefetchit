#!/usr/bin/env bash
# CXXRTL (yosys C++ codegen) on a 48-core picorv32 array: another flattened-simulator kind
set -u
cd /tmp/screen_inputs/cxxrtl
[[ -f picorv32.v ]] || curl -sSL -o picorv32.v https://raw.githubusercontent.com/YosysHQ/picorv32/main/picorv32.v
python3 - <<'PY'
N=48
lines=["module top(input clk, input resetn, output [31:0] sum);", "  wire [31:0] s [0:%d];" % (N-1)]
for i in range(N):
    lines += [f"  wire mem_valid{i}, mem_instr{i}; wire [31:0] mem_addr{i}, mem_wdata{i}; wire [3:0] mem_wstrb{i}; reg [31:0] mem_rdata{i}; reg mem_ready{i};",
              f"  picorv32 #(.ENABLE_MUL(1), .ENABLE_DIV(1), .ENABLE_IRQ(1), .BARREL_SHIFTER(1), .COMPRESSED_ISA(1)) cpu{i}(.clk(clk), .resetn(resetn), .mem_valid(mem_valid{i}), .mem_instr(mem_instr{i}), .mem_ready(mem_ready{i}), .mem_addr(mem_addr{i}), .mem_wdata(mem_wdata{i}), .mem_wstrb(mem_wstrb{i}), .mem_rdata(mem_rdata{i}));",
              f"  reg [31:0] rom{i} [0:1023];",
              f"  always @(posedge clk) begin mem_ready{i} <= mem_valid{i} && !mem_ready{i}; mem_rdata{i} <= rom{i}[mem_addr{i}[11:2]] + {i}; if (mem_valid{i} && mem_wstrb{i} != 0) rom{i}[mem_addr{i}[11:2]] <= mem_wdata{i}; end",
              f"  assign s[{i}] = mem_addr{i};"]
lines.append("  assign sum = " + " ^ ".join(f"s[{i}]" for i in range(N)) + ";\nendmodule")
open("top.v","w").write("\n".join(lines)+"\n")
PY
yosys -q -p "read_verilog picorv32.v top.v; hierarchy -top top; proc; opt_clean; write_cxxrtl -O4 sim.cc" > yosys.log 2>&1 || { tail -3 yosys.log; exit 1; }
YINC=$(yosys-config --datdir)/include
cat > main.cc <<'M'
#include "sim.cc"
#include <cstdio>
int main(int argc, char** argv){ long n = argc>1?atol(argv[1]):200000; cxxrtl_design::p_top top;
  top.p_resetn.set<bool>(false); for(int i=0;i<10;i++){ top.p_clk.set<bool>(false); top.step(); top.p_clk.set<bool>(true); top.step(); }
  top.p_resetn.set<bool>(true);
  for(long i=0;i<n;i++){ top.p_clk.set<bool>(false); top.step(); top.p_clk.set<bool>(true); top.step(); }
  printf("sum=%u\n", top.p_sum.get<uint32_t>()); return 0; }
M
clang++-19 -O2 -g -std=c++17 -I$YINC -I$YINC/backends/cxxrtl/runtime main.cc -o sim_cxxrtl 2> build.err || { tail -3 build.err; exit 1; }
size sim_cxxrtl | tail -1
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
CORE=48 bash $S cxxrtl_picorv32x48 /tmp/screen_inputs/cxxrtl "./sim_cxxrtl 300000" 120
echo CXXRTL_DONE
