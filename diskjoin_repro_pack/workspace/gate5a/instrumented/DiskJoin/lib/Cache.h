#pragma once

#include "../utils/utils.h"
#include "../utils/heap.h"
#include "string.h"
#include <cstdlib>
#include <cstdio>
#include <fstream>

struct Cache {
    size_t budget;
    size_t size;
    size_t length;
    float* data;

    size_t filled;
    size_t hit;
    size_t total;
    // [GATE4A] mechanism counters: cold admits, true evictions, rejected
    // pushes (cache full and new bucket's next use is later than victim's).
    size_t admit;
    size_t evict;
    size_t reject;
    // [GATE4B1] replacement policy in force:
    //   0 = belady_reject (default, original Cache behaviour)
    //   1 = belady_forced (forced load, farthest-next-use victim)
    //   2 = lru_forced    (forced load, least-recently-used victim)
    size_t g4b1_policy;
    std::ofstream g4a_trace; // [GATE4A] optional access/eviction trace
    updateable_heap<size_t, size_t, std::greater<size_t>> priority;
    std::vector<int> address_table;
    std::vector<size_t> ptr;
    std::vector<std::vector<size_t>> iters;

    Cache(size_t budget, size_t length): budget(budget), length(length) {
        size = budget / 4 / length;
        // [GATE4B1] env-gated capacity override: changes ONLY the number of
        // cache slots. Bucketization, the task graph, the Gorder window and
        // the ClusterWriter buffer all derive from mem_budget on other code
        // paths and are untouched by this override (verified by task-multiset
        // / pair-set identity runs). Unset -> budget-derived capacity,
        // reference behaviour unchanged.
        size_t g4b1_capacity_default = size;
        const char* g4b1_cap_env = getenv("GATE4B1_CAPACITY");
        if (g4b1_cap_env) {
            long g4b1_cap = strtol(g4b1_cap_env, nullptr, 10);
            if (g4b1_cap <= 0) {
                fprintf(stderr, "[gate4b1] invalid GATE4B1_CAPACITY=%s\n", g4b1_cap_env);
                exit(1);
            }
            size = (size_t)g4b1_cap;
        }
        // [GATE4B1] env-gated policy selector. All policies share the same
        // access sequence (find order is fixed by the task graph), capacity,
        // initial state and miss definition; they differ only in the push
        // decision and in what the priority heap encodes:
        //   belady_reject  (default) - original: cold-admit; evict the
        //                  farthest-next-use resident iff its next use is
        //                  strictly later than the incoming's, else reject.
        //   belady_forced  - forced load (no reject branch), victim =
        //                  farthest-next-use resident (next-use keys).
        //   lru_forced     - forced load, victim = least-recently-used
        //                  resident. Recency is encoded as SIZE_MAX - access
        //                  index, so the largest key = oldest access = top
        //                  of this same max-heap (the encoding LRUCache
        //                  below already uses with its total-cnt key).
        g4b1_policy = 0;
        const char* g4b1_policy_env = getenv("GATE4B1_POLICY");
        if (g4b1_policy_env) {
            if (strcmp(g4b1_policy_env, "belady_reject") == 0) g4b1_policy = 0;
            else if (strcmp(g4b1_policy_env, "belady_forced") == 0) g4b1_policy = 1;
            else if (strcmp(g4b1_policy_env, "lru_forced") == 0) g4b1_policy = 2;
            else {
                fprintf(stderr, "[gate4b1] unknown GATE4B1_POLICY=%s (expected belady_reject|belady_forced|lru_forced)\n", g4b1_policy_env);
                exit(1);
            }
        }
        data = new float[length * size];
        priority = updateable_heap<size_t, size_t, std::greater<size_t>>(size + 1);
        filled = 0;
        hit = 0;
        total = 0;
        admit = 0;
        evict = 0;
        reject = 0;
        if (g4b1_cap_env || g4b1_policy_env) {
            fprintf(stderr, "[gate4b1] policy=%s capacity=%zu capacity_default=%zu\n",
                    g4b1_policy == 0 ? "belady_reject"
                    : (g4b1_policy == 1 ? "belady_forced" : "lru_forced"),
                    size, g4b1_capacity_default);
        }
        // [GATE4A] env-gated trace: one line per access ("A seq id hit") and
        // per push ("P seq id admit|evict|reject victim"). find/push are only
        // called from the serial section of DiskJoin::search, so no locking
        // is needed.
        if (getenv("GATE4A_CACHE_TRACE")) {
            g4a_trace.open(getenv("GATE4A_CACHE_TRACE"));
        }
    }

