// Step 12 — bounded task replay of the DiskJoin compute loop.
//
// Replays a few COMPLETE real tasks (chosen by exact candidate volume) on the
// REAL vectors, in the REAL working-buffer layout, with the REAL candidate
// order. Compares three compute-loop variants on identical input:
//   A: the original loop, distance through the mutable global function pointer
//      `dist_l2` (indirect call, out-of-line utils::L2Sqr);
//   B: same loop, direct call to the same implementation `utils::L2Sqr`
//      (fixed d = 128, inlinable in-TU);
//   C: same math, but candidates are computed in small blocks with vec1 held in
//      AVX-512 registers (blocked + operand reuse), then the ORIGINAL per-pair
//      judgment is applied to the block.
//
// Bit-identity is enforced by XOR-ing every distance's float bits (order
// independent) and hashing the emitted (min,max) pair set; candidate count,
// pass count, recall numerator and the strict `< 73984` boundary count must all
// match. The compiler is prevented from eliminating work by accumulating a
// distance checksum that is printed (and by the hashes in verify mode).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <chrono>
#include <algorithm>
#include <fcntl.h>
#include <unistd.h>
#include "utils/dist_func.h"

// Faithful external-linkage mutable global (same type/linkage as ClusterIO.h:20).
float (*dist_l2)(const void *, const void *, const void *) = utils::L2Sqr;

static const size_t D = 128;
static const int BLK = 16;

static inline uint32_t fb(float x) { uint32_t u; memcpy(&u, &x, 4); return u; }

struct Meta {
    size_t n = 0, d = 0, cluster_num = 0, max_points = 0, length = 0;
    std::vector<size_t> bucket_sizes;
    std::vector<size_t> file_pos;
    std::vector<std::vector<size_t>> asg;
};

static Meta load_meta(const char *path) {
    Meta m; std::ifstream f(path, std::ios::binary);
    if (!f) { fprintf(stderr, "cannot open meta %s\n", path); exit(2); }
    f.read((char *)&m.n, 8); f.read((char *)&m.d, 8);
    f.read((char *)&m.cluster_num, 8); f.read((char *)&m.max_points, 8);
    m.bucket_sizes.resize(m.cluster_num);
    f.read((char *)m.bucket_sizes.data(), 8 * m.cluster_num);
    std::vector<float> centroids(m.d * m.cluster_num);
    f.read((char *)centroids.data(), 4 * m.d * m.cluster_num);
    std::vector<float> radii(m.cluster_num);
    f.read((char *)radii.data(), 4 * m.cluster_num);
    m.asg.resize(m.cluster_num);
    for (size_t i = 0; i < m.cluster_num; i++) {
        m.asg[i].resize(m.bucket_sizes[i]);
        f.read((char *)m.asg[i].data(), 8 * m.bucket_sizes[i]);
    }
    m.length = m.max_points * m.d;
    size_t cumu = 0;
    m.file_pos.resize(m.cluster_num);
    for (size_t i = 0; i < m.cluster_num; i++) { m.file_pos[i] = cumu * 4 * m.d; cumu += m.bucket_sizes[i]; }
    return m;
}

struct Task { size_t target = 0; std::vector<size_t> nbrs; };

// raw tasks.txt: line i = "<slot> <target> <deg> <nc0=self> <nc1> ..."
static std::vector<Task> load_raw_tasks(const char *path) {
    std::vector<Task> ts; std::ifstream f(path); std::string line;
    while (std::getline(f, line)) {
        std::istringstream ss(line); size_t slot, target, deg;
        if (!(ss >> slot >> target >> deg)) continue;
        Task t; t.target = target;
        for (size_t i = 0; i < deg; i++) { size_t x; ss >> x; t.nbrs.push_back(x); }
        ts.push_back(t);
    }
    return ts;
}

static std::vector<size_t> load_selection(const char *path) {
    std::vector<size_t> slots; std::ifstream f(path); std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line); std::string lab; size_t slot, target, cand, deg, nt, cross;
        if (!(ss >> lab >> slot >> target >> cand >> deg >> nt >> cross)) continue;
        slots.push_back(slot);
    }
    return slots;
}

struct Stats {
    uint64_t ncand = 0, npass = 0, count = 0, eqbound = 0;
    uint64_t pairxor = 0, dxor = 0;
    double dsum = 0;
};

