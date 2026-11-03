// Gate 4A deterministic Gorder window-behaviour harness.
//
// Builds small fixed task graphs (same shape as DiskJoin's: tasks[i][0]==i,
// neighbours j >= i), runs the REAL order_gorder() from the instrumented
// copy, and checks:
//   1. returned rank is a permutation of 0..n-1
//   2. order is the inverse permutation (DiskJoin usage order[perm[i]]=i)
//   3. task lists are preserved verbatim under the DiskJoin reorder
//      (slot i holds bucket order[i]'s list; head == order[i]; upper-triangle
//      neighbour invariant preserved; total edge count unchanged)
//   4. repeated calls give identical output (determinism)
// Window-removal counting itself is printed by the instrumented order_gorder
// when GATE4A_STATS=1 (this harness sets it); the expected count
// n - min(window, n) is verified from the log by the caller.
#include <cstdio>
#include <cstdlib>
#include <numeric>
#include <random>
#include <vector>
#include "Gorder.h"

static int failures = 0;

static void check_case(const char* name, std::vector<std::vector<size_t>> tasks, size_t window) {
    size_t n = tasks.size();
    std::vector<size_t> perm(n), order(n);
    std::vector<std::vector<size_t>> reordered(n);
    std::iota(perm.begin(), perm.end(), 0);
    // same call shape as lib/DiskJoin.h
    perm = order_gorder(tasks, window);
    for (size_t i = 0; i < n; i++) {
        reordered[perm[i]] = tasks[i];
        order[perm[i]] = i;
    }
    int perm_ok = 1, inv_ok = 1, head_ok = 1, upper_ok = 1, edges_ok = 1;
    std::vector<int> seen(n, 0);
    for (size_t i = 0; i < n; i++) {
        if (perm[i] >= n || seen[perm[i]]) perm_ok = 0; else seen[perm[i]] = 1;
        if (order[perm[i]] != i) inv_ok = 0;
    }
    size_t edges_before = 0, edges_after = 0;
    for (size_t i = 0; i < n; i++) {
        edges_before += tasks[i].size();
        if (!tasks[i].empty() && tasks[i][0] != i) head_ok = 0; // precondition
    }
    for (size_t i = 0; i < n; i++) {
        edges_after += reordered[i].size();
        if (reordered[i].empty()) continue;
        if (reordered[i][0] != order[i]) head_ok = 0;
        for (auto nc : reordered[i]) if (nc < order[i]) upper_ok = 0;
    }
    if (edges_before != edges_after) edges_ok = 0;
    // determinism: run again and compare
    std::vector<size_t> perm2 = order_gorder(tasks, window);
    int det_ok = perm2 == perm;
    int pass = perm_ok && inv_ok && head_ok && upper_ok && edges_ok && det_ok;
    if (!pass) failures++;
    printf("[gorder-test] %-16s n=%3zu window=%4zu perm_ok=%d inv_ok=%d head_ok=%d "
           "upper_ok=%d edges_ok=%d det_ok=%d edges=%zu => %s\n",
           name, n, window, perm_ok, inv_ok, head_ok, upper_ok, edges_ok, det_ok,
           edges_before, pass ? "PASS" : "FAIL");
}

int main() {
    setenv("GATE4A_STATS", "1", 1);

    { // chain: i -> {i, i+1}
        size_t n = 60;
        std::vector<std::vector<size_t>> t(n);
        for (size_t i = 0; i < n; i++) {
            t[i].push_back(i);
            if (i + 1 < n) t[i].push_back(i + 1);
        }
        check_case("chain", t, 3);
        check_case("chain", t, 30);
        check_case("chain", t, 100); // window >= n: no removals
        check_case("chain", t, 0);   // degenerate window
    }
    { // blocks of 8 (clique-ish upper-triangle blocks)
        size_t n = 64;
        std::vector<std::vector<size_t>> t(n);
        for (size_t i = 0; i < n; i++) {
            size_t base = (i / 8) * 8;
            for (size_t j = i; j < base + 8 && j < n; j++) t[i].push_back(j);
        }
        check_case("blocks8", t, 4);
        check_case("blocks8", t, 8);
        check_case("blocks8", t, 16);
    }
    { // star: hub 0 links to all; others self only
        size_t n = 50;
        std::vector<std::vector<size_t>> t(n);
        for (size_t j = 0; j < n; j++) t[0].push_back(j);
        for (size_t i = 1; i < n; i++) t[i].push_back(i);
        check_case("star", t, 2);
        check_case("star", t, 10);
    }
    { // seeded random upper-triangle dag
        std::mt19937 rng(12345);
        size_t n = 80;
        std::vector<std::vector<size_t>> t(n);
        for (size_t i = 0; i < n; i++) {
            t[i].push_back(i);
            for (size_t k = 0; k < 6 && i + 1 < n; k++) {
                size_t j = i + 1 + rng() % (n - i - 1);
                t[i].push_back(j);
            }
            std::sort(t[i].begin(), t[i].end());
            t[i].erase(std::unique(t[i].begin(), t[i].end()), t[i].end());
        }
        check_case("random-dag", t, 1);
        check_case("random-dag", t, 5);
        check_case("random-dag", t, 20);
        check_case("random-dag", t, 79);
    }
    { // single node; all-self
        std::vector<std::vector<size_t>> t1 = {{0}};
        check_case("single", t1, 0);
        size_t n = 30;
        std::vector<std::vector<size_t>> t2(n);
        for (size_t i = 0; i < n; i++) t2[i].push_back(i);
        check_case("all-self", t2, 7);
    }
    printf("GORDER_TEST %s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
