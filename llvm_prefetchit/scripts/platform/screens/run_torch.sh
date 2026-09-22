#!/usr/bin/env bash
set -u
until grep -q "TORCH DONE" /tmp/pip_torch.log; do sleep 20; done
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
python3 -c "import torch; print(torch.__version__)" 2>&1 | tail -1
CORE=46 bash $S pytorch_resnet50_cpu_b1 /tmp/screen_inputs/torch "python3 infer.py" 120
echo TORCH_SCREEN_DONE
