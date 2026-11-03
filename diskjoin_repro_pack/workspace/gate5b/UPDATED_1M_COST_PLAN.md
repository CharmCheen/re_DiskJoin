# Updated BigANN1M cost & execution plan (Gate 5B, deliverable 3)

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
This supersedes the cost paragraph in `REPORT.md` §4. The change is driven by the new
**streaming pair verifier** (`scripts/verify_pairs_stream.py`, deliverable 2), which
removes the need to hold or set-load full pair outputs.

---

## 1. Measured basis (100K, from this project, not estimated)

Config: n=100,000, d=128, cluster_num=1000, K=24, radius=73984, mem_budget=5,120,000 B,
OMP_NUM_THREADS=1. Evidence: `runs/step2_100k/normal/{time.log,stderr.log,stdout.log}`
and `logs/step3_1m_blocker.log`.

| measured quantity | 100K value | source |
|---|---|---|
| build wall | 1.65902 s | `stdout.log` "[1.65902 s] Build done" |
| join wall | 5.69056 s (7.35058 − 1.65902) | `stdout.log` "[7.35058 s] Join done" |
| total wall | 7.35 s | `time.log` |
| user / sys CPU | 5.32 s / 0.30 s | `time.log` |
| peak RSS | 88,044 KB | `time.log` |
| `dist_comp` | 154,113,552 | `stderr.log` |
| pairs | 3,855,811 lines | `stderr.log` |
| read_calls / effective bytes | 5,192 / 286,884,352 B | `stderr.log [gate4b1-io]` |
| requested aligned bytes | 305,594,368 B | `stderr.log [gate4b1-io]` |
| process block input / output | 596,864 / 193,904 blocks | `time.log` |
| data.clusters | 51,200,000 B | `stat` |
| data.metadata | 1,324,032 B | `stat` |
| data.hnsw | 692,800 B | `stat` |
| pairs.txt | 45,411,278 B (11.78 B/line) | `stat` |
| knn / tasks / trace | 283,908 / 62,258 / 280,538 B | `stat` |
| GT (200 endpoints, m=272) | 110,567 B | `stat` |
| whole 100K run tree | 99,285,622 B | `du -sb` |

**Derived rates:** `dist_comp` rate = 154,113,552 / 5.69 s = **27.1 M comps/s**.

## 2. Extrapolation assumptions (stated explicitly)

1. **n: ×10** (100K → 1M); d fixed at 128.
2. **Fixed radius ⇒ neighbor density scales with n.** At a fixed radius and a fixed
   data distribution, expected neighbors per vector is proportional to the number of
   points. So degree ≈ ×10, and therefore **pairs and `dist_comp` ≈ ×100**
   (n ×10 times degree ×10). Cross-check: 1M GT pairs ≈ `n·degree/2` =
   `1e6·1004.6/2` ≈ 502 M; the join produced 76.8 % of GT at 100K ⇒ ≈ 386 M output
   pairs, consistent with ×100.
3. **cluster_num stays 1000, K=24, radius=73984, error_bound=0.1** (unchanged for
   comparability; see `configs/bigann1m.validation_criteria.json`). The HNSW over the
   1000 centers therefore stays constant-size.
4. `mem_budget` = 10 % of data bytes = **51,200,000 B** at 1M (vs 5,120,000 B at 100K).
5. **Sensitivity:** if the join's candidate search prunes more aggressively at 1M and
   the effective degree grows only ×5, pairs and `dist_comp` scale ×50 (half the
   figures below). The ×100 column is the planning (worst-realistic) case.

Note: the in-binary `dist_comp` is a float32 counter (finding F2); the plan uses the
order-invariant integer value.

## 3. Per-phase disk / memory / time at 1M

### 3.1 Data conversion (one-time)

| item | estimate | basis |
|---|---|---|
| gz download | ≤128 MiB (expected 93.4 MiB) | deliverable 1 §2 |
| `bigann1m.bvecs` | 132,000,000 B (125.9 MiB) | `n*(d+4)` |
| `bigann1m.fbin` | 512,000,008 B (488.3 MiB) | `8 + n*d*4` |
| disk retained / peak | ≈614 MiB / ≈742 MiB (gz transient) | arithmetic |
| memory | ≤ ~200 MiB streaming | converter is stream-based |
| time | ~2–5 min | gz streaming decompress + 128 M float casts |

