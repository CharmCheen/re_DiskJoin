#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <algorithm>
#include <vector>
static const size_t N = 100000, D = 128, REC = 4 + D;
int main(int argc, char** argv) {
    FILE* f = fopen(argv[1], "rb");
    std::vector<uint8_t> X(N * REC);
    if (fread(X.data(), 1, N * REC, f) != N * REC) return 1;
    fclose(f);
    // vector 0 content + stats
    printf("vec0: ");
    for (int k = 0; k < D; k++) printf("%d ", X[4 + k]);
    printf("\nvec0_nonzero=%d vec0_sum=%d\n", [&]{int c=0;for(int k=0;k<D;k++)c+=X[4+k]!=0;return c;}(),
           [&]{int c=0;for(int k=0;k<D;k++)c+=X[4+k];return c;}());
    // 20 smallest d2 from vector 0
    std::vector<int32_t> best;
    const uint8_t* a = &X[0];
    for (size_t j = 1; j < N; j++) {
        const uint8_t* b = &X[j * REC];
        int32_t s = 0;
        for (size_t k = 0; k < D; k++) { int32_t df = (int32_t)a[4+k] - (int32_t)b[4+k]; s += df * df; }
        best.push_back(s);
    }
    std::sort(best.begin(), best.end());
    printf("vec0 nearest-20 d2: ");
    for (int i = 0; i < 20; i++) printf("%d ", best[i]);
    printf("\nvec0 min d2 = %d (sqrt=%.2f)\n", best[0], sqrt((double)best[0]));
    // distribution of per-vector min-d2 over 200 sampled vectors for context
    std::vector<size_t> ids; long v;
    FILE* g = fopen(argv[2], "r");
    while (fscanf(g, "%ld", &v) == 1) ids.push_back((size_t)v);
    fclose(g);
    std::vector<int32_t> mins(ids.size());
    #pragma omp parallel for schedule(dynamic)
    for (int64_t s = 0; s < (int64_t)ids.size(); s++) {
        const uint8_t* a2 = &X[ids[s] * REC];
        int32_t mn = 1<<30;
        for (size_t j = 0; j < N; j++) {
            if (j == ids[s]) continue;
            const uint8_t* b = &X[j * REC];
            int32_t s2 = 0;
            for (size_t k = 0; k < D; k++) { int32_t df = (int32_t)a2[4+k] - (int32_t)b[4+k]; s2 += df * df; }
            if (s2 < mn) mn = s2;
        }
        mins[s] = mn;
    }
    std::sort(mins.begin(), mins.end());
    printf("per-vector min-d2 over %zu calib samples: p0=%d p25=%d p50=%d p75=%d p90=%d p99=%d max=%d\n",
           ids.size(), mins[0], mins[ids.size()/4], mins[ids.size()/2], mins[ids.size()*3/4],
           mins[(size_t)(ids.size()*0.9)], mins[(size_t)(ids.size()*0.99)], mins.back());
    return 0;
}
