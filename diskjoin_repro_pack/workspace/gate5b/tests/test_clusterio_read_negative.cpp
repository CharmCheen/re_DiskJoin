// Gate 5B NEGATIVE CONTROL for the ClusterIO read-path fix.
//
// This test asserts the PRE-FIX (buggy) behaviour:
//   N1 a truncated cluster file does NOT throw; reading bucket1 silently
//      returns bucket0's stale bytes (buffer reused across calls)
//   N2 the constructor does NOT throw on missing files
//   N3 truncated metadata does NOT throw
//
// It exits 0 iff the bugs are present, so:
//   - against the pre-fix header it PASSES  (bug reproduced)
//   - against the patched header it FAILS   (fix changes behaviour)
// This makes the positive test meaningful (it would have caught the bug).
#include "ClusterIO.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

static int failures = 0;
static void check(bool ok, const char* msg) {
    std::printf("%s: %s\n", ok ? "ok  " : "FAIL", msg);
    if (!ok) failures++;
}

static void write_meta(const std::string& path, size_t n, size_t d, size_t cluster_num,
                       size_t max_points, const std::vector<size_t>& bs,
                       const std::vector<std::vector<size_t>>& asg, bool header_only = false) {
    std::ofstream f(path, std::ios::binary);
    f.write((char*)&n, sizeof(size_t));
    f.write((char*)&d, sizeof(size_t));
    f.write((char*)&cluster_num, sizeof(size_t));
    f.write((char*)&max_points, sizeof(size_t));
    if (header_only) return;
    f.write((char*)bs.data(), sizeof(size_t) * cluster_num);
    std::vector<float> centroids(cluster_num * d, 0.0f);
    f.write((char*)centroids.data(), sizeof(float) * cluster_num * d);
    std::vector<float> radii(cluster_num, 0.0f);
    f.write((char*)radii.data(), sizeof(float) * cluster_num);
    for (size_t i = 0; i < cluster_num; i++)
        f.write((char*)asg[i].data(), sizeof(size_t) * bs[i]);
}

static void write_cluster(const std::string& path, const std::vector<std::vector<float>>& buckets,
                          long truncate_to = -1) {
    std::ofstream f(path, std::ios::binary);
    for (auto& b : buckets) f.write((char*)b.data(), b.size() * sizeof(float));
    f.close();
    if (truncate_to >= 0 && ::truncate(path.c_str(), truncate_to) != 0) std::perror("truncate");
}

int main(int argc, char** argv) {
    if (argc != 2) { std::fprintf(stderr, "usage: %s WORKDIR\n", argv[0]); return 2; }
    std::string dir = argv[1];
    const size_t d = 4, cn = 2, maxp = 1024;
    std::vector<size_t> bs = {1024, 1024};
    std::vector<std::vector<size_t>> asg = {std::vector<size_t>(1024, 0), std::vector<size_t>(1024, 0)};
    std::vector<std::vector<float>> buckets(2);
    for (size_t b = 0; b < 2; b++)
        for (size_t i = 0; i < 1024 * d; i++) buckets[b].push_back(100.0f * b + (float)i);

    std::string cf = dir + "/data.clusters";
    std::string mf = dir + "/data.metadata";

    // N1: truncated cluster file -> stale reuse, no throw
    write_meta(mf, 2048, d, cn, maxp, bs, asg);
    write_cluster(cf, buckets, (long)(1024 * d * sizeof(float)));
    {
        bool threw = false, stale = false;
        try {
            ClusterReader r(cf, mf, 1);
            r.readMetaData();
            std::vector<float> got0(1024 * d, -1.0f), got1(1024 * d, -1.0f);
            r.posixDirectReadCluster(0, got0.data());
            r.posixDirectReadCluster(1, got1.data()); // pre-fix: silently stale
            stale = (got1 == buckets[0]);             // bucket0 bytes reused for bucket1
        } catch (const std::exception&) { threw = true; }
        check(!threw && stale, "N1 (bug) truncated read returns stale bytes without throwing");
    }

    // N2: missing files -> no throw
    {
        bool threw = false;
        try { ClusterReader r(dir + "/nope.clusters", dir + "/nope.meta", 1); }
        catch (const std::exception&) { threw = true; }
        check(!threw, "N2 (bug) constructor does not fail on missing files");
    }

    // N3: truncated metadata -> no throw
    write_cluster(cf, buckets);
    write_meta(mf, 2048, d, cn, maxp, bs, asg, /*header_only=*/true);
    {
        bool threw = false;
        try { ClusterReader r(cf, mf, 1); r.readMetaData(); }
        catch (const std::exception&) { threw = true; }
        check(!threw, "N3 (bug) truncated metadata does not throw");
    }

    std::printf("\n%s (%d failure%s)\n", failures ? "NEG-CONTROL SAW FIXED BEHAVIOUR" : "NEG-CONTROL REPRODUCED PRE-FIX BUGS",
                failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