// Timed mode mirrors the real loop: one candidate counter (`dist_comp++`) and
// the threshold branch. Verify mode adds the order-independent distance-bit
// XOR, the strict `< 73984` boundary probe and the emitted-pair-set hash.
static inline void judge(float dist, size_t id1, size_t id2, float thr, Stats &st, bool hash) {
    st.ncand++;
    if (hash) {
        st.dxor ^= (uint64_t)fb(dist);
        st.dsum += dist;
        if (dist == 73984.0f) st.eqbound++;
    }
    if (dist < thr) {
        st.npass++;
        if (id1 % 100000 == 0) st.count++;
        if (id2 % 100000 == 0) st.count++;
        if (hash) {
            size_t a = id1 < id2 ? id1 : id2, b = id1 < id2 ? id2 : id1;
            st.pairxor ^= (uint64_t)a * 1000003ull + (uint64_t)b * 0x9e3779b97f4a7c15ull;
        }
    }
}

// ---- A: original structure, indirect call through dist_l2 ----
static void run_A(const Meta &m, const Task &t, const std::vector<float> &buf, float thr, Stats &st, bool hash) {
    const size_t nb = m.bucket_sizes[t.target];
    const size_t *tag = m.asg[t.target].data();
    const float *b0 = buf.data();
    const size_t length = m.length;
    for (size_t j = 0; j < nb; j++) {
        const size_t id1 = tag[j]; const float *v1 = b0 + j * D;
        for (size_t l = 0; l < nb; l++) {
            const size_t id2 = tag[l]; if (id2 >= id1) continue;
            float dist = dist_l2(v1, b0 + l * D, &D);
            judge(dist, id1, id2, thr, st, hash);
        }
        for (size_t k = 1; k < t.nbrs.size(); k++) {
            const size_t nc = t.nbrs[k]; const size_t sn = m.bucket_sizes[nc];
            const size_t *nag = m.asg[nc].data();
            const float *base = b0 + k * length;
            for (size_t l = 0; l < sn; l++) {
                const size_t id2 = nag[l];
                float dist = dist_l2(v1, base + l * D, &D);
                judge(dist, id1, id2, thr, st, hash);
            }
        }
    }
}

// ---- B: same structure, direct call to utils::L2Sqr (inlinable) ----
static void run_B(const Meta &m, const Task &t, const std::vector<float> &buf, float thr, Stats &st, bool hash) {
    const size_t nb = m.bucket_sizes[t.target];
    const size_t *tag = m.asg[t.target].data();
    const float *b0 = buf.data();
    const size_t length = m.length;
    for (size_t j = 0; j < nb; j++) {
        const size_t id1 = tag[j]; const float *v1 = b0 + j * D;
        for (size_t l = 0; l < nb; l++) {
            const size_t id2 = tag[l]; if (id2 >= id1) continue;
            float dist = utils::L2Sqr(v1, b0 + l * D, &D);
            judge(dist, id1, id2, thr, st, hash);
        }
        for (size_t k = 1; k < t.nbrs.size(); k++) {
            const size_t nc = t.nbrs[k]; const size_t sn = m.bucket_sizes[nc];
            const size_t *nag = m.asg[nc].data();
            const float *base = b0 + k * length;
            for (size_t l = 0; l < sn; l++) {
                const size_t id2 = nag[l];
                float dist = utils::L2Sqr(v1, base + l * D, &D);
                judge(dist, id1, id2, thr, st, hash);
            }
        }
    }
}

// ---- C: blocked, vec1 held in zmm registers across the block ----
static inline void l2_block_reuse(const float *v1, const float *const *v2s, int nb, float *out) {
    __m512 a0 = _mm512_loadu_ps(v1 + 0),  a1 = _mm512_loadu_ps(v1 + 16),
           a2 = _mm512_loadu_ps(v1 + 32), a3 = _mm512_loadu_ps(v1 + 48),
           a4 = _mm512_loadu_ps(v1 + 64), a5 = _mm512_loadu_ps(v1 + 80),
           a6 = _mm512_loadu_ps(v1 + 96), a7 = _mm512_loadu_ps(v1 + 112);
    for (int b = 0; b < nb; b++) {
        const float *v2 = v2s[b];
        __m512 s = _mm512_setzero_ps(), x;
        x = _mm512_sub_ps(a0, _mm512_loadu_ps(v2 + 0));   s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a1, _mm512_loadu_ps(v2 + 16));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a2, _mm512_loadu_ps(v2 + 32));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a3, _mm512_loadu_ps(v2 + 48));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a4, _mm512_loadu_ps(v2 + 64));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a5, _mm512_loadu_ps(v2 + 80));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a6, _mm512_loadu_ps(v2 + 96));  s = _mm512_fmadd_ps(x, x, s);
        x = _mm512_sub_ps(a7, _mm512_loadu_ps(v2 + 112)); s = _mm512_fmadd_ps(x, x, s);
        __m256 s256 = _mm256_add_ps(_mm512_castps512_ps256(s), _mm512_extractf32x8_ps(s, 1));
        __m128 s128 = _mm_add_ps(_mm256_castps256_ps128(s256), _mm256_extractf128_ps(s256, 1));
        out[b] = utils::HsumFloat128(s128);
    }
}

