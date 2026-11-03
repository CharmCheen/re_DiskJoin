# BigANN1M data-acquisition plan (Gate 5B, deliverable 1)

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
Scope: `workspace/gate5b/` only. **No dataset body was downloaded in this round.**
This is a plan plus an executable, authorization-gated driver.

---

## 1. What "BigANN1M" means here (convention = the accepted 100K)

The accepted 100K subset was derived from the official IRISA/texmex SIFT1B base
using the site's own subset definition. The official page states verbatim:

> "For the largest set (ANN_SIFT1B), the groundtruth is provided for the whole set,
> but also for subsets of varying size. **These subsets are the n first vectors of
> the `bigann_base.bvecs` file** (n=1M,2M,5M,10M,20M,50M,100M,200M,500M,1B)."

Source: `http://corpus-texmex.irisa.fr/` (fetched this round).

Therefore **BigANN1M ≡ the first 1,000,000 records of `bigann_base.bvecs`**, exactly
the same first-N rule that produced the 100K subset. It is **not** a rescaled or
duplicated copy of the 100K data (`configs/bigann1m.validation_criteria.json` forbids
that).

`.bvecs` record layout (texmex format page): per record a 4-byte little-endian
dimension prefix (== 128) followed by 128 uint8. There is **no global header**.

| quantity | value | basis |
|---|---|---|
| n | 1,000,000 | official subset convention |
| d | 128 | SIFT descriptors |
| bvecs record size | 132 B (4 + 128) | texmex format |
| raw bvecs bytes | 132,000,000 B (125.9 MiB) | `n*(d+4)` |
| fbin bytes | 512,000,008 B (488.3 MiB) | `8 + n*d*4` |

---

## 2. Acquisition route (primary, preserves the 100K convention)

| field | value |
|---|---|
| URL | `ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz` |
| protocol | FTP only (HTTP mirror of the texmex host is not the source used for 100K) |
| server total | `Content-Length: 97941899519` B (91.2 GiB) — HEAD, this round |
| partial fetch | **Supported** — `Accept-ranges: bytes` (HEAD) and an actual 1-byte range request at offset 0 returned exactly 1 byte (this round, metadata-level; no body retained) |
| `Last-Modified` | `Wed, 16 Jun 2010 20:38:39 GMT` |
| record range | first 1,000,000 records = first `1,000,000 * 132 = 132,000,000` uncompressed bytes; fetched via an FTP byte range of the gz stream |
| network transfer | expected ≈ 97,941,900 B (93.4 MiB). Derived from the full-file ratio `97,941,899,519 / 132,000,000,000 = 0.7420`; a gzip stream's marginal ratio is stable, so 1M compressed ≈ `132,000,000 * 0.7420`. **Budget 128 MiB** (`134,217,728` B, Range `0-134217727`) for margin; if 1M records are not reached, extend the range and re-stream. |
| disk (transient + retained) | gz prefix ≤ 128 MiB (transient, deletable); `bigann1m.bvecs` 132,000,000 B; `bigann1m.fbin` 512,000,008 B. Retained ≈ 614 MiB; peak with gz ≈ 742 MiB. |
| conversion | deterministic bvecs→fbin: drop each 4-byte dim prefix, cast the 128 uint8 to float32, write `uint32 n, uint32 d` header then row-major float32. Implemented in `scripts/bvecs_to_fbin.py` (mirrors upstream `datasets.py`: `np.array([n,d],dtype=uint32).tofile` + `data.astype(float32).tofile`). |
| driver | `scripts/acquire_bigann1m.py` — plan-only by default; the actual fetch requires `--authorized` (not run this round). |

### 2.1 Exact commands (to be run only after authorization)

Plan / metadata probe (safe, no body) — **run this round**:

```
python3 -B scripts/acquire_bigann1m.py
```

Authorized acquisition (NOT run this round):

```
python3 -B scripts/acquire_bigann1m.py --authorized --keep-gz
python3 -B scripts/make_data_manifest.py --name bigann1m \
    --fbin data/bigann1m/bigann1m.fbin --bvecs data/bigann1m/bigann1m.bvecs \
    --expect-n 1000000 --expect-d 128 --out configs/manifest_bigann1m.json
python3 -B oracle/independent_check.py --manifest configs/manifest_bigann1m.json ...
```

The underlying fetch that `--authorized` issues is a single bounded range:

```
curl -sS -r 0-134217727 --max-time 900 \
     -o prefix.gz ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz
```

then a streaming gzip decompress that stops as soon as 1,000,000 records are parsed.

---

## 3. Provenance verification — what can and cannot be proven

