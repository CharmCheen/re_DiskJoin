// Gate 5B deterministic regression test for the ClusterIO read path.
//
// Covers:
//   T1 normal O_DIRECT bucket read (exact values, no false failure)
//   T2 short/truncated cluster file -> must throw, NOT return stale bytes
//      (the pre-fix code memcpy'd from a buffer reused across calls)
//   T3 read failure (invalid fd, EBADF) -> must throw
//   T4 EINTR: a blocking read interrupted by signals must be retried and
//      still return the full payload
//   T5 constructor fail-fast on unopenable inputs
//   T6 truncated metadata -> readMetaData must throw
//
// Exit code 0 iff every check passes. Usage: test_clusterio_read WORKDIR
#include "ClusterIO.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <sys/time.h>
#include <unistd.h>

static int failures = 0;
static void check(bool ok, const char* msg) {
    std::printf("%s: %s\n", ok ? "ok  " : "FAIL", msg);
    if (!ok) failures++;
}

static void write_meta(const std::string& path, size_t n, size_t d, size_t cluster_num,
                       size_t max_points, const std::vector<size_t>& bs,
                       const std::vector<std::vector<size_t>>& asg) {
    std::ofstream f(path, std::ios::binary);
    f.write((char*)&n, sizeof(size_t));
    f.write((char*)&d, sizeof(size_t));
    f.write((char*)&cluster_num, sizeof(size_t));
    f.write((char*)&max_points, sizeof(size_t));
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

static void on_alarm(int) {}
static void* writer_thread(void* arg) {
    int fd = *(int*)arg;
    usleep(250000); // let several SIGALRMs interrupt the blocked reader first
    const char payload[8] = {'A','B','C','D','E','F','G','H'};
    ssize_t w = ::write(fd, payload, 8);
    (void)w;
    return nullptr;
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

    // ---- T1: normal read ----
    write_meta(mf, 2048, d, cn, maxp, bs, asg);
    write_cluster(cf, buckets);
    try {
        ClusterReader r(cf, mf, 1);
        r.readMetaData();
        std::vector<float> got0(1024 * d, -1.0f), got1(1024 * d, -1.0f);
        r.posixDirectReadCluster(0, got0.data());
        r.posixDirectReadCluster(1, got1.data());
        bool ok = (got0 == buckets[0]) && (got1 == buckets[1]) && r.reads == 2;
        check(ok, "T1 normal O_DIRECT read returns exact bucket values");
    } catch (const std::exception& e) {
        check(false, (std::string("T1 threw unexpectedly: ") + e.what()).c_str());
    }

    // ---- T2: short/truncated cluster file must throw (no stale reuse) ----
    // Truncate to exactly bucket0; reading bucket1 must not return bucket0's bytes.
    write_cluster(cf, buckets, (long)(1024 * d * sizeof(float)));
    bool t2_threw = false, t2_wrong = false;
    try {
        ClusterReader r(cf, mf, 1);
        r.readMetaData();
        std::vector<float> got0(1024 * d, -1.0f), got1(1024 * d, -1.0f);
        r.posixDirectReadCluster(0, got0.data()); // fills the internal buffer
        if (got0 != buckets[0]) t2_wrong = true;
        r.posixDirectReadCluster(1, got1.data()); // must throw
    } catch (const std::exception&) {
        t2_threw = true;
    }
    check(t2_threw && !t2_wrong,
          "T2 truncated cluster read throws instead of returning stale data");

    // ---- T3: read failure (bad fd) must throw ----
    bool t3_threw = false;
    try {
        char buf[16];
        ClusterReader::readExactOrThrow(-1, buf, sizeof(buf));
    } catch (const std::exception&) { t3_threw = true; }
    check(t3_threw, "T3 read failure (EBADF) throws");

    // ---- T4: EINTR retry still returns the full payload ----
    {
        int pfd[2];
        if (pipe(pfd) != 0) { check(false, "T4 pipe() failed"); }
        else {
            struct sigaction sa; std::memset(&sa, 0, sizeof sa);
            sa.sa_handler = on_alarm; // no SA_RESTART -> blocked read returns EINTR
            sigaction(SIGALRM, &sa, nullptr);
            struct itimerval it; std::memset(&it, 0, sizeof it);
            it.it_interval.tv_usec = 20000; it.it_value = it.it_interval;
            setitimer(ITIMER_REAL, &it, nullptr);
            pthread_t th;
            pthread_create(&th, nullptr, writer_thread, &pfd[1]);
            char buf[8]; std::memset(buf, 0, sizeof buf);
            bool ok = false;
            try { ClusterReader::readExactOrThrow(pfd[0], buf, 8);
                  ok = (std::memcmp(buf, "ABCDEFGH", 8) == 0); }
            catch (const std::exception&) { ok = false; }
            pthread_join(th, nullptr);
            struct itimerval zero; std::memset(&zero, 0, sizeof zero);
            setitimer(ITIMER_REAL, &zero, nullptr);
            close(pfd[0]); close(pfd[1]);
            check(ok, "T4 EINTR-interrupted read is retried to completion");
        }
    }

    // ---- T5: constructor fail-fast on unopenable inputs ----
    bool t5_threw = false;
    try { ClusterReader r(dir + "/does-not-exist.clusters", dir + "/does-not-exist.meta", 1); }
    catch (const std::exception&) { t5_threw = true; }
    check(t5_threw, "T5 constructor throws on missing cluster/metadata files");

    // ---- T6: truncated metadata must throw ----
    write_cluster(cf, buckets);
    {
        std::ofstream f(mf, std::ios::binary); // header only, no buckets/assignment
        size_t n = 2048, dd = d, c = cn, mp = maxp;
        f.write((char*)&n, 8); f.write((char*)&dd, 8);
        f.write((char*)&c, 8); f.write((char*)&mp, 8);
    }
    bool t6_threw = false;
    try { ClusterReader r(cf, mf, 1); r.readMetaData(); }
    catch (const std::exception&) { t6_threw = true; }
    check(t6_threw, "T6 truncated metadata throws");

    std::printf("\n%s (%d failure%s)\n", failures ? "READ-PATH TESTS FAILED" : "READ-PATH TESTS PASSED",
                failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
