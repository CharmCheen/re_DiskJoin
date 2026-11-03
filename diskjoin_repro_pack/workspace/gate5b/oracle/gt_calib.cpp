// Exact BigANN oracle. Record headers are consumed by the loader, never d2().
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Dataset {
    static const size_t d = 128;
    std::vector<uint8_t> values;
    size_t n() const { return values.size() / d; }
    const uint8_t* row(size_t i) const { return values.data() + i * d; }
};

// Upper bound on n, taken from the validated data manifest via the environment
// (GATE5B_ORACLE_MAX_N) so it is no longer a 100K-only literal. The 1e6 default
// is only a safety ceiling matched to the intended 1M dataset; the run harness
// must set it equal to the manifest n.
static size_t max_n_from_env() {
    const char* s = std::getenv("GATE5B_ORACLE_MAX_N");
    if (!s || !*s) return 1000000;
    char* end = nullptr;
    unsigned long long v = std::strtoull(s, &end, 10);
    if (end == s || *end || v == 0) throw std::runtime_error("bad GATE5B_ORACLE_MAX_N");
    return static_cast<size_t>(v);
}

static Dataset load(const char* path, size_t max_n) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open bvecs");
    Dataset x;
    while (true) {
        unsigned char h[4];
        in.read(reinterpret_cast<char*>(h), 4);
        if (in.gcount() == 0 && in.eof()) break;
        if (in.gcount() != 4) throw std::runtime_error("truncated header");
        uint32_t d = uint32_t(h[0]) | uint32_t(h[1]) << 8 |
                     uint32_t(h[2]) << 16 | uint32_t(h[3]) << 24;
        if (d != Dataset::d) throw std::runtime_error("expected dimension 128");
        uint8_t row[Dataset::d];
        in.read(reinterpret_cast<char*>(row), Dataset::d);
        if (in.gcount() != Dataset::d) throw std::runtime_error("truncated vector");
        x.values.insert(x.values.end(), row, row + Dataset::d);
        if (x.n() > max_n) throw std::runtime_error("bounded oracle: n exceeds manifest bound");
    }
    if (!x.n()) throw std::runtime_error("empty dataset");
    return x;
}

static int32_t d2(const uint8_t* a, const uint8_t* b) {
    int32_t sum = 0;
    for (size_t k = 0; k < Dataset::d; ++k) {
        int32_t delta = int32_t(a[k]) - int32_t(b[k]);
        sum += delta * delta;
    }
    return sum;
}

static std::vector<size_t> read_ids(const char* path, size_t n) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open ids");
    std::vector<size_t> ids;
    std::set<size_t> seen;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        long long v; std::string extra;
        if (!(ss >> v) || (ss >> extra) || v < 0 || size_t(v) >= n ||
            !seen.insert(size_t(v)).second) throw std::runtime_error("invalid/duplicate id");
        ids.push_back(size_t(v));
    }
    if (ids.empty()) throw std::runtime_error("empty ids");
    return ids;
}

static int parse_m(const std::string& s) {
    size_t used = 0;
    int m = std::stoi(s, &used);
    if (used != s.size() || m < 1 || m > 4095) throw std::runtime_error("m outside [1,4095]");
    return m;
}

int main(int argc, char** argv) {
    try {
        if (argc < 4) throw std::runtime_error("calib bvecs ids [m,...] | gt bvecs ids m output");
        Dataset x = load(argv[2], max_n_from_env());
        auto ids = read_ids(argv[3], x.n());
        std::string mode(argv[1]);
        if (mode == "calib") {
            if (argc > 5) throw std::runtime_error("extra calibration arguments");
            std::vector<int> radii;
            std::stringstream ss(argc == 5 ? argv[4] : "262,264,266,268,270,272,274,276,280");
            std::string s;
            while (std::getline(ss, s, ',')) radii.push_back(parse_m(s));
            if (radii.empty() || radii.size() > 64) throw std::runtime_error("invalid m list");
            std::vector<std::vector<size_t>> counts(radii.size(), std::vector<size_t>(ids.size()));
            #pragma omp parallel for schedule(static)
            for (long long t = 0; t < static_cast<long long>(ids.size()); ++t) {
                for (size_t j = 0; j < x.n(); ++j) {
                    if (j == ids[t]) continue;
                    int32_t distance = d2(x.row(ids[t]), x.row(j));
                    for (size_t c = 0; c < radii.size(); ++c)
                        if (distance < radii[c] * radii[c]) ++counts[c][t];
                }
            }
            std::cout << "m\tthreshold\tsamples\ttotal_neighbors\tmean_neighbors\n";
            for (size_t c = 0; c < radii.size(); ++c) {
                size_t sum = 0;
                for (auto count : counts[c]) sum += count;
                std::cout.precision(17);
                std::cout << radii[c] << '\t' << radii[c] * radii[c] << '\t'
                          << ids.size() << '\t' << sum << '\t' << double(sum) / ids.size() << '\n';
            }
        } else if (mode == "gt") {
            if (argc != 6) throw std::runtime_error("gt requires m and output");
            int m = parse_m(argv[4]);
            std::vector<std::vector<size_t>> neighbors(ids.size());
            #pragma omp parallel for schedule(static)
            for (long long t = 0; t < static_cast<long long>(ids.size()); ++t)
                for (size_t j = 0; j < x.n(); ++j)
                    if (j != ids[t] && d2(x.row(ids[t]), x.row(j)) < m * m)
                        neighbors[t].push_back(j);
            FILE* out = std::fopen(argv[5], "wx");
            if (!out) throw std::runtime_error("cannot create output exclusively");
            for (size_t t = 0; t < ids.size(); ++t) {
                std::fprintf(out, "%zu %zu", ids[t], neighbors[t].size());
                for (auto j : neighbors[t]) std::fprintf(out, " %zu", j);
                std::fprintf(out, "\n");
            }
            bool failed = std::ferror(out);
            if (std::fclose(out) || failed) throw std::runtime_error("GT write failed");
        } else throw std::runtime_error("unknown mode");
    } catch (const std::exception& e) {
        std::cerr << "gate5ar oracle: " << e.what() << '\n';
        return 1;
    }
    return 0;
}