static void run_C(const Meta &m, const Task &t, const std::vector<float> &buf, float thr, Stats &st, bool hash) {
    const size_t nb = m.bucket_sizes[t.target];
    const size_t *tag = m.asg[t.target].data();
    const float *b0 = buf.data();
    const size_t length = m.length;
    const float *v2s[BLK]; size_t ids[BLK]; float out[BLK];
    for (size_t j = 0; j < nb; j++) {
        const size_t id1 = tag[j]; const float *v1 = b0 + j * D;
        int cnt = 0;
        for (size_t l = 0; l < nb; l++) {
            const size_t id2 = tag[l]; if (id2 >= id1) continue;
            v2s[cnt] = b0 + l * D; ids[cnt] = id2; cnt++;
            if (cnt == BLK) { l2_block_reuse(v1, v2s, cnt, out);
                for (int b = 0; b < cnt; b++) { judge(out[b], id1, ids[b], thr, st, hash); } cnt = 0; }
        }
        if (cnt) { l2_block_reuse(v1, v2s, cnt, out);
            for (int b = 0; b < cnt; b++) { judge(out[b], id1, ids[b], thr, st, hash); } }
        for (size_t k = 1; k < t.nbrs.size(); k++) {
            const size_t nc = t.nbrs[k]; const size_t sn = m.bucket_sizes[nc];
            const size_t *nag = m.asg[nc].data();
            const float *base = b0 + k * length;
            cnt = 0;
            for (size_t l = 0; l < sn; l++) {
                const size_t id2 = nag[l];
                v2s[cnt] = base + l * D; ids[cnt] = id2; cnt++;
                if (cnt == BLK) { l2_block_reuse(v1, v2s, cnt, out);
                    for (int b = 0; b < cnt; b++) { judge(out[b], id1, ids[b], thr, st, hash); } cnt = 0; }
            }
            if (cnt) { l2_block_reuse(v1, v2s, cnt, out);
                for (int b = 0; b < cnt; b++) { judge(out[b], id1, ids[b], thr, st, hash); } }
        }
    }
}

