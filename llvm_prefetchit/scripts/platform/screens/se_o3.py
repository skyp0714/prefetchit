# gem5 stdlib SE-mode X86 O3 config for screening gem5 itself as a workload
import argparse
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_cache_hierarchy import PrivateL1PrivateL2CacheHierarchy
from gem5.components.memory import SingleChannelDDR4_2400
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.components.processors.cpu_types import CPUTypes
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource
from gem5.simulate.simulator import Simulator
ap = argparse.ArgumentParser(); ap.add_argument("--cmd", required=True); ap.add_argument("--options", default="")
a = ap.parse_args()
cache = PrivateL1PrivateL2CacheHierarchy(l1d_size="32kB", l1i_size="32kB", l2_size="2MB")
mem = SingleChannelDDR4_2400(size="2GB")
proc = SimpleProcessor(cpu_type=CPUTypes.O3, isa=ISA.X86, num_cores=1)
board = SimpleBoard(clk_freq="3GHz", processor=proc, memory=mem, cache_hierarchy=cache)
board.set_se_binary_workload(BinaryResource(a.cmd), arguments=a.options.split())
sim = Simulator(board=board)
sim.run()
print("gem5 done:", sim.get_last_exit_event_cause())
