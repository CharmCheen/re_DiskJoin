// Gate 3A/3C deterministic cache harness.
// Includes the UNMODIFIED reference Cache.h and compares the reference Cache
// against two independent oracles under the SAME cache model used by DiskJoin:
//   model: each request is always served (a miss triggers a fresh read);
//          on a miss the cache may optionally admit the requested bucket;
//          admission is beneficial only when the farthest resident's next use
//          is later than the incoming bucket's next use.
//   * dp_optimal : shortest-path DP over all cache-set states (small inputs)
//   * belady_rule: greedy farthest-next-use admission
// The reference Cache must match the DP optimum (Belady is optimal here).
//
// Bucket sizes differ in the real system, but the cache uses fixed slots
// (size = budget/4/length); the harness uses constant bucket_length = length,
// which is the model the implementation actually realises.
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <map>
#include <set>
#include <queue>
#include <limits>
#include <algorithm>
#include <random>
#include <climits>
#include "lib/Cache.h"

using namespace std;

// ---- independent DP-optimal over cache-set states (admission model) -------
struct DP {
    vector<int> seq;
    int n_items, C;
    map<set<int>, long long> cur;
    long long run() {
        cur.clear();
        cur[set<int>()] = 0;
        for (int x : seq) {
            map<set<int>, long long> nxt;
            auto relax = [&](const set<int>& s, long long c) {
                auto it = nxt.find(s);
                if (it == nxt.end() || it->second > c) nxt[s] = c;
            };
            for (auto& kv : cur) {
                const set<int>& s = kv.first; long long c = kv.second;
                if (s.count(x)) { relax(s, c); continue; }
                // miss: current served at cost 1
                long long cost = c + 1;
                relax(s, cost);                       // do not admit
                if ((int)s.size() < C) { set<int> s2 = s; s2.insert(x); relax(s2, cost); }
                else {                                // evict one, admit x
                    for (int y : s) { set<int> s2 = s; s2.erase(y); s2.insert(x); relax(s2, cost); }
                }
            }
            cur.swap(nxt);
        }
        long long best = numeric_limits<long long>::max();
        for (auto& kv : cur) best = min(best, kv.second);
        return best;
    }
};

// ---- independent Belady greedy (farthest-next-use admission) --------------
int belady_rule(const vector<int>& seq, int C) {
    int n = seq.size();
    // next-use position lists
    map<int, vector<int>> pos;
    for (int i = 0; i < n; i++) pos[seq[i]].push_back(i);
    map<int, int> ptr;
    set<int> cache;
    int misses = 0;
    auto nextUse = [&](int id, int t) -> int {
        auto& v = pos[id];
        int k = ptr[id];
        // advance to first occurrence > t
        while (k < (int)v.size() && v[k] <= t) k++;
        ptr[id] = k;
        return k < (int)v.size() ? v[k] : INT_MAX;
    };
    for (int t = 0; t < n; t++) {
        int x = seq[t];
        if (cache.count(x)) continue;
        misses++;
        if ((int)cache.size() < C) cache.insert(x);
        else {
            int victim = -1, far = -1;
            for (int y : cache) { int nu = nextUse(y, t); if (nu > far) { far = nu; victim = y; } }
            int nu_x = nextUse(x, t);
            if (far > nu_x) { cache.erase(victim); cache.insert(x); }
        }
    }
    return misses;
}

// ---- one random / deterministic trial ------------------------------------
struct Trial { vector<vector<size_t>> tasks; int n_items; };

static Trial make_random(int n_items, int ntasks, int per_task, unsigned seed) {
    mt19937 rng(seed);
    Trial tr; tr.n_items = n_items;
    tr.tasks.resize(ntasks);
    for (int i = 0; i < ntasks; i++)
        for (int j = 0; j < per_task; j++)
            tr.tasks[i].push_back(rng() % n_items);
    return tr;
}

static int ref_misses(const Trial& tr, int C, size_t length) {
    size_t budget = (size_t)4 * length * C;
    Cache cache(budget, length);
    cache.init(tr.tasks);
    vector<float> buf(length, 0.0f);
    for (auto& tk : tr.tasks)
        for (size_t id : tk)
            if (!cache.find(id, buf.data(), (unsigned)length))
                cache.push(id, buf.data(), (unsigned)length);
    return (int)(cache.total - cache.hit);
}

