# DiskJoin Gate 5B — BigANN1M bounded correctness trial

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`

**Bottom line: Step 3/4 (BigANN1M) is BLOCKED — no BigANN1M data exists on the server and
downloads are forbidden. Steps 1–2 were completed and independently verified. The 1M
execution was NOT started, and no substitute-data experiment was fabricated.**

All new material is under `diskjoin_repro_pack/workspace/gate5b/`; prior Gate assets were
not modified. No commit/push/reset/clean was performed.

---

## A. Conclusion: is BigANN1M correctness + resource feasibility PASSED?

**NO — BLOCKED (not passed).** The BigANN1M dataset is absent and downloads are forbidden.
No 1M run was performed. Independently estimated 1M cost (extrapolated from the measured
100K run) also sits at/over both the 5 GiB new-disk budget and the 30-minute budget, so even
with data present this trial could not fit the stated envelope without shrinking it.

## B. Conclusion: ready for mechanism ablations?

**Not ready at 1M. Ready and validated at 100K, with one caveat.** The read-path defect is
fixed with deterministic tests and a byte-identical 100K regression, so correctness
instrumentation is trustworthy. However (i) the 1M dataset is missing, and (ii) the earlier
Gate 5A-R follow-up already flags *physical SSD I/O as UNVERIFIED* and notes that
sampled-endpoint metrics are not full-join Recall. Mechanism ablations that compare I/O or
cache behaviour still need a data/I/O-verified setup.

## C. What is still missing for paper-level reproduction

1. The real BigANN1M (or larger) corpus + provenance (see `configs/bigann1m.validation_criteria.json`).
2. A 1M (and larger) run under the resource envelope, including one sanitizer build.
3. Physical-SSD I/O measurement (distinguish request I/O / returned bytes / process block
   input / physical SSD I/O) — still unverified.
4. Full-join Recall at scale; the 200-endpoint full-neighborhood GT is a sampled protocol.
5. Mechanism ablations only after the above.

---

## 1. Step 1 — independent re-verification of Gate 5A-R evidence (DONE)

Log: `workspace/gate5b/logs/step1_gate5ar_evidence_verification.log`

Recomputed from raw artifacts, treating the prior PASS as a lead only:

| check | result |
|---|---|
| `server_evidence_20261103` manifest `sha256sum -c` | 96/96 OK, rc=0 |
| `followup_20261103` manifest | 50/50 OK, rc=0 |
| tarball integrity (`gzip -t`) | both OK |
| 3-mode identity (`normal`/`asan`/`prefetch_off`) on 7 artifacts | byte-identical |
| independent recompute of output SHA-256 | matches `evaluation.json`-pinned pairs hash |
| pairs legality/uniqueness | 3,855,811 lines = unique, 0 illegal, 0 duplicate |
| sanitizer strings in **actual** logs | 0 (the 2 hits are self-referential text inside `SERVER_REPORT.md`) |
| input hashes vs `run_linux.sh` expectations | match |

**No finding overturns the Gate 5A-R correctness conclusion.** Current tracked diff is only
`gate5ar/scripts/run_linux.sh` (+4 lines, build-dir init fix):

```
$ git -C /home/qch/DiskJoin diff --name-only
diskjoin_repro_pack/workspace/gate5ar/scripts/run_linux.sh
```

---

## 2. Step 2 — read-failure was ignored in `ClusterIO` (FIXED, tested, regression PASS)

### 2.1 Audit of the actual read path (`lib/ClusterIO.h`)

- Constructor `open(clusterfile, O_RDONLY|O_DIRECT)` return value **unchecked**.
- `posixDirectReadCluster` (the only live read path) ignored `lseek` and `read` returns:
  `read(fd, buffer, aligned_read_size)` result discarded, then
  `memcpy(data_buffer, buffer+offset, read_size)`. `buffer` is reused across calls, so a
  short read **silently returned stale bytes from a previous bucket**.
- `readCluster` is dead code and unchecked.
- `readMetaData()` did not verify completeness.
- Latent: `buffer` was uninitialised in the constructor but `free(buffer)` runs in the
  destructor, so a throwing `readMetaData()` (truncated metadata) freed garbage.

### 2.2 Minimal patch

Patch: `workspace/gate5b/patches/clusterio_read_safety.patch`
Header: `workspace/gate5b/instrumented/DiskJoin/lib/ClusterIO.h`
`6647f18344250bb18d02e8e2796a467177976794aca0192e784f0a52e25caaac` →
`66c4f4dc903258ae86f85933befca5d002407d9f2f68477d7c906836ea2baac4`

Changes (all `[GATE5B]`-tagged):
1. Constructor fail-fast on unopenable streams and on `open(O_DIRECT) == -1`.
2. `buffer(nullptr)` initialisation (no free of uninitialised pointer).
3. `readMetaData()` throws if the metadata stream is truncated.
4. New `static readExactOrThrow(fd, dst, len)`: retries `EINTR`, throws on EOF / short read /
   other error — never leaves the destination stale-filled.
5. `posixDirectReadCluster` checks `lseek` and reads the **full PAGE_SIZE-aligned** extent via
   `readExactOrThrow` (alignment preserved) before `memcpy`.
6. `readCluster` completeness check.

### 2.3 Deterministic read-path tests

Test: `workspace/gate5b/tests/test_clusterio_read.cpp`, log
`workspace/gate5b/logs/step2_readpath_test.log`.

| test | result |
|---|---|
| T1 normal O_DIRECT read returns exact bucket values | ok |
| T2 truncated cluster file throws instead of returning stale bytes | ok |
| T3 read failure (EBADF) throws | ok |
| T4 EINTR-interrupted read retried to completion | ok |
| T5 constructor fails on missing files | ok |
| T6 truncated metadata throws | ok |

Negative control `tests/test_clusterio_read_negative.cpp` against the **pre-fix** header:
aborts in `~ClusterReader()` → `free()` double-free on the uninitialised `buffer` (gdb
backtrace captured in the log), i.e. the bug is reproduced; against the patched header it
reports 3 FAILs (bugs gone). So the positive test genuinely detects the defect.

### 2.4 Bounded 100K output-consistency regression (PASS)

Script `scripts/run_100k_regression.sh` (OMP_NUM_THREADS=1, BUILD_JOBS≤4, per-step 600 s,
30-min deadline), comparator `scripts/regression_compare.py`, log
`workspace/gate5b/logs/step2_readpath_regression.log`.

Frozen baseline input hashes: bvecs `cd48bfd0…`, fbin `d9671097…`.

| artifact | normal | prefetch_off | frozen Gate 5A `r1_default` |
|---|---|---|---|
| knn.txt | `66015e11…` | same | same |
| tasks.txt | `4281c529…` | same | same |
| pairs.txt | `8d2ed373…` | same | same |
| trace.txt | `dd0811df…` | same | same |
| data.metadata | `a1fe94de…` | same | (n/a) |
| data.hnsw | `212f0a5f…` | same | (n/a) |
| data.clusters | `6bfbf4ef…` | same | (n/a) |

pairs = 3,855,811 unique, 0 illegal, 0 duplicate; `[gate3-inv] perm_ok=1 … bucket_sum=100000`.
**The read-path fix is behaviour-preserving on well-formed 100K input.**

### 2.5 100K ASan+UBSan on the patched source

Log `logs/step2_readpath_asan_100k.log`: rc=0, **0 sanitizer hits**, all 7 artifacts
byte-identical to `normal`, `[gate3-stat] sampled_count=2 gt=3`. This is a **100K** sanitizer
pass and does **not** substitute for the (not run) 1M sanitizer.

### 2.6 Unit suite

`logs/step3_unit_tests.log`: **13/13 OK** (oracle + statistics + build-dir regressions).

---

## 3. Step 3 — 1M config & Oracle preparation (BLOCKED on data; prep done)

### 3.1 Data location (downloads forbidden)

Searched repo + `/` (excluding `/proc,/sys`), files >300 MB, all `*.fbin/*.bvecs/*.gz/*.tar`
>10 MB, `/data` (7.3 T, empty except root-only `lost+found`), `/home/amax` (unreadable).
**No BigANN1M data exists.** Only:

- `workspace/gate5a/data/bigann100k.{fbin,bvecs}` — the 100K subset (real).
- `workspace/gate5a/data/bigann_base.bvecs.gz.prefix24m` — 25,165,824 B **gzip prefix**
  (inner name `1milliard.p1.siftbin`). A truncated gzip stream of the 1-billion-vector base;
  not a record-aligned 1M fbin/bvecs. Unusable; using it would be fabricating a substitute.

**Blocker recorded in `configs/bigann1m.validation_criteria.json` and
`logs/step3_1m_blocker.log`.** No substitute-data experiment was started.

### 3.2 Validated data manifest (replaces 100K-only hardcoding)

New `scripts/make_data_manifest.py` generates a manifest from a real fbin (+optional bvecs),
validating: fbin header (uint32 LE n,d), `size == 8+n*d*4`, optional bvecs
`size == n*(d+4)` **and every per-record dimension prefix**, plus optional `--expect-n/d`.
Negative controls (`logs/step3_data_manifest.log` §3c) confirm it **rejects** a truncated fbin
and a wrong expected n. Manifest for the real 100K data:
`data/manifest_bigann100k.json` (n=100000, d=128, fbin 51,200,008 B, bvecs records_checked=100000).

Rewired to consume the manifest (checks moved, **not disabled**):

| site | before | after |
|---|---|---|
| `oracle/independent_check.py` | literal `(100000,128)` | `--manifest` provides n,d + sha256 pins |
| `oracle/sample_endpoints.py` | `--n default=100000` | `--manifest` provides n,dimension |
| `oracle/gt_calib.cpp` | literal `n > 100000` | `GATE5B_ORACLE_MAX_N` (from manifest n) |
| `scripts/validate_run.py` | literal `bucket_sum != "100000"` | `--manifest` provides expected n |
| `tests/test_correctness.py` | implicit 100000 | passes manifest-derived `expected_n` (+ new mismatch test) |

Patch: `workspace/gate5b/patches/manifest_refactor.patch`.

### 3.3 Oracle wiring validated on the real 100K data

`logs/step3_data_manifest.log` §3f–3i and `logs/step3_oracle_eval_100k.log`:

- Regenerated calibration/evaluation/diagnostic split from the manifest is **byte-identical**
  to the frozen Gate 5A-R split.
- Full-neighborhood GT (m=272) `gt.txt`/`diagnostic.txt` **byte-identical** to Gate 5A-R.
- `independent_check.py --manifest`: "all coordinates equal", independent distance cross-check
  on endpoints `[0, 1786, 2878, 3008]` (≥3 + diagnostic) passes.
- Negative control: oracle **rejects** n above the manifest bound.
- Manifest-driven `evaluate.py` reproduces the frozen metrics exactly (below).

### 3.4 Scale-driven parameter changes (fixed threshold kept)

- `threshold_squared = 73984` — **fixed, not re-searched**.
- `cluster_num = 1000`, `K = 24`, `error_bound = 0.1` — unchanged for comparability.
- `mem_budget` (cache) = **10 % of data bytes**: 100K → `0.00476837158203125`
  (5,120,000 B); proposal for 1M → `0.0476837158203125` (51,200,000 B), to be applied only
  once real 1M data exists.
- In-binary `DiskJoin.h` samples ids divisible by 100000 for its printed "sampled recall".
  At 1M that selects 10 seed ids, so the **reported** metric must remain the external
  full-neighborhood GT over the fixed 200 endpoints (`evaluate.py`), not the in-binary print.

### 3.5 100K sampled metrics (manifest-driven, full-neighborhood GT, 200 endpoints)

threshold²=73984; bootstrap: whole endpoint incl. empty-GT, 5000 reps, seed 2026110303.

| metric | estimate | 95 % CI | notes |
|---|---|---|---|
| neighbor-weighted Recall | 0.8172816794719187 | [0.7634864, 0.8682656] | 5000 valid |
| nonempty-endpoint mean Recall | 0.6675276752768653 | [0.6087999, 0.7229044] | 5000 valid |
| Precision | 1.0 | [1.0, 1.0] | **degenerate** (0 sampled FP) |

empty-GT endpoints 68/200; sampled false positives 0; total pairs 3,855,811.
These are **sampled-endpoint** metrics on 100K — **not** full-join Recall, and **not** the
1M result. Statistical limits: single corpus/graph; endpoint holdout shares the corpus; the
degenerate precision interval carries no information about FP rate.

---

## 4. Step 4 — bounded 1M execution (NOT STARTED)

Pre-run state (`logs/step3_1m_blocker.log`): load ~0.25; 24× Xeon Silver 4310 (AVX2/FMA/
AVX-512F); 62 GiB RAM (~58 GiB available); `/` 815 GiB free; `/data` 6.9 T free.

Measured 100K cost: wall **7.35 s**, RSS **88,044 KB**, derived disk ~95 MB
(clusters 49 MB + metadata 1.3 MB + hnsw 0.68 MB + pairs 44 MB).

1M extrapolation:
- cache (10 %) 5,120,000 → 51,200,000 B;
- pairs grow ~O(n·degree); degree ~×10 at 1M ⇒ pairs ~×100 (~385 M, ~4.6 GB text);
- derived disk ≈ 512 MB clusters + 9 MB metadata + 7 MB hnsw + ~4.6 GB pairs ≈ **5.1 GB** ⇒
  **exceeds** the 5 GiB new-disk budget before GT/tasks/trace/ASan and before two modes;
- join `dist_comp` ~100× (154 M → ~15 G) ⇒ ~11–12 min/mode; ×2 modes + GT(200×1M×128) +
  ASan ⇒ **over** the 30-minute budget.

**Decision: output plan + blocker and stop. No 1M run started** (data absent and cost over
budget). Per the task, samples were **not** shrunk and passed off as the full protocol.

---

## 5. Time / RSS / I/O scoping

- **Cache budget vs memory:** configured cache budget = 5,120,000 B = 10 % of the 51,200,000 B
  *data* size — **not** a percentage of process/total memory. Actual cache allocation
  (`[gate4a-cache] length=44544 × capacity_slots=28 × 4 B`) = 4,988,928 B; other working
  memory = data matrix (100,000×128×4 = 51,200,000 B) + task/order buffers. Peak process RSS 100K normal = 88,044 KB;
  prefetch_off = 87,972 KB; ASan = 619,900 KB.
- **I/O accounting (100K, unscoped to physical device):**
  `read_calls=5192`, `effective_bytes=286,884,352` (returned payload),
  `requested_aligned_bytes=305,594,368` (PAGE-aligned read sizes passed to `read(2)`).
  `/usr/bin/time` `File system inputs` = 596,864 blocks (×512 = 305,594,368 ≈
  requested_aligned_bytes) — this is **process-level block input**, not physical SSD I/O.
- **Physical SSD I/O: UNVERIFIED** (unchanged from Gate 5A-R; page cache not cleared, no
  device counters used).
- Request I/O ≠ successfully-returned bytes ≠ process-level block input ≠ physical SSD I/O:
  these are kept distinct throughout.

---

## 6. Failure evidence / stop conditions

- No input/GT inconsistency, illegal/duplicate pair, sampled-endpoint FP, read failure,
  output inconsistency, sanitizer error, timeout, or resource overrun occurred in the steps
  that ran.
- **Stop condition triggered:** Step 3 "dataset absent" → blocker, per instructions. Evidence:
  `logs/step3_data_manifest.log` §3a, `logs/step3_1m_blocker.log`,
  `configs/bigann1m.validation_criteria.json`.
- The only negative result is the *pre-fix* read-path behaviour: pre-fix negative-control
  abort in `~ClusterReader()` (gdb backtrace in `logs/step2_readpath_test.log`).

---

## 7. Blocker summary / next steps

1. **Provide the real BigANN1M corpus** (with provenance) on the server, then run
   `scripts/make_data_manifest.py --expect-n 1000000 --expect-d 128` and the criteria in
   `configs/bigann1m.validation_criteria.json`.
2. Re-check whether 1M fits the 5 GiB / 30-min envelope; the pairs text dump (~4.6 GB) is the
   binding constraint. External/streaming pair verification would be required.
3. Only then run normal + prefetch_off (+ one sanitizer build) with output-consistency and
   the 200-endpoint full-neighborhood GT protocol.
4. Physical-SSD I/O measurement remains a separate, unresolved requirement.

---

## Appendix — key files

```
workspace/gate5b/
  REPORT.md
  patches/clusterio_read_safety.patch          # read-path fix
  patches/manifest_refactor.patch              # oracle/scripts manifest refactor
  instrumented/DiskJoin/lib/ClusterIO.h        # patched (66c4f4dc…)
  tests/test_clusterio_read.cpp                # T1..T6
  tests/test_clusterio_read_negative.cpp       # pre-fix bug control
  scripts/make_data_manifest.py                # validated manifest generator
  scripts/run_100k_regression.sh               # bounded 100K regression
  scripts/regression_compare.py                # artifact comparator
  oracle/{independent_check,sample_endpoints,evaluate}.py, gt_calib.cpp  # manifest-driven
  configs/bigann1m.validation_criteria.json    # 1M blocking criteria
  data/manifest_bigann100k.json                # validated real-data manifest
  logs/step1_…   step2_…   step3_…             # all raw logs
  runs/step2_100k/{normal,prefetch_off,asan}/  # regression outputs
  runs/step3_oracle100k/                       # manifest-driven oracle validation
```

Reproduce Step 2: `bash workspace/gate5b/scripts/run_100k_regression.sh`
Reproduce Step 1: see `logs/step1_gate5ar_evidence_verification.log`.
