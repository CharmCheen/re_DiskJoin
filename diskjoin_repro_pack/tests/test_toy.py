#!/usr/bin/env python3
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class DataTests(unittest.TestCase):
    def test_generation_and_config(self):
        subprocess.run([sys.executable,str(ROOT/'scripts/make_toy.py')],check=True,capture_output=True)
        d=ROOT/'workspace/toy'
        data=d/'toy.fbin'
        with data.open('rb') as f:n,dim=struct.unpack('<II',f.read(8))
        self.assertEqual((n,dim),(12000,16))
        self.assertEqual(data.stat().st_size,8+12000*16*4)
        meta=json.loads((d/'toy_metadata.json').read_text())
        self.assertGreater(meta['gt_sampled'],0)
        c=(d/'toy.config').read_text()
        self.assertIn(f"gt               {meta['gt_sampled']}", c)
if __name__=='__main__':unittest.main()