### 3.2 Graph build (per run)

| item | 100K measured | 1M estimate (×10) | basis |
|---|---|---|---|
| wall | 1.66 s | **~17–30 s** | assignment scales with n; center HNSW constant |
| data.clusters | 51,200,000 B | 512,000,000 B (488.3 MiB) | `n*d*4` (full float32 copy) |
| data.metadata | 1,324,032 B | ~13,240,320 B (12.6 MiB) | 13.24 B/vector (linear upper bound) |
| data.hnsw | 692,800 B | ~0.7 MiB | `cluster_num` fixed at 1000 |

Build disk subtotal ≈ **501 MiB**.

### 3.3 Join (per run) — the binding phase

| item | 100K measured | 1M estimate (×100) | 1M sensitivity (×50) |
|---|---|---|---|
| `dist_comp` | 154,113,552 | 1.54e10 | 7.7e9 |
| wall @27.1 M/s | 5.69 s | **~568 s ≈ 9.5 min** | ~4.7 min |
| pairs | 3,855,811 | ~385.6 M | ~193 M |
| pairs.txt bytes | 45,411,278 | ~4.23 GiB (×100); **~4.7–5.2 GiB** with 5→6-digit IDs | ~2.4 GiB |
| knn.txt | 283,908 B | ~28 MB | ~14 MB |
| tasks.txt | 62,258 B | ~6 MB | ~3 MB |
| trace.txt | 280,538 B | ~28 MB | ~14 MB |
| bucket reads | 5,192 reads / 286.9 MB | ~519k reads / ~28.7 GB | ~half |
| requested aligned I/O | 305.6 MB | ~30.6 GB | ~half |

Join disk subtotal ≈ **5.3 GiB** (dominated by pairs.txt).

### 3.4 GT (one-time, external exact)

| item | estimate | basis |
|---|---|---|
| compute | 200 endpoints × 1M × 128 dims ≈ 2.56e10 int ops; **~30–90 s** at OMP=4 | 100K was 2.56e9 with the same binary |
| gt.txt / diagnostic | ~1.1 MB | degree ×10 |

### 3.5 Output verification (one-time, streaming — deliverable 2)

| check | method | RAM | time | temp disk |
|---|---|---|---|---|
| total / illegal / self-joins / range / digest | one streaming pass | O(1) | ~5–10 s per ~5 GB | 0 |
| exact global duplicates | `--dup-mode external-sort`: `sort -S256M` then adjacent-equal | 256 MB cap | ~3–8 min | **~pairs-size, ≈5 GiB** |
| cross-version compare, order known | lockstep streaming SHA-256 (`--ordered`) | O(1) | ~10–20 s for both | 0 (needs both files) |
| cross-version compare, order unknown | external-sort multiset compare | 256 MB cap | ~6–16 min | ~2× pairs (≈10 GiB) |

**Why this changes the plan.** The previous approach (`oracle/evaluate.py`
`endpoint_counts`) held every pair key in RAM, and the old plan kept a full `pairs.txt`
per mode and set-compared them — ≥2× pairs and unbounded RAM. The streaming verifier
gives counts/legality/self-joins/digest in O(1) RAM, and cross-version equality by a
streaming digest. Strategy for 1M: **run mode A → verify + record digest → delete
pairs → run mode B → verify + record digest → compare digests**, so only one `pairs.txt`
exists at a time. Exact duplicate detection still needs a ~pairs-size sort temp; it is
either authorized (§4) or reported **UNVERIFIED** (never "0").

## 4. Totals and requested authorization

### 4.1 Per-phase summary (planning case, ×100)

