#!/usr/bin/env bash
set -u
cd /home/hnpark2/prefetchit
export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916
S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
W=/tmp/screen_inputs
bash $S lammps_lj_2x2x2 $W "lmp -in in.lj -var x 2 -var y 2 -var z 2 -log none -echo none" 120
# QE heavier
sed -i 's/ecutwfc=40.0/ecutwfc=70.0/; s/ 24 24 24 1 1 1/ 40 40 40 1 1 1/' $W/qe/al.in
bash $S qe_pwx_al_scf_heavy $W/qe "pw.x -in al.in" 120
# OpenFOAM: find tutorial
PD=$(find /usr/share/openfoam /usr/share/doc /opt -maxdepth 8 -type d -name pitzDaily 2>/dev/null | grep simpleFoam | head -1)
echo "pitzDaily at: $PD"
if [[ -n "$PD" ]]; then rm -rf $W/of/pitzDaily; mkdir -p $W/of; cp -r "$PD" $W/of/pitzDaily; cd $W/of/pitzDaily && bash -c 'source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1; blockMesh > blockMesh.log 2>&1; echo blockMesh rc=$?'; sed -i 's/^endTime .*/endTime         3000;/' system/controlDict; cd /home/hnpark2/prefetchit
  bash $S openfoam_pitzDaily_simpleFoam $W/of/pitzDaily "bash -c 'source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1; simpleFoam'" 120; fi
# ABINIT diagnosis
echo "abinit psp files:"; find /usr/share/abinit/psp -type f 2>/dev/null | head -5; tail -5 $OUT_DIR/logs/abinit_si_scf.run.log 2>/dev/null | cut -c1-150
# mypy diagnosis
tail -3 $OUT_DIR/logs/mypy_sympy.run.log 2>/dev/null | cut -c1-150
bash $S mypy_sympy2 $W "python3 -m mypy --ignore-missing-imports --no-incremental --follow-imports=skip /usr/lib/python3/dist-packages/sympy/core/expr.py /usr/lib/python3/dist-packages/sympy/core/basic.py /usr/lib/python3/dist-packages/sympy/polys/polytools.py" 180
echo BATCH_FIX_DONE