typedef void (*Runner)(const Meta &, const Task &, const std::vector<float> &, float, Stats &, bool);

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "usage: %s meta tasks_txt selection cluster_file [passes]\n", argv[0]); return 2; }
    const char *meta_path = argv[1], *tasks_path = argv[2], *sel_path = argv[3], *cluster_path = argv[4];
    int passes = argc > 5 ? atoi(argv[5]) : 5;

    Meta m = load_meta(meta_path);
    std::vector<Task> raw = load_raw_tasks(tasks_path);
    std::vector<size_t> sel = load_selection(sel_path);
    float eps = std::sqrt(73984.0f);
    float thr = eps * eps;
    printf("[replay] meta n=%zu d=%zu cluster_num=%zu max_points=%zu length=%zu\n",
           m.n, m.d, m.cluster_num, m.max_points, m.length);
    printf("[replay] epsilon=%.9g epsilon*epsilon=%.9g  threshold compare is STRICT dist < %.9g\n", eps, thr, thr);
    printf("[replay] eta: strict< boundary probe counts dist == 73984.0f exactly\n");

    int fd = open(cluster_path, O_RDONLY);
    if (fd < 0) { perror("open cluster"); return 2; }

    std::vector<const float *> v2temp;
    double total_bytes_read = 0;
    // load each selected task into its OWN real-layout buffer (slot0=target, slotk=neighbour k)
    std::vector<Task> sel_tasks; std::vector<std::vector<float>> bufs;
    for (size_t s : sel) {
        const Task &t = raw[s];
        std::vector<float> buf(t.nbrs.size() * m.length, 0.0f);
        for (size_t k = 0; k < t.nbrs.size(); k++) {
            size_t nc = t.nbrs[k]; size_t bytes = m.bucket_sizes[nc] * m.d * 4;
            ssize_t r = pread(fd, buf.data() + k * m.length, bytes, m.file_pos[nc]);
            if (r != (ssize_t)bytes) { fprintf(stderr, "pread fail nc=%zu\n", nc); return 2; }
            total_bytes_read += bytes;
        }
        printf("[replay] slot=%zu target=%zu deg=%zu n_target=%zu buffer_bytes=%zu (slots*%zu)\n",
               s, t.target, t.nbrs.size(), m.bucket_sizes[t.target], buf.size() * 4, m.length * 4);
        sel_tasks.push_back(t); bufs.push_back(std::move(buf));
    }
    close(fd);
    printf("[replay] total real bytes loaded into working buffers = %.0f\n", total_bytes_read);

    const char *names[3] = {"A", "B", "C"};
    Runner runners[3] = {run_A, run_B, run_C};

    // ---- correctness pass (with hashing) ----
    Stats cst[3];
    for (int v = 0; v < 3; v++) {
        Stats s;
        for (size_t i = 0; i < sel_tasks.size(); i++) runners[v](m, sel_tasks[i], bufs[i], thr, s, true);
        cst[v] = s;
        printf("[verify] %s ncand=%llu npass=%llu count=%llu eqbound=%llu dxor=%016llx pairxor=%016llx dsum=%.6f\n",
               names[v], (unsigned long long)s.ncand, (unsigned long long)s.npass, (unsigned long long)s.count,
               (unsigned long long)s.eqbound, (unsigned long long)s.dxor, (unsigned long long)s.pairxor, s.dsum);
    }
    bool ok = true;
    for (int v = 1; v < 3; v++) {
        if (cst[v].ncand != cst[0].ncand || cst[v].npass != cst[0].npass ||
            cst[v].count != cst[0].count || cst[v].eqbound != cst[0].eqbound ||
            cst[v].dxor != cst[0].dxor || cst[v].pairxor != cst[0].pairxor) ok = false;
    }
    printf("[verify] %s\n", ok ? "ALL THREE VERSIONS IDENTICAL (candidates, pass set, pair set, distance bits, boundary)"
                                : "*** MISMATCH BETWEEN VERSIONS ***");

    // ---- timing: round-robin, warmup pass then `passes` timed passes ----
    for (int v = 0; v < 3; v++) { Stats s; for (size_t i = 0; i < sel_tasks.size(); i++) runners[v](m, sel_tasks[i], bufs[i], thr, s, false); }
    std::vector<double> times[3];
    for (int p = 0; p < passes; p++) {
        for (int v = 0; v < 3; v++) {
            Stats s;
            auto t0 = std::chrono::steady_clock::now();
            for (size_t i = 0; i < sel_tasks.size(); i++) runners[v](m, sel_tasks[i], bufs[i], thr, s, false);
            auto t1 = std::chrono::steady_clock::now();
            double dt = std::chrono::duration<double>(t1 - t0).count();
            times[v].push_back(dt);
            printf("[time] pass=%d %s wall_s=%.6f ncand=%llu npass=%llu dsum=%.6f\n",
                   p, names[v], dt, (unsigned long long)s.ncand, (unsigned long long)s.npass, s.dsum);
        }
    }
    for (int v = 0; v < 3; v++) {
        std::vector<double> tt = times[v]; std::sort(tt.begin(), tt.end());
        double sum = 0; for (double x : tt) sum += x;
        printf("[summary] %s mean=%.6f min=%.6f median=%.6f max=%.6f passes=%d\n",
               names[v], sum / tt.size(), tt.front(), tt[tt.size() / 2], tt.back(), passes);
    }
    printf("[summary] added buffers for C: %d x (const float*) + %d x size_t + %d x float = %zu bytes (stack), plus 8 held zmm\n",
           BLK, BLK, BLK, (size_t)BLK * (sizeof(void *) + sizeof(size_t) + sizeof(float)));
    printf("[summary] vector reuse: vec1 is fixed across each inner segment; A/B reload both operands every call, C holds vec1's 8 zmm for the whole block\n");
    return ok ? 0 : 1;
}
