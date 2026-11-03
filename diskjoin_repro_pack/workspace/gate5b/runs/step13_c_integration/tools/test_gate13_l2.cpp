// Step 13 unit test for lib/gate13_l2.h.
//
// Proves the blocked fixed-128 kernel is BIT-IDENTICAL to utils::L2Sqr
// (which dispatches to L2SqrFloatAVX512 at d=128) across:
//   * random vectors, blocks of every size 1..16 and multi-block tails,
//   * deliberately UNALIGNED v1/v2 offsets (alignment / boundary access),
//   * the strict-threshold boundary: a distance exactly == 73984.0f (=272^2)
//     must compare `< 73984` FALSE, and a just-below value must pass,
//   * an empty block (n == 0) must be a no-op (empty-bucket path).
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <vector>
#include <random>
#include "lib/gate13_l2.h"

static uint32_t fb(float x) { uint32_t u; memcpy(&u, &x, 4); return u; }

int main() {
    const size_t d = 128;
    std::mt19937 rng(20261103u);
    std::uniform_real_distribution<float> ud(-1000.0f, 1000.0f);
    long fails = 0, checks = 0;

    const int N = 4096;
    std::vector<std::vector<float>> V(N);
    for (int i = 0; i < N; i++) {
        V[i].resize(d + 1);
        for (size_t k = 0; k < d + 1; k++) V[i][k] = ud(rng);
    }

    // 1) random vectors; block sizes span full blocks and tails; unaligned.
    for (int trial = 0; trial < 400; trial++) {
        const float* v1 = V[trial % N].data() + (trial & 1);
        int M = 1 + (int)(rng() % 40);
        std::vector<const float*> v2s(M);
        for (int i = 0; i < M; i++) v2s[i] = V[rng() % N].data() + ((i + trial) & 1);
        std::vector<float> got(M);
        int off = 0;
        while (off < M) {
            int n = std::min(16, M - off);
            gate13_l2sq_block128(v1, v2s.data() + off, n, got.data() + off);
            off += n;
        }
        for (int i = 0; i < M; i++) {
            float ref = utils::L2Sqr(v1, v2s[i], &d);
            checks++;
            if (fb(ref) != fb(got[i])) {
                if (fails < 5) printf("MISMATCH trial=%d i=%d ref=%08x got=%08x\n", trial, i, fb(ref), fb(got[i]));
                fails++;
            }
        }
    }

    // 2) strict-threshold boundary: exactly 73984 = 272^2
    {
        std::vector<float> a(d, 0.0f), b(d, 0.0f), c(d, 0.0f);
        b[0] = 272.0f;        // difference^2 = 73984 exactly
        c[0] = 271.9999f;     // just below
        float out = 0, out2 = 0;
        const float* bp = b.data(); const float* cp = c.data();
        gate13_l2sq_block128(a.data(), &bp, 1, &out);
        gate13_l2sq_block128(a.data(), &cp, 1, &out2);
        float ref = utils::L2Sqr(a.data(), b.data(), &d);
        printf("boundary : got=%.9g (%08x) ref=%.9g (%08x)  strict<73984 got=%d ref=%d\n",
               out, fb(out), ref, fb(ref), out < 73984.0f, ref < 73984.0f);
        printf("just-below: got=%.9g            strict<73984 got=%d\n", out2, out2 < 73984.0f);
        checks += 3;
        if (fb(out) != fb(ref)) fails++;
        if (!(out == 73984.0f)) { printf("expected exactly 73984.0f\n"); fails++; }
        if (out < 73984.0f) { printf("expected strict < to be FALSE at the boundary\n"); fails++; }
        if (!(out2 < 73984.0f)) { printf("expected just-below to pass\n"); fails++; }
    }

    // 3) empty block (empty bucket) must not dereference
    {
        const float* dummy = nullptr;
        float o = 123.0f;
        gate13_l2sq_block128(V[0].data(), &dummy, 0, &o);
        printf("empty block n=0: ok, out untouched=%.1f\n", o);
        if (o != 123.0f) fails++;
    }

    printf("checks=%ld fails=%ld => %s\n", checks, fails, fails ? "FAIL" : "PASS");
    return fails ? 1 : 0;
}