The official MD5 list (`ftp://ftp.irisa.fr/local/texmex/corpus/MD5SUM`, tiny metadata
file, fetched this round) contains:

```
4346fa68813d71e7f3d75d2faba669ec  bigann_base.bvecs.gz
f40646ba10e152229818e82cd5bd84b2  bigann_gnd.tar.gz
69535458f804e99358afe4320e2e2c6a  bigann_learn.bvecs.gz
b5f61050d3c435911d54db122b5469b5  bigann_query.bvecs.gz
```

**The official MD5 covers the FULL 91.2 GiB file.** We fetch only a bounded prefix of
a truncated gzip stream, which (a) cannot reproduce the full-file MD5 and (b) cannot
be CRC-checked (gzip CRCs cover complete members only). So **no file hash we generate
can serve as official provenance**, and this plan does not treat it as such.

What is actually established, per the accepted 100K precedent:

1. **Authoritative URL + first-N convention** (the site's own definition) fix *what*
   the subset is.
2. **Partial-fetch integrity** replaces the missing CRC, as in Gate 5A:
   - gzip magic `1f 8b` present;
   - every record header equals 128 (record alignment across the whole prefix);
   - uint8 values within [0,255];
   - exact uint8→float32 roundtrip on sampled records.
3. **Local content pins** (SHA-256/MD5 of our prefix, bvecs, fbin) are recorded only
   to detect *local* corruption or drift — explicitly labelled as content pins, not
   provenance.

A future round *could* upgrade to true provenance by authorizing the 91.2 GiB full
download and checking the official MD5, but that is out of the current envelope and
is **not** proposed here.

### 3.1 Unverifiable / left unknown (stated honestly)

- **Byte-equivalence of any HTTP mirror is UNVERIFIED.** This round an HTTP mirror
  `https://dl.fbaipublicfiles.com/billion-scale-ann-benchmarks/bigann/base.1B.u8bin`
  returned `HTTP/2 200` with `content-length: 128000000008` (= `8 + 1e9*128`, the
  big-ann `.u8bin` format), whereas the `.fbin` variant returned 403 in the prior
  round. It is a **documented alternative**, but it uses a different host, format
  (u8bin vs bvecs) and crop convention (`download(..., max_size=...)` then patch
  header), so switching to it would change provenance and is not the plan.
- The prefix's marginal gz/raw ratio is **estimated** from the full-file ratio; the
  driver does not rely on it (it streams until 1,000,000 headers are confirmed, and
  the 128 MiB budget has margin).
- Fields not present in `curl -I` output (e.g. hash/size beyond Content-Length) are
  not claimed.
- No large download, no upstream script (`create_datasets.sh`), no cloud spend.

---

## 4. Container / structural verification after acquisition

`scripts/bvecs_to_fbin.py` (with `--check-only`) independently re-derives the same
structural facts, and `scripts/make_data_manifest.py` (validated in the prior round)
writes a machine-checked manifest. Negative controls required before use:

- a truncated bvecs (size not a positive multiple of 132) must be **rejected**;
- a wrong `--expect-n` must be **rejected**;
- a wrong per-record dimension header must be **rejected**.

`tests/test_bvecs_convert.py` exercises all three on synthetic data and passes
(§6), so the verifier is known to detect malformed input before it ever runs on the
real 1M file.

---

## 5. Risk / stop conditions

- If the compressed transfer needed to reach 1M records exceeds the authorized
  download budget, **stop** and request a raise; do not silently fetch more.
- If any structural check fails, **stop**; do not "repair" the prefix.
- If an HTTP mirror is used instead of the texmex FTP source, that is a provenance
  change and must be re-authorized and re-documented (it would no longer match the
  100K derivation chain).
- Using `workspace/gate5a/data/bigann_base.bvecs.gz.prefix24m` is forbidden as a
  substitute: it is a 24 MiB truncated gzip prefix (inner name `1milliard.p1.siftbin`)
  and is not a record-aligned 1M fbin/bvecs.

---

## 6. Evidence produced this round (deliverable 1)

| artifact | meaning |
|---|---|
| `logs/step7_data_acquisition_probe.log` | FTP HEAD, MD5SUM, 1-byte range test, HTTP-mirror HEAD, local prefix info |
| `logs/step7_acquire_plan.log` | `acquire_bigann1m.py` plan-only run (no body) |
| `logs/step7_converter_tests.log` | 4/4 converter tests pass (synthetic, no network) |
| `scripts/acquire_bigann1m.py` | authorization-gated acquisition driver |
| `scripts/bvecs_to_fbin.py` | deterministic converter + structural checker |
| `tests/test_bvecs_convert.py` | synthetic converter tests |