// Verify slot mapping + exact copy length: every find must return exactly the
// bytes pushed for that bucket (and not overwrite beyond bucket_length).
static int data_integrity() {
    const size_t L = 8;
    const int nb = 10;          // buckets; must be <= tasks.size()
    vector<int> sz(nb);
    vector<vector<float>> pat(nb);
    for (int b = 0; b < nb; b++) {
        sz[b] = 1 + (b % 8);
        for (int k = 0; k < sz[b]; k++) pat[b].push_back(1000.0f * b + k);
    }
    // tasks: one task per bucket id (so tasks.size() == nb == id space)
    vector<vector<size_t>> tasks(nb);
    mt19937 rng(987654321u);
    for (int t = 0; t < nb; t++)
        for (int j = 0; j < 6; j++) tasks[t].push_back(rng() % nb);

    int C = 3;
    size_t budget = (size_t)4 * L * C;
    Cache cache(budget, L);
    cache.init(tasks);
    vector<float> buf(L);
    const float SENT = 12345.0f;
    int errs = 0;
    for (auto& tk : tasks) {
        for (size_t id : tk) {
            fill(buf.begin(), buf.end(), SENT);
            bool hit = cache.find(id, buf.data(), (unsigned)sz[id]);
            if (hit) {
                for (int k = 0; k < sz[id]; k++) if (buf[k] != pat[id][k]) errs++;
                for (size_t k = sz[id]; k < L; k++) if (buf[k] != SENT) errs++;
            } else {
                for (int k = 0; k < sz[id]; k++) buf[k] = pat[id][k]; // simulated read
                cache.push(id, buf.data(), (unsigned)sz[id]);
            }
        }
    }
    printf("data-integrity: copy/padding errors=%d %s\n", errs, errs == 0 ? "OK" : "FAIL");
    return errs == 0 ? 0 : 1;
}

int main() {
    size_t L = 8;
    int fails = 0;

    // 1. deterministic LRU-vs-Belady example (JR benchmark style)
    {
        vector<int> seq = {1,2,3,4,1,2,5,1,2,3,4,5};
        int C = 3;
        Trial tr; tr.n_items = 6;
        for (int x : seq) tr.tasks.push_back({(size_t)x});
        DP dp; dp.seq = seq; dp.n_items = 6; dp.C = C;
        long long opt = dp.run();
        int bel = belady_rule(seq, C);
        int rmiss = ref_misses(tr, C, L);
        printf("deterministic: opt=%lld belady=%d ref=%d %s\n", opt, bel, rmiss,
               (opt == bel && bel == rmiss) ? "OK" : "FAIL");
        if (!(opt == bel && bel == rmiss)) fails++;
    }

    // 2. random trials across capacities; ref must equal DP optimum
    int cases = 0;
    for (unsigned seed = 1; seed <= 60; seed++) {
        int n_items = 2 + (seed % 5);            // 2..6
        int ntasks = n_items + 1 + (seed % 3);   // ids < tasks.size() (API contract)
        int per = 1 + (seed % 3);
        Trial tr = make_random(n_items, ntasks, per, seed * 7919u);
        // flatten for the independent oracles
        vector<int> seq;
        for (auto& tk : tr.tasks) for (size_t id : tk) seq.push_back((int)id);
        for (int C = 1; C <= n_items + 1; C++) {
            DP dp; dp.seq = seq; dp.n_items = n_items; dp.C = C;
            long long opt = dp.run();
            int bel = belady_rule(seq, C);
            int rmiss = ref_misses(tr, C, L);
            cases++;
            if (rmiss != (int)opt) {
                printf("MISMATCH seed=%u C=%d ref=%d opt=%lld belady=%d seq=[", seed, C, rmiss, opt, bel);
                for (int x : seq) printf("%d ", x);
                printf("]\n");
                fails++;
                if (fails > 20) { printf("too many failures, aborting\n"); return 2; }
            }
        }
    }
    printf("random cases=%d fails=%d\n", cases, fails);

    fails += data_integrity();

    // 3. large no-eviction sanity: capacity >= distinct buckets => every
    //    first-time access is a miss, repeats are hits.
    {
        Trial tr = make_random(50, 200, 3, 12345u);
        vector<int> seq;
        for (auto& tk : tr.tasks) for (size_t id : tk) seq.push_back((int)id);
        int C = 64; // >= 50 distinct
        int rmiss = ref_misses(tr, C, L);
        set<int> seen; int exp_miss = 0;
        for (int x : seq) { if (!seen.count(x)) { seen.insert(x); exp_miss++; } }
        printf("no-eviction: ref_miss=%d expected=%d %s\n", rmiss, exp_miss,
               rmiss == exp_miss ? "OK" : "FAIL");
        if (rmiss != exp_miss) fails++;
    }

    printf("CACHE_HARNESS %s (fails=%d)\n", fails == 0 ? "PASS" : "FAIL", fails);
    return fails == 0 ? 0 : 1;
}
