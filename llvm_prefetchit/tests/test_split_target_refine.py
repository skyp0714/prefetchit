import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from split_target_refine import choose,coverage


class FixedSlotSelection(unittest.TestCase):
    def test_shared_calls_do_not_double_count_and_global_cover_avoids_duplicate(self):
        # Calls 1 and 3 share one physical stub. Both stubs can cover line 10,
        # but only the second can cover 20. A local independent ranking would
        # waste both slots on 10; the global choice must cover both populations.
        rows=[dict(line=10,target=640,sites=[1,2,3],weight=1.) for _ in range(10)]
        rows += [dict(line=20,target=1280,sites=[2],weight=.8) for _ in range(10)]
        groups={1:100,3:100,2:200};original={100:[640],200:[640]}
        selected,decisions=choose(rows,groups,{100:1,200:1},original)
        self.assertEqual(selected,{100:[640],200:[1280]})
        self.assertEqual([d['gain_samples'] for d in decisions],[10,10])
        self.assertEqual(coverage(rows,groups,selected)['covered'],20)
        self.assertAlmostEqual(coverage(rows,groups,selected)['weighted_covered'],18.)

    def test_unused_slots_keep_valid_distinct_old_targets(self):
        rows=[dict(line=30,target=1920,sites=[1],weight=1.) for _ in range(8)]
        selected,_=choose(rows,{1:100},{100:3},{100:[640,1280,1920]})
        self.assertEqual(selected,{100:[1920,640,1280]})
        self.assertEqual(len(selected[100]),3)


if __name__=='__main__':unittest.main()