| phase | disk | memory | time |
|---|---|---|---|
| data conversion | ≈614 MiB retained (+128 MiB transient) | ≤200 MiB | 2–5 min |
| graph build (per mode) | 501 MiB | ~0.9 GiB | ~0.3–0.5 min |
| join (per mode) | 5.3 GiB (pairs) | ~0.9–2 GiB | ~9.5 min |
| GT | ~1.1 MB | small | ~0.5–1.5 min |
| verification (per mode) | 0 (stream) + optional ~5 GiB sort temp | 256 MB cap | 0.2–8 min |
| **session total (2 modes)** | **≈6.4 GiB** (no sort temp) / **≈11.4 GiB** (with exact-dup temp) | **≤4 GiB** | **≈22–30 min** |

### 4.2 Requested authorization amounts

| resource | request | justification |
|---|---|---|
| **download** | **128 MiB** (`134,217,728` B) FTP Range of `bigann_base.bvecs.gz` | expected 93.4 MiB; margin for gz-ratio uncertainty. No query/GT download — GT is computed locally; queries are not needed for the join |
| **new disk** | **12 GiB** | worst case = inputs ≈0.75 GiB + one mode's artifacts ≈5.3 GiB + exact-dup sort temp ≈5 GiB. Minimum viable **6.5 GiB** if exact-dup is skipped (marked UNVERIFIED) |
| **wall time** | **90 min** for the 1M session | 2 modes (~20 min) + GT (~1.5 min) + verify (~1–16 min) + conversion (~5 min) + slack. The 30-min envelope is only borderline and leaves no room for the exact-dup pass |
| **memory** | **4 GiB RSS** | expected ~1–2 GiB (100K was 88 MiB); 4 GiB is the existing cap |
| **CPU** | ≤4, `OMP_NUM_THREADS=1`, 1 join thread | existing discipline |
| **filesystem** | `/data` (6.9 T free) for inputs + run + sort temp | root `/` has 815 GiB free too; `/data` is the intended data mount |

### 4.3 What does NOT fit (explicit, not silently dropped)

- **ASan at 1M does not fit the envelope.** 100K ASan measured RSS 619,900 KB ≈ 6.9×
  normal; ×10 data ⇒ ~4–5 GiB RSS (over the 4 GiB cap) and ~7–10× time (~2–3.5 h).
  So the 1M trial would run **non-sanitized only**; the sanitizer evidence stays the
  already-passing **100K** ASan/UBSan run, explicitly labelled as 100K. A 1M ASan run
  would need a separate authorization (~4 h, ≥8 GiB) or a reduced subset.
- **Physical SSD I/O remains UNVERIFIED** (unchanged): the figures above are
  syscall/process-level, not device-level.

## 5. Execution sequence once authorized

```
# 1. acquire + convert + manifest  (deliverable 1)
python3 -B scripts/acquire_bigann1m.py --authorized --keep-gz
python3 -B scripts/make_data_manifest.py --name bigann1m \
    --fbin data/bigann1m/bigann1m.fbin --bvecs data/bigann1m/bigann1m.bvecs \
    --expect-n 1000000 --expect-d 128 --out configs/manifest_bigann1m.json
# 2. mode A: build + join + dump pairs (bounded)
# 3. verify + record digest, then delete pairs
python3 -B scripts/verify_pairs_stream.py verify --pairs <A>/pairs.txt --n 1000000 \
    --gt runs/gate5b_1m/gt.txt --dup-mode external-sort --sort-mem-mb 256 \
    --out runs/gate5b_1m/A_verify.json
# 4. mode B: build + join + dump pairs
# 5. verify + record digest, delete pairs; compare digests
python3 -B scripts/verify_pairs_stream.py compare --left A.pairs --right B.pairs --ordered
# 6. GT over the fixed 200 endpoints (oracle), then evaluate
```

Every step keeps within the tenancy rules: OMP=1, ≤4 build jobs, per-step timeouts,
failure logs retained, no commit/push/reset/clean.

---

## 6. Evidence produced this round (deliverable 3)

| artifact | meaning |
|---|---|
| this file | per-phase 1M cost + authorization request |
| `logs/step6_stream_verify_100k.log` | streaming verify/compare validated on the real 100K output (the basis for the verification-phase costs) |
| `runs/step2_100k/normal/{time.log,stdout.log,stderr.log}` | the measured 100K basis quoted in §1 |