    void init(std::vector<std::vector<size_t>> tasks, size_t n = 0) {
        if (n == 0) n = tasks.size();
        address_table = std::vector<int>(n, -1);
        ptr.resize(n);
        iters.resize(n);
        size_t num = 0;
        for (size_t i = 0; i < tasks.size(); i++) {
            for (size_t id : tasks[i]) {
                iters[id].push_back(num++);
            }
        }
        for (size_t i = 0; i < n; i++) iters[i].push_back(std::numeric_limits<size_t>::max());
    }

    inline bool find(size_t id, float* buffer, unsigned bucket_length) {
        total++;
        ptr[id]++;
        if (address_table[id] == -1) {
            if (g4a_trace.is_open()) g4a_trace << "A " << total << " " << id << " 0\n";
            return false;
        }
        hit++;
        // [GATE4B1] heap key: next-use position (Belady policies) or recency
        // encoding (LRU). total was already incremented, so SIZE_MAX - total
        // is unique and strictly decreasing over the run (same encoding as
        // LRUCache), making the max-heap top the least-recently-used resident.
        if (g4b1_policy == 2) {
            priority.update(std::make_pair(id, std::numeric_limits<size_t>::max() - total));
        } else {
            priority.update(std::make_pair(id, iters[id][ptr[id]]));
        }
        memcpy(buffer, data + address_table[id] * length, bucket_length * sizeof(float));
        if (g4a_trace.is_open()) g4a_trace << "A " << total << " " << id << " 1\n";
        return true;
    }

    inline void push(size_t id, float* buffer, unsigned bucket_length) {
        // [GATE4B1] heap key at push time (see find()): next-use position
        // for the Belady policies, recency encoding for LRU.
        size_t g4b1_key = (g4b1_policy == 2)
            ? (std::numeric_limits<size_t>::max() - total)
            : iters[id][ptr[id]];
        if (filled < size) {
            address_table[id] = filled;
            memcpy(data + address_table[id] * length, buffer, bucket_length * sizeof(float));
            priority.add(std::make_pair(id, g4b1_key));
            filled++;
            admit++;
            if (g4a_trace.is_open()) g4a_trace << "P " << total << " " << id << " admit -1\n";
        } else if (g4b1_policy == 0 && !(priority.top().second > iters[id][ptr[id]])) {
            // [GATE4B1] original belady_reject branch, condition verbatim:
            // keep the residents when the farthest next use is NOT strictly
            // later than the incoming bucket's next use.
            reject++;
            if (g4a_trace.is_open()) g4a_trace << "P " << total << " " << id << " reject -1\n";
        } else {
            // [GATE4B1] evict branch: forced load for belady_forced/lru_forced
            // (no reject); victim = heap top = farthest next use (policies
            // 0/1) or least recently used (policy 2).
            auto g4a_victim = priority.top().first;
            memcpy(data + address_table[g4a_victim] * length, buffer, bucket_length * sizeof(float));
            address_table[id] = address_table[g4a_victim];
            address_table[g4a_victim] = -1;
            priority.pop();
            priority.add(std::make_pair(id, g4b1_key));
            evict++;
            if (g4a_trace.is_open()) g4a_trace << "P " << total << " " << id << " evict " << g4a_victim << "\n";
        }
    }

    // [GATE4A] env-gated mechanism statistics (print-only).
    void g4a_stats() {
        if (getenv("GATE4A_STATS")) {
            fprintf(stderr, "[gate4a-cache] capacity_slots=%zu length=%zu budget_bytes=%zu filled=%zu total=%zu hit=%zu miss=%zu admit=%zu evict=%zu reject=%zu\n",
                    size, length, budget, filled, total, hit, total - hit, admit, evict, reject);
        }
    }

    ~Cache() {
        delete[] data;
    }
};

struct LRUCache {
    size_t budget;
    size_t size;
    size_t length;
    float* data;

    size_t filled;
    size_t hit;
    size_t total;
    size_t cnt;
    updateable_heap<size_t, size_t, std::greater<size_t>> priority;
    std::vector<int> address_table;

    LRUCache(size_t budget, size_t length): budget(budget), length(length) {
        size = budget / 4 / length;
        data = new float[length * size];
        priority = updateable_heap<size_t, size_t, std::greater<size_t>>(size + 1);
        filled = 0;
        hit = 0;
        total = 0;
        cnt = 0;
    }

