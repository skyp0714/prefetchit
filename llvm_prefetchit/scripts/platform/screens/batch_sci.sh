#!/usr/bin/env bash
# broad screen batch: scientific simulators + interpreters (L2I MPKI under load)
set -u
cd /home/hnpark2/prefetchit
export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916
S=llvm_prefetchit/scripts/platform/screen_one.sh
W=/tmp/screen_inputs; cd $W

# LAMMPS: LJ benchmark scaled 2x2x2 (256k atoms), 300 steps
cp -f /usr/share/lammps/bench/in.lj $W/ 2>/dev/null
bash $S lammps_lj_2x2x2 $W "lmp -in in.lj -var x 2 -var y 2 -var z 2 -log none -echo none" 120; cd $W

# GROMACS: SPC/E water box 4 nm, PME, 1 thread
mkdir -p $W/gmx && cd $W/gmx && cat > topol.top <<'T'
#include "oplsaa.ff/forcefield.itp"
#include "oplsaa.ff/spce.itp"
[ system ]
water
[ molecules ]
T
gmx -quiet solvate -cs spc216 -box 4 4 4 -o water.gro -p topol.top > solvate.log 2>&1
cat > md.mdp <<'M'
integrator = md
nsteps = 4000
dt = 0.002
cutoff-scheme = Verlet
nstlist = 10
rlist = 1.0
coulombtype = PME
rcoulomb = 1.0
rvdw = 1.0
tcoupl = v-rescale
tc-grps = System
tau_t = 0.1
ref_t = 300
constraints = h-bonds
nstxout = 0
nstvout = 0
nstenergy = 0
nstlog = 0
M
gmx -quiet grompp -f md.mdp -c water.gro -p topol.top -o md.tpr -maxwarn 5 > grompp.log 2>&1
cd /home/hnpark2/prefetchit && bash $S gromacs_water4nm_pme $W/gmx "gmx -quiet mdrun -nt 1 -ntomp 1 -s md.tpr -nsteps 3000 -deffnm run" 120; cd $W

# OpenFOAM 1912: pitzDaily simpleFoam
mkdir -p $W/of && cd $W/of && rm -rf pitzDaily && cp -r /usr/share/openfoam/tutorials/incompressible/simpleFoam/pitzDaily . 2>/dev/null || cp -r $(find /usr/share/openfoam* /usr/lib/openfoam* -maxdepth 6 -type d -name pitzDaily 2>/dev/null | head -1) .
cd pitzDaily && (source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1; blockMesh > blockMesh.log 2>&1; sed -i 's/^endTime .*/endTime         2000;/' system/controlDict)
cd /home/hnpark2/prefetchit && bash $S openfoam_pitzDaily_simpleFoam $W/of/pitzDaily "bash -c 'source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1; simpleFoam'" 120; cd $W

# Quantum ESPRESSO: Al fcc SCF with shipped pseudo, dense k-mesh
mkdir -p $W/qe && cd $W/qe && cat > al.in <<'Q'
&control
  calculation='scf', prefix='al', pseudo_dir='/usr/share/espresso/pseudo', outdir='./tmp', tprnfor=.true.
/
&system
  ibrav=2, celldm(1)=7.5, nat=1, ntyp=1, ecutwfc=40.0, occupations='smearing', smearing='mv', degauss=0.02
/
&electrons
  conv_thr=1.0d-9
/
ATOMIC_SPECIES
 Al 26.98 Al.pz-vbc.UPF
ATOMIC_POSITIONS alat
 Al 0.0 0.0 0.0
K_POINTS automatic
 24 24 24 1 1 1
Q
cd /home/hnpark2/prefetchit && bash $S qe_pwx_al_scf $W/qe "pw.x -in al.in" 120; cd $W

# NWChem: water DFT
mkdir -p $W/nw && cd $W/nw && cat > h2o.nw <<'N'
start h2o
geometry units angstrom
 O 0.000 0.000 0.117
 H 0.000 0.757 -0.469
 H 0.000 -0.757 -0.469
end
basis
 * library aug-cc-pvtz
end
dft
 xc b3lyp
 iterations 100
end
task dft energy
N
cd /home/hnpark2/prefetchit && bash $S nwchem_h2o_b3lyp_augccpvtz $W/nw "nwchem h2o.nw" 120; cd $W

# ABINIT if a pseudopotential is shipped
PSP=$(find /usr/share/abinit/psp -type f 2>/dev/null | grep -i -E "si|al" | head -1)
if [[ -n "$PSP" ]]; then mkdir -p $W/abi && cd $W/abi && cat > si.abi <<A
acell 3*10.26
rprim 0.0 0.5 0.5  0.5 0.0 0.5  0.5 0.5 0.0
ntypat 1
znucl 14
natom 2
typat 1 1
xred 0.0 0.0 0.0  0.25 0.25 0.25
ecut 30.0
ngkpt 8 8 8
nshiftk 1
shiftk 0.5 0.5 0.5
nstep 30
toldfe 1.0d-8
pp_dirpath "$(dirname $PSP)"
pseudos "$(basename $PSP)"
A
cd /home/hnpark2/prefetchit && bash $S abinit_si_scf $W/abi "abinit si.abi" 120; fi; cd $W

# Interpreters / JITs
cat > $W/pybench.py <<'P'
import sympy, random, json, re
x=sympy.symbols('x')
acc=0
for i in range(300):
    e=sympy.integrate(sympy.sin(x)**2*sympy.cos(x)**(i%5), x)
    acc+=len(str(e))
d={str(i):[random.random() for _ in range(50)] for i in range(20000)}
s=json.dumps(d); t=json.loads(s)
r=sum(len(re.findall(r'\d\.\d+', s[i:i+100000])) for i in range(0, len(s), 100000))
print(acc, len(t), r)
P
cd /home/hnpark2/prefetchit
bash $S cpython_sympy_json_re $W "python3 pybench.py" 120
bash $S pypy3_loops $W "pypy3 -c \"import random
s=0
d={}
for i in range(30000000):
    s+= (i*7)%13
    if i%1000==0: d[i]=s
print(s,len(d))\"" 120
bash $S luajit_loops $W "luajit -e 'local s=0 local t={} for i=1,200000000 do s=s+(i*7)%13 if i%1000==0 then t[i]=s end end print(s)'" 120
bash $S ruby_loops $W "ruby -e 's=0; h={}; 30000000.times{|i| s+=(i*7)%13; h[i]=s if i%1000==0}; puts s'" 120
bash $S php_loops $W "php -r '\$s=0; \$h=[]; for(\$i=0;\$i<60000000;\$i++){\$s+=(\$i*7)%13; if(\$i%1000==0) \$h[\$i]=\$s;} echo \$s;'" 120
bash $S mypy_sympy $W "python3 -m mypy --ignore-missing-imports --no-incremental /usr/lib/python3/dist-packages/sympy/core" 180
echo BATCH_SCI_DONE
