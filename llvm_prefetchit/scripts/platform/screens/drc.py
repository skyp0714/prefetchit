# klayout batch: build a large random layout, then boolean/DRC-style region ops (exercises the C++ geometry engine)
import pya, random
random.seed(7)
ly = pya.Layout(); top = ly.create_cell("TOP")
l1 = ly.layer(1, 0); l2 = ly.layer(2, 0)
for i in range(400000):
    x = random.randrange(0, 2000000); y = random.randrange(0, 2000000)
    w = random.randrange(100, 2000); h = random.randrange(100, 2000)
    top.shapes(l1 if i % 2 else l2).insert(pya.Box(x, y, x + w, y + h))
r1 = pya.Region(top.begin_shapes_rec(l1)); r2 = pya.Region(top.begin_shapes_rec(l2))
r1.merged_semantics = True
a = r1 & r2; b = r1 - r2; c = (r1 | r2).sized(50)
viol = r1.space_check(150) ; viol2 = r1.separation_check(r2, 120)
print("shapes", r1.count(), r2.count(), "and", a.count(), "not", b.count(), "or", c.count(), "space", viol.count(), "sep", viol2.count())