    void init(std::vector<std::vector<size_t>> tasks) {
        auto n = tasks.size();
        address_table = std::vector<int>(n, -1);
        for (size_t i = 0; i < n; i++) total += tasks[i].size();
    }

    inline bool find(size_t id, float* buffer, unsigned bucket_length) {
        cnt++;
        if (address_table[id] == -1) return false;
        hit++;
        priority.update(std::make_pair(id, total - cnt));
        memcpy(buffer, data + address_table[id] * length, bucket_length * sizeof(float));
        return true;
    }

    inline void push(size_t id, float* buffer, unsigned bucket_length) {
        if (filled < size) {
            address_table[id] = filled;
            memcpy(data + address_table[id] * length, buffer, bucket_length * sizeof(float));
            priority.add(std::make_pair(id, total - cnt));
            filled++;
        } else {
            memcpy(data + address_table[priority.top().first] * length, buffer, bucket_length * sizeof(float));
            address_table[id] = address_table[priority.top().first];
            address_table[priority.top().first] = -1;
            priority.pop();
            priority.add(std::make_pair(id, total - cnt));
        }
    }

    ~LRUCache() {
        delete[] data;
    }
};

void simulate_cache(std::vector<std::vector<size_t>> tasks, size_t n, size_t size) {
   size_t CACHE_SIZE = size;
   std::vector<unsigned> cache(CACHE_SIZE);
   std::vector<int> address_table(n, -1);

   std::vector<unsigned> ptr(n);
   std::vector<std::vector<unsigned>> iters(n);
   unsigned num = 0;
   for (size_t i = 0; i < n; i++) {
      for (unsigned id : tasks[i]) {
        iters[id].push_back(num++);
      }
   }
   for (size_t i = 0; i < n; i++) iters[i].push_back(std::numeric_limits<unsigned>::max());

   updateable_heap<unsigned, unsigned, std::greater<unsigned>> priority(CACHE_SIZE + 1);

   unsigned cache_hit = 0, total = 0;
   unsigned filled = 0;
   for (size_t i = 0; i < n; i++) {
      for (unsigned id : tasks[i]) {
         total++;
         ptr[id]++;
         if (address_table[id] == -1) {
            if (filled < CACHE_SIZE) {
               cache[filled] = id;
               address_table[id] = filled;
               priority.add(std::make_pair(id, iters[id][ptr[id]]));
               filled++;
            } else if (priority.top().second > iters[id][ptr[id]]) { 
               cache[address_table[priority.top().first]] = id;
               address_table[id] = address_table[priority.top().first];
               address_table[priority.top().first] = -1;
               priority.pop();
               priority.add(std::make_pair(id, iters[id][ptr[id]]));
            }
         } else {
            cache_hit++;
            priority.update(std::make_pair(id, iters[id][ptr[id]]));
         }
      }
   }

   std::cout << "[stat] total: " << total << ", cache hit: " << cache_hit << " " << 1.0 * cache_hit / total << "\n";
}

void simulate_cache_LRU(std::vector<std::vector<size_t>> tasks, size_t n, size_t size) {
   size_t CACHE_SIZE = size;
   std::vector<unsigned> cache(CACHE_SIZE);
   std::vector<int> address_table(n, -1);

   updateable_heap<unsigned, unsigned, std::greater<unsigned>> priority(CACHE_SIZE + 1);

   unsigned cache_hit = 0, total = 0, cnt = 0;
   for (size_t i = 0; i < n; i++) total += tasks[i].size();
   unsigned filled = 0;
   for (size_t i = 0; i < n; i++) {
      for (unsigned id : tasks[i]) {
         cnt++;
         if (address_table[id] == -1) {
            if (filled < CACHE_SIZE) {
               cache[filled] = id;
               address_table[id] = filled;
               priority.add(std::make_pair(id, total - cnt));
               filled++;
            } else { 
               cache[address_table[priority.top().first]] = id;
               address_table[id] = address_table[priority.top().first];
               address_table[priority.top().first] = -1;
               priority.pop();
               priority.add(std::make_pair(id, total - cnt));
            }
         } else {
            cache_hit++;
            priority.update(std::make_pair(id, total - cnt));
         }
      }
   }

   std::cout << "total: " << total << ", cache hit: " << cache_hit << " " << 1.0 * cache_hit / total << "\n";
} 