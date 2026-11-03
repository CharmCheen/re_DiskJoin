#pragma once

// [GATE13] Fixed-128 blocked squared-L2 kernel for the join compute loop.
//
// This is the step12 "version C" kernel made usable inside DiskJoin: for a
// fixed 128-dim vector `v1`, compute the squared L2 distance to a small block
// of `v2` vectors while keeping v1's eight 512-bit lanes (8 zmm) in registers
// across the whole block, so v1 is loaded once per block instead of once per
// candidate.
//
// It is BIT-IDENTICAL to utils::L2SqrFloatAVX512 for d == 128: the operation
// order is reproduced exactly (eight {loadu, subps, fmadd} groups over 16
// lanes each, then the same pairwise narrowing and HsumFloat128 tail). No new
// fast-math option is enabled and no accumulation order is changed.
//
// Only valid for d == 128; the caller (DiskJoin.h) only selects this path when
// the runtime dimension is exactly 128. All other dimensions keep the original
// utils::L2Sqr path unchanged.

#include <cstddef>
#include <immintrin.h>
#include "../utils/dist_func.h"   // utils::HsumFloat128

#define GATE13_BLK 16

static inline void gate13_l2sq_block128(const float* __restrict__ v1,
                                        const float* const* __restrict__ v2s,
                                        int n, float* __restrict__ out) {
    // Hoist v1 once per block: eight 16-lane groups == 128 floats.
    __m512 a0 = _mm512_loadu_ps(v1 + 0),   a1 = _mm512_loadu_ps(v1 + 16),
           a2 = _mm512_loadu_ps(v1 + 32),  a3 = _mm512_loadu_ps(v1 + 48),
           a4 = _mm512_loadu_ps(v1 + 64),  a5 = _mm512_loadu_ps(v1 + 80),
           a6 = _mm512_loadu_ps(v1 + 96),  a7 = _mm512_loadu_ps(v1 + 112);
    for (int b = 0; b < n; b++) {
        const float* v2 = v2s[b];
        __m512 s = _mm512_setzero_ps(), x;
        x = _mm512_sub_ps(a0, _mm512_loadu_ps(v2 + 0));   s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a1, _mm512_loadu_ps(v2 + 16));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a2, _mm512_loadu_ps(v2 + 32));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a3, _mm512_loadu_ps(v2 + 48));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a4, _mm512_loadu_ps(v2 + 64));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a5, _mm512_loadu_ps(v2 + 80));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a6, _mm512_loadu_ps(v2 + 96));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a7, _mm512_loadu_ps(v2 + 112)); s = _mm512_fmadd_ps(x, x, s);
        // Same narrowing as L2SqrFloatAVX512 at dim == 128:
        //   sum256 = lo256(sum512) + hi256(sum512)
        //   sum128 = lo128(sum256) + hi128(sum256)
        //   return HsumFloat128(sum128)
        __m256 s256 = _mm256_add_ps(_mm512_castps512_ps256(s), _mm512_extractf32x8_ps(s, 1));
        __m128 s128 = _mm_add_ps(_mm256_castps256_ps128(s256), _mm256_extractf128_ps(s256, 1));
        out[b] = utils::HsumFloat128(s128);
    }
}
