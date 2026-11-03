#!/usr/bin/env python3
"""Gate 5A: sample calibration ids and GT endpoints (pure stdlib).

Samplers (recorded for reproducibility):
  - calibration ids: 2000 ids drawn from range(100000) without replacement
    via random.Random(20260101).sample()  [CPython Mersenne Twister]
  - GT endpoints: 200 ids drawn from range(100000) without replacement via
    random.Random(20260101).sample(), a DIFFERENT stream from the calibration
    draw (fresh Random(20260101) instance), then endpoint 0 appended
    explicitly (deduplicated) because the in-binary sampled recall counts
    vector ids divisible by 100000, i.e. vector 0 on this 100K dataset.

Output files (one id per line):
  data/calib_ids_2000.txt    (sorted)
  data/gt_endpoints.txt      (sorted, 200 sampled; vector 0 appended at END,
                              see "EXPLICIT" line; dedup rule applied)
"""
import random
import sys

N = 100000

def main():
    calib_k = 2000
    endp_k = 200

    rng_c = random.Random(20260101)
    calib = rng_c.sample(range(N), calib_k)

    rng_e = random.Random(20260101)
    endp = rng_e.sample(range(N), endp_k)

    calib_sorted = sorted(calib)
    endp_sorted = sorted(endp)
    zero_was_sampled = 0 in endp_sorted
    if not zero_was_sampled:
        endp_sorted.append(0)

    with open("data/calib_ids_2000.txt", "w") as f:
        for i in calib_sorted:
            f.write(f"{i}\n")
    with open("data/gt_endpoints.txt", "w") as f:
        for i in endp_sorted:
            f.write(f"{i}\n")
        f.write("# EXPLICIT 0 appended as endpoint (in-binary recall samples id%100000==0); "
                f"0_was_in_sampled_200={'yes' if zero_was_sampled else 'no'}\n")

    print(f"python={sys.version.split()[0]}")
    print(f"calib_ids={len(calib_sorted)} (sorted; RNG=random.Random(20260101).sample(range(100000),2000))")
    print(f"endpoints={len(endp_sorted)} incl. vector 0 (200 sampled, "
          f"0_was_in_sampled_200={'yes' if zero_was_sampled else 'no'})")
    print(f"endpoints_min={min(endp_sorted)} endpoints_max={max(endp_sorted)}")

if __name__ == "__main__":
    main()
