#pragma once

#include <algorithm>
#include <thread>
#include <cstdlib>
#include <fstream>
#include <omp.h>
#include "Kmeans.h"
#include "ClusterIO.h"
#include "Gorder.h"
#include "Cache.h"
#include "ConfigReader.h"

struct DiskJoin {
    void build(ConfigReader config) {
        one_level_kmeans(config);
    }

    void search(ConfigReader config) {
        float epsilon = sqrt(config.radius);
        ClusterReader cluster_reader(config.cluster_file, config.metadata_file, config.K);
        cluster_reader.readMetaData();
        size_t max_comp = cluster_reader.n / cluster_reader.cluster_num * config.K;
        size_t cluster_num = cluster_reader.cluster_num;
        size_t empty_count = 0;
        size_t d = cluster_reader.d;
        hnswlib::L2Space space(d);
        hnswlib::HierarchicalNSW<float>* graph = new hnswlib::HierarchicalNSW<float>(&space, config.hnsw_file);
        graph->radii = cluster_reader.radii;
        auto& bucket_sizes = cluster_reader.bucket_sizes;
        auto& assignment = cluster_reader.assignment;
        float* centroids = cluster_reader.centroids.data();
        std::vector<std::vector<size_t>> tasks(cluster_num);
        graph->setEf(1000);
        int len = 500;
        std::vector<float> arcos_list(len + 1);
        float sc = len / 2;
        for(int i = 0; i <= len; i++){
            float x = float(i - sc) / sc;
            float y = std::acos(x);
            arcos_list[i] = y;
        }

        auto arcos = [&](float x) -> float {
            if (x > 1) x = 1;
            int index = x*len/2 + len/2;
            return arcos_list[index];
        };
#pragma omp parallel for
        for (size_t i = 0; i < cluster_num; i++) {
            auto top_candidates = graph->knnSearchBaseLayer(i, config.K);
            std::vector<std::pair<float, unsigned>> dis_to_boundary;
            while (!top_candidates.empty()) {
                auto neighbor_cluster = top_candidates.top().second;
                float temp = top_candidates.top().first / 2;
                top_candidates.pop();
                dis_to_boundary.emplace_back(temp, neighbor_cluster);
            }
            std::sort(dis_to_boundary.begin(), dis_to_boundary.end());
            int ptr = dis_to_boundary.size() - 1;
            float sum_of_angle = 0;
            while (ptr >= 0) {
                sum_of_angle += arcos(dis_to_boundary[ptr].first / epsilon);
                if (sum_of_angle >= config.error_bound) break;
                ptr--;
            }
            for (int ii = 0; ii <= ptr; ii++) {
                if (i <= dis_to_boundary[ii].second) {
                    tasks[i].push_back(dis_to_boundary[ii].second);
                }
            }
            std::sort(tasks[i].begin(), tasks[i].end());
            if (tasks[i].size() == 0) {
                for (int ii = 0; ii <= ptr; ii++) {
                    if (dis_to_boundary[ii].first != 0) 
                        exit(0);
                }
                tasks[i].push_back(i);
            }
        }
        delete graph;
        size_t task_num = 0, max_task_num = 0;
        for (size_t i = 0; i < cluster_num; i++) {
            task_num += tasks[i].size();
            if (tasks[i].size() > max_task_num) max_task_num = tasks[i].size();
        }
        std::vector<size_t> perm(cluster_num);
        std::vector<size_t> order(cluster_num);
        std::vector<std::vector<size_t>> reordered_tasks(cluster_num);
        std::vector<std::vector<size_t>> shuffled_tasks(cluster_num);
        for (size_t i = 0; i < cluster_num; i++) {
            perm[i] = i;
        }
        for (size_t i = 0; i < cluster_num; i++) {
            shuffled_tasks[i] = tasks[perm[i]];
        }
        size_t budget = (size_t)(config.mem_budget * 1024 * 1024 * 1024);
        size_t length = cluster_reader.max_points * d;
        perm = order_gorder(shuffled_tasks, budget / 4 / length / config.K * 2);
        for (size_t i = 0; i < cluster_num; i++) {
            reordered_tasks[perm[i]] = shuffled_tasks[i];
            order[perm[i]] = i;
        }
        // [GATE3] runtime invariant checks, gated, no effect on join logic.
        if (getenv("GATE3_INVARIANTS")) {
            std::vector<size_t> seen(cluster_num, 0);
            size_t perm_ok = 1, viol_head = 0, empty_tasks = 0, self_missing = 0;
            for (size_t i = 0; i < cluster_num; i++) {
                if (order[i] >= cluster_num || seen[order[i]]) { perm_ok = 0; }
                else seen[order[i]] = 1;
            }
            for (size_t i = 0; i < cluster_num; i++) {
                if (reordered_tasks[i].empty()) { empty_tasks++; continue; }
                if (reordered_tasks[i][0] != order[i]) viol_head++;
                bool has_self = false;
                for (auto nc : reordered_tasks[i]) if (nc == order[i]) has_self = true;
                if (!has_self) self_missing++;
            }
            size_t task_total = 0, upper_ok = 1;
            for (size_t i = 0; i < cluster_num; i++) {
                task_total += reordered_tasks[i].size();
                for (auto nc : reordered_tasks[i]) if (nc < order[i]) upper_ok = 0;
            }
            size_t sum_bucket = 0;
            for (auto s : bucket_sizes) sum_bucket += s;
            std::cerr << "[gate3-inv] perm_ok=" << perm_ok
                      << " empty_tasks=" << empty_tasks
                      << " head_mismatch=" << viol_head
                      << " self_missing=" << self_missing
                      << " upper_triangle_ok=" << upper_ok
                      << " task_total=" << task_total
                      << " bucket_sum=" << sum_bucket
                      << " n=" << (size_t)cluster_reader.n << "\n";
        }
        std::vector<float> data(max_task_num * length);

        float io_size = 0;

        Cache cache(budget, length);
        cache.init(reordered_tasks);
        float sum = 0;
        size_t count = 0;
        float disk_time = 0;
        float comp_time = 0;
        float dist_comp = 0;
        // [GATE3] env-gated pair-output instrumentation. It records the same
        // hit condition used by the reference and does not alter candidate
        // generation, ordering, cache behaviour, pruning or distance logic.
        const char* gate3_pair_out = getenv("GATE3_PAIR_OUT");
        std::vector<std::vector<std::pair<size_t, size_t>>> gate3_pair_bufs;
        if (gate3_pair_out) gate3_pair_bufs.resize(omp_get_max_threads());
        for (size_t i = 0; i < cluster_num; i++) {
            auto target_cluster = order[i];
            auto& target_tasks = reordered_tasks[i];
            for (size_t j = 0; j < target_tasks.size(); j++) {
                auto neighbor_cluster = target_tasks[j];
                if (!cache.find(neighbor_cluster, data.data() + j * length, cluster_reader.bucket_sizes[neighbor_cluster] * d)) {
                    cluster_reader.posixDirectReadCluster(neighbor_cluster, data.data() + j * length);
                    cache.push(neighbor_cluster, data.data() + j * length, cluster_reader.bucket_sizes[neighbor_cluster] * d);
                }
            }
            
            if (bucket_sizes[target_cluster] == 0) continue;
#pragma omp parallel for schedule(dynamic) reduction(+:sum) reduction(+:count) reduction(+:dist_comp)
            for (size_t j = 0; j < bucket_sizes[target_cluster]; j++) {
                auto id1 = assignment[target_cluster][j];
                float* vec1 = data.data() + j * d;
                std::vector<std::pair<size_t, size_t>>* gate3_local =
                    gate3_pair_out ? &gate3_pair_bufs[omp_get_thread_num()] : nullptr;
                for (size_t l = 0; l < bucket_sizes[target_cluster]; l++) {
                    auto id2 = assignment[target_cluster][l];
                    if (id2 >= id1) continue;
                    float* vec2 = data.data() + l * d;
                    float dist = dist_l2(vec1, vec2, &d);
                    dist_comp++;
                    if (dist < epsilon * epsilon) {
                        if (id1 % 100000 == 0) count++;
                        if (id2 % 100000 == 0) count++;
                        if (gate3_local) gate3_local->emplace_back(std::min(id1, id2), std::max(id1, id2));
                    }
                }

                for (int k = 1; k < target_tasks.size(); k++) {
                    auto neighbor_cluster = target_tasks[k];
                    float dist = dist_l2(vec1, centroids + neighbor_cluster * d, &d);
                    for (size_t l = 0; l < bucket_sizes[neighbor_cluster]; l++) {
                        auto id2 = assignment[neighbor_cluster][l];
                        float* vec2 = data.data() + k * length + l * d;
                        float dist1 = dist_l2(vec1, vec2, &d);
                        dist_comp++;
                        if (dist1 < epsilon * epsilon) {
                            if (id1 % 100000 == 0) count++;
                            if (id2 % 100000 == 0) count++;
                            if (gate3_local) gate3_local->emplace_back(std::min(id1, id2), std::max(id1, id2));
                        };
                    }
                }
            }
        }
        std::cout << "recall = " << 1.0 * count / config.gt << "\n";
        // [GATE3] precise statistics, gated.
        if (getenv("GATE3_INVARIANTS")) {
            std::cerr << "[gate3-stat] dist_comp=" << (size_t)dist_comp
                      << " sampled_count=" << count
                      << " gt=" << config.gt << "\n";
        }
        // [GATE3] write per-thread pair buffers (thread-local -> no locking).
        if (gate3_pair_out) {
            std::ofstream gate3_f(gate3_pair_out);
            size_t gate3_total = 0;
            for (auto& gate3_pb : gate3_pair_bufs) {
                for (auto& gate3_pr : gate3_pb) {
                    gate3_f << gate3_pr.first << " " << gate3_pr.second << "\n";
                    gate3_total++;
                }
            }
            gate3_f.close();
            std::cerr << "[gate3] pair_dump=" << gate3_pair_out
                      << " pairs=" << gate3_total
                      << " threads=" << gate3_pair_bufs.size() << "\n";
        }
    }
};
