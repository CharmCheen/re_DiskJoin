#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from micro_task_cache import simulate, ORIGINAL, REORDERED

class CacheTests(unittest.TestCase):
    def test_original_belady_five_misses(self):
        self.assertEqual(simulate(ORIGINAL, 2, "belady")["misses"], 5)
    def test_reordered_belady_four_misses(self):
        self.assertEqual(simulate(REORDERED, 2, "belady")["misses"], 4)
    def test_belady_no_worse_than_lru_in_this_example(self):
        for tasks in (ORIGINAL, REORDERED):
            self.assertLessEqual(simulate(tasks,2,"belady")["misses"],
                                 simulate(tasks,2,"lru")["misses"])
    def test_bad_capacity(self):
        with self.assertRaises(ValueError):simulate(ORIGINAL,1,"belady")
if __name__ == "__main__":unittest.main()
