from neuron import h
h.load_file("stdrun.hoc")
cells=[]
for i in range(400):
    s=h.Section(name=f"soma{i}"); s.L=20; s.diam=20; s.insert("hh")
    d=h.Section(name=f"dend{i}"); d.L=200; d.diam=2; d.nseg=21; d.insert("pas"); d.connect(s(1))
    cells.append((s,d))
syns=[]; ncs=[]
import random
random.seed(1)
for i,(s,d) in enumerate(cells):
    for _ in range(20):
        j=random.randrange(len(cells))
        syn=h.ExpSyn(cells[j][1](0.5)); syn.tau=2; syn.e=0
        nc=h.NetCon(s(0.5)._ref_v, syn, sec=s); nc.threshold=-20; nc.delay=1; nc.weight[0]=0.002
        syns.append(syn); ncs.append(nc)
stims=[]
for i in range(40):
    ic=h.IClamp(cells[i][0](0.5)); ic.delay=1; ic.dur=1e9; ic.amp=0.3; stims.append(ic)
h.dt=0.025; h.finitialize(-65); h.continuerun(1500)
print("done", h.t)
