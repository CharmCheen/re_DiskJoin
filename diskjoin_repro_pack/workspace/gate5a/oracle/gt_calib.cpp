// Gate 5A: exact integer calibration + brute-force GT for BigANN100K.
//
// Standalone helper (new isolated tool, NOT part of the DiskJoin source).
// All distance computations are EXACT integer arithmetic:
//   data are uint8 in [0,255]^128 -> per-dim |diff| <= 255, diff^2 <= 65025,
//   sum over 128 dims <= 8,323,200 < 2^31 -> int32 is exact, no rounding.
// The join binary compares dist < (float)sqrt(radius)^2; with radius = m^2
// (m <= 4095) and integer data, the float32 chain is exact as well, so the
// GT here uses the identical strict '<' on the identical integer values.
//
// Modes:
//   calib <bvecs> <ids_file>
//     For each candidate m: per-sample neighbour counts (excluding self)
//     -> mean / median / min / max / frac_empty, plus |N(0)| when vector 0
//        is in the id list. Single pass, per-sample counts for a fixed
//        candidate list (see CAND list below).
//   gt <bvecs> <endpoints_file> <m> <out_file>
//     For each endpoint e: all j != e with d2(e,j) < m*m, written as
//     "e k id1 id2 ...". Endpoint 0 gives the config `gt` value.
//
// Build: g++ -O2 -fopenmp -o gt_calib gt_calib.cpp
// Run with OMP_NUM_THREADS<=4.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <algorithm>
#include <vector>
#include <string>

static const size_t N = 100000, D = 128, REC = 4 + D;

static void load_bvecs(const char* fn, std::vector<uint8_t>& X) {
    FILE* f = fopen(fn, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", fn); exit(1); }
    X.resize(N * REC);
    if (fread(X.data(), 1, N * REC, f) != N * REC) {
        fprintf(stderr, "short read on %s\n", fn); exit(1);
    }
    fclose(f);
    for (size_t i = 0; i < N; i++) {
        uint32_t h; memcpy(&h, &X[i * REC], 4);
        if (h != D) { fprintf(stderr, "bad header at %zu: %u\n", i, h); exit(1); }
    }
}

static inline int32_t d2(const uint8_t* a, const uint8_t* b) {
    int32_t s = 0;
    for (size_t k = 0; k < D; k++) {
        int32_t df = (int32_t)a[k] - (int32_t)b[k];
        s += df * df;
    }
    return s;
}

static std::vector<size_t> read_ids(const char* fn) {
    FILE* f = fopen(fn, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", fn); exit(1); }
    std::vector<size_t> ids; long v; 
    while (fscanf(f, "%ld", &v) == 1) ids.push_back((size_t)v);
    fclose(f);
    return ids;
}

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s calib <bvecs> <ids_file> | gt <bvecs> <endpoints_file> <m> <out_file>\n", argv[0]);
        return 1;
    }
    std::string mode = argv[1];
    std::vector<uint8_t> X;
    load_bvecs(argv[2], X);

    if (mode == "calib") {
        std::vector<size_t> ids = read_ids(argv[3]);
        const int CAND[] = {262,264,266,268,270,272,274,276,280};
        const size_t NC = sizeof(CAND) / sizeof(CAND[0]);
        std::vector<std::vector<uint32_t>> cnt(NC, std::vector<uint32_t>(ids.size(), 0));
        int64_t have0 = -1;
        for (size_t s = 0; s < ids.size(); s++) if (ids[s] == 0) have0 = (int64_t)s;
        #pragma omp parallel for schedule(dynamic)
        for (int64_t s = 0; s < (int64_t)ids.size(); s++) {
            const uint8_t* a = &X[ids[s] * REC];
            for (size_t j = 0; j < N; j++) {
                int32_t v = d2(a, &X[j * REC]);
                for (size_t c = 0; c < NC; c++)
                    if (v < CAND[c] * CAND[c]) cnt[c][s]++;
            }
            for (size_t c = 0; c < NC; c++) cnt[c][s]--; // exclude self (d2==0)
        }
        printf("samples=%zu\n", ids.size());
        printf("%6s %10s %8s %8s %8s %8s %10s %9s\n",
               "m", "m^2", "mean", "median", "min", "max", "frac_empty", "|N(0)|");
        for (size_t c = 0; c < NC; c++) {
            std::vector<uint32_t> v = cnt[c];
            std::sort(v.begin(), v.end());
            double mean = 0; size_t empty = 0;
            for (uint32_t x : v) { mean += x; if (x == 0) empty++; }
            mean /= v.size();
            uint32_t n0 = 0;
            if (have0 >= 0) n0 = cnt[c][have0];
            printf("%6d %10d %8.2f %8u %8u %8u %10.4f %9u\n",
                   CAND[c], CAND[c] * CAND[c], mean,
                   v.empty() ? 0 : v[v.size() / 2], v.empty() ? 0 : v.front(),
                   v.empty() ? 0 : v.back(), v.empty() ? 0.0 : (double)empty / v.size(), n0);
        }
        return 0;
    } else if (mode == "gt") {
        if (argc < 6) { fprintf(stderr, "gt mode needs <endpoints> <m> <out>\n"); return 1; }
        std::vector<size_t> ids = read_ids(argv[3]);
        int m = atoi(argv[4]);
        if (m <= 0 || m > 4095) { fprintf(stderr, "m must be in [1,4095]\n"); return 1; }
        int32_t thr = m * m; // exact int32, same strict '<' as the binary's exact float32 chain
        FILE* out = fopen(argv[5], "w");
        if (!out) { fprintf(stderr, "cannot open %s\n", argv[5]); return 1; }
        std::vector<std::vector<uint32_t>> nb(ids.size());
        #pragma omp parallel for schedule(dynamic)
        for (int64_t s = 0; s < (int64_t)ids.size(); s++) {
            const uint8_t* a = &X[ids[s] * REC];
            for (size_t j = 0; j < N; j++) {
                if (j == ids[s]) continue;
                if (d2(a, &X[j * REC]) < thr) nb[s].push_back((uint32_t)j);
            }
        }
        size_t tot = 0;
        for (size_t s = 0; s < ids.size(); s++) {
            std::sort(nb[s].begin(), nb[s].end());
            tot += nb[s].size();
            fprintf(out, "%zu %zu", ids[s], nb[s].size());
            for (uint32_t j : nb[s]) fprintf(out, " %u", j);
            fprintf(out, "\n");
        }
        fclose(out);
        fprintf(stderr, "gt: endpoints=%zu m=%d thr=%d total_pairs=%zu mean_neighbors=%.3f\n",
                ids.size(), m, thr, tot, (double)tot / ids.size());
        return 0;
    }
    fprintf(stderr, "unknown mode %s\n", mode.c_str());
    return 1;
}
