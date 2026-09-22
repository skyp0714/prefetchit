#!/usr/bin/env python3
"""OpenMM CPU-platform MD benchmark: a Lennard-Jones fluid (no input files needed) integrated with Langevin dynamics.
Realistic config for our screen: the CPU platform with THREADS threads pinned to the measured cores."""
import sys, openmm as mm, openmm.unit as unit
n = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
threads = sys.argv[2] if len(sys.argv) > 2 else "4"
system = mm.System(); nb = mm.NonbondedForce(); nb.setNonbondedMethod(mm.NonbondedForce.CutoffPeriodic)
nb.setCutoffDistance(1.0*unit.nanometer); nb.setUseSwitchingFunction(True); nb.setSwitchingDistance(0.9*unit.nanometer)
L = (n/25.0)**(1/3.0)
system.setDefaultPeriodicBoxVectors(mm.Vec3(L,0,0)*unit.nanometer, mm.Vec3(0,L,0)*unit.nanometer, mm.Vec3(0,0,L)*unit.nanometer)
import random; random.seed(1); pos=[]
for i in range(n):
    system.addParticle(39.9*unit.amu); nb.addParticle(0.0, 0.34*unit.nanometer, 0.996*unit.kilojoule_per_mole)
    pos.append(mm.Vec3(random.uniform(0,L), random.uniform(0,L), random.uniform(0,L))*unit.nanometer)
system.addForce(nb)
integrator = mm.LangevinMiddleIntegrator(120*unit.kelvin, 1/unit.picosecond, 0.004*unit.picoseconds)
platform = mm.Platform.getPlatformByName('CPU')
ctx = mm.Context(system, integrator, platform, {'Threads': threads})
ctx.setPositions(pos); mm.LocalEnergyMinimizer.minimize(ctx, 10.0, 200)   # tolerance in kJ/mol/nm as a bare float
ctx.setVelocitiesToTemperature(120*unit.kelvin, 1)
print(f"OpenMM {mm.version.version} CPU platform, {n} LJ particles, {threads} threads", flush=True)
while True: integrator.step(500)
