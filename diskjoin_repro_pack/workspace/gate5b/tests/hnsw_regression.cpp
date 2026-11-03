#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include "hnswlib.h"

int main() {
    const size_t d = 128;
    hnswlib::L2Space space(d);
    hnswlib::HierarchicalNSW<float> graph(&space, 256, 20, 100);
    std::vector<float> x(d, 0);
    x[0] = 9; // Post-list bits would form ID 1091567616 in the old lookahead.
    graph.addPoint(x.data(), 0);
    // An upper-level full list is its own 85-byte allocation (20 IDs + header + 1).
    {
        hnswlib::HierarchicalNSW<float> upper(&space, 4, 20, 100);
        upper.addPoint(x.data(), 0, 1);
        auto list = upper.get_linklist(0, 1);
        upper.setListCount(list, 20);
        auto p = reinterpret_cast<hnswlib::tableint*>(list + 1);
        for (size_t j = 0; j < 20; ++j) p[j] = 0;
        assert(upper.searchBaseLayer(0, x.data(), 1).size() == 1);
    }
    // Empty adjacency and one-past lookahead must not even read their operand.
    graph.prefetchNeighbor(nullptr, 0, 0);
    graph.prefetchNeighbor(nullptr, 0, 1);
    hnswlib::tableint one[] = {0};
    graph.prefetchNeighbor(one, 1, 1);
    hnswlib::tableint invalid[] = {std::numeric_limits<hnswlib::tableint>::max()};
    graph.prefetchNeighbor(invalid, 1, 0);
    auto single = graph.knnSearchBaseLayer(0, 1);
    assert(single.size() == 1 && single.top().second == 0);
    // Full level-0 table: its following float bits must never become an ID.
    auto links = graph.get_linklist0(0);
    auto ids = reinterpret_cast<hnswlib::tableint*>(links + 1);
    graph.setListCount(links, 40);
    for (size_t j = 0; j < 40; ++j) ids[j] = 0;
    assert(graph.knnSearchBaseLayer(0, 1).size() == 1);
    graph.setListCount(links, 1);
    ids[0] = invalid[0];
    bool rejected = false;
    try { graph.knnSearchBaseLayer(0, 1); }
    catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
    graph.setListCount(links, 41);
    rejected = false;
    try { graph.knnSearchBaseLayer(0, 1); }
    catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
    graph.setListCount(links, 0);
    // Deterministic construction covers upper layers and both search variants.
    uint32_t state = 1234567;
    for (size_t i = 1; i < 256; ++i) {
        for (auto& v : x) { state = state * 1664525u + 1013904223u; v = float(state % 256); }
        graph.addPoint(x.data(), i);
    }
    graph.radii.assign(256, 3000);
    graph.setEf(256);
    uint64_t digest = 0;
    for (size_t i = 0; i < 256; ++i) {
        auto q = graph.knnSearchBaseLayer(i, 24);
        while (!q.empty()) { digest = digest * 131 + q.top().second; q.pop(); }
        graph.rangeSearchBaseLayer(i, 272);
    }
    // Standard search and update/repair instantiate the remaining hint consumers.
    graph.searchKnn(0, 24);
    graph.addPoint(x.data(), 255);
    unsigned wanted[] = {255};
    graph.searchAll(x.data(), 1, wanted);
    std::vector<hnswlib::vl_type> visited(256);
    graph.prefetchNode(255, visited.data()); // +64 hint must be suppressed.
    std::cout << "hnsw regression digest=" << digest << '\n';
}
