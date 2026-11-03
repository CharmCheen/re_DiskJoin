#pragma once

#include <vector>
#include <mutex>
#include "../utils/dist_func.h"
#include "ClusterIO.h"
#include "ConfigReader.h"

#define EPS (1 / 1024.)

auto dist_ = utils::L2Sqr;

struct Kmeans {
    size_t d;
    size_t cluster_num;
    std::vector<float> centroids_;
    std::vector<std::vector<size_t>> inverted_list_;
    std::vector<std::vector<std::pair<float, unsigned>>> dists;

    Kmeans(size_t d, size_t cluster_num): d(d), cluster_num(cluster_num) {
        centroids_.resize(cluster_num * d);
        inverted_list_.resize(cluster_num);
    }

    void train(size_t n, float* data, size_t kmeans_iter = 10) {
        size_t bucket_size = n / cluster_num;
#pragma omp parallel for
        for (size_t i = 0; i < cluster_num; ++i) {
            float *data_ptr = data + i * bucket_size * d;
            memcpy(centroids_.data() + i * d, data_ptr, d * sizeof(float));
        }
        std::vector<size_t> assign(n);
        while (kmeans_iter--) {
#pragma omp parallel for
            for (size_t i = 0; i < n; ++i) {
                assign[i] = 0;
                float *data_ptr = data + i * d;
                float min_l2 = dist_(data_ptr, centroids_.data(), &d);
                for (size_t j = 1; j < cluster_num; ++j) {
                    float l2 = dist_(data_ptr, centroids_.data() + j * d, &d);
                    if (l2 < min_l2) {
                        assign[i] = j;
                        min_l2 = l2;
                    }
                }
            }
            std::vector<std::vector<size_t>> ivf(cluster_num);
            for (size_t i = 0; i < n; ++i) {
                ivf[assign[i]].push_back(i);
            }
#pragma omp parallel for
            for (std::size_t i = 0; i < cluster_num; ++i) {
                if (ivf[i].size()) {
                    for (std::size_t j = 0; j < d; ++j) {
                        centroids_[i * d + j] = data[ivf[i][0] * d + j];
                    }
                    for (std::size_t j = 1; j < ivf[i].size(); ++j) {
                        for (std::size_t k = 0; k < d; ++k) {
                            centroids_[i * d + k] += data[ivf[i][j] * d + k];
                        }
                    }
                    for (std::size_t j = 0; j < d; ++j) {
                        centroids_[i * d + j] /= ivf[i].size();
                    }
                }
            }
            for (size_t ci = 0; ci < cluster_num; ci++) {
                if (ivf[ci].size() == 0) {
                    size_t cj;
                    for (cj = 0; 1; cj = (cj + 1) % cluster_num) {
                        float p = (ivf[cj].size() - 1.0) / (float)(n - cluster_num);
                        float r = (float)rand() / RAND_MAX;
                        if (r < p) {
                            break; 
                        }
                    }
                    memcpy(centroids_.data() + ci * d, centroids_.data() + cj * d, sizeof(float) * d);
                    for (size_t j = 0; j < d; j++) {
                        if (j % 2 == 0) {
                            centroids_[ci * d + j] *= 1 + EPS;
                            centroids_[cj * d + j] *= 1 - EPS;
                        } else {
                            centroids_[ci * d + j] *= 1 - EPS;
                            centroids_[cj * d + j] *= 1 + EPS;
                        }
                    }
                }
            }
        }
    }

    void add(size_t n, float* data, std::vector<size_t>& ids) {
        std::vector<size_t> assign(n); 
#pragma omp parallel for
        for (size_t i = 0; i < n; ++i) {
            size_t c = 0;
            float *data_ptr = data + i * d;
            float min_l2 = dist_(data_ptr, centroids_.data(), &d);
            for (size_t j = 1; j < cluster_num; ++j) {
                float l2 = dist_(data_ptr, centroids_.data() + j * d, &d);
                if (l2 < min_l2) {
                    c = j;
                    min_l2 = l2;
                }
            }
            assign[i] = c;
        }
        for (size_t i = 0; i < n; ++i) {
            inverted_list_[assign[i]].push_back(ids[i]);
        }
    }

    void add(size_t n, float* data, std::vector<size_t>& ids, hnswlib::HierarchicalNSW<float>& graph) {
        std::vector<size_t> assign(n); 
#pragma omp parallel for schedule(dynamic)
        for (size_t i = 0; i < n; ++i) {
            float *data_ptr = data + i * d;
            auto cand = graph.searchBaseLayerST<false>(graph.enterpoint_node_, data_ptr, 20);
            while (cand.size() > 1) cand.pop();
            assign[i] = graph.getExternalLabel(cand.top().second);
        }
        for (size_t i = 0; i < n; ++i) {
            inverted_list_[assign[i]].push_back(ids[i]);
        }
    }

    void add2choice(size_t n, float* data, std::vector<size_t>& ids, hnswlib::HierarchicalNSW<float>& graph) {
        std::vector<std::vector<std::pair<size_t, float>>> assign(n); 
#pragma omp parallel for schedule(dynamic)
        for (size_t i = 0; i < n; ++i) {
            float *data_ptr = data + i * d;
            auto cand = graph.searchBaseLayerST<false>(graph.enterpoint_node_, data_ptr, 20);
            while (cand.size() > 2) cand.pop();
            assign[i].push_back(std::make_pair(graph.getExternalLabel(cand.top().second), cand.top().first));
            cand.pop();
            assign[i].push_back(std::make_pair(graph.getExternalLabel(cand.top().second), cand.top().first));
        }
        for (size_t i = 0; i < n; ++i) {
            if (inverted_list_[assign[i][0].first].size() < inverted_list_[assign[i][1].first].size() 
                && assign[i][0].second < assign[i][1].second * 1.2) {
                inverted_list_[assign[i][0].first].push_back(ids[i]);
            } else {
                inverted_list_[assign[i][1].first].push_back(ids[i]);
            }
        }
    }

    void assign() {
        std::vector<std::pair<float, unsigned>> priority;
        for (size_t i = 0; i < dists.size(); i++) {
            priority.push_back(std::make_pair(dists[i][1].first - dists[i][0].first, i));
        }
        std::sort(priority.begin(), priority.end());
        for (size_t i = 0; i < priority.size(); i++) {
            auto id = priority[i].second;
            if (inverted_list_[dists[id][0].second].size() < inverted_list_[dists[id][1].second].size()) {
                inverted_list_[dists[id][0].second].push_back(id);
            } else {
                inverted_list_[dists[id][1].second].push_back(id);
            }
        }
    }
};

void one_level_kmeans(ConfigReader config) {
    auto datafile = config.data_file;
    auto cluster_num = config.cluster_num;
    DataReader data_reader(datafile);
    size_t n = data_reader.n;
    size_t d = data_reader.d;
    std::vector<float> centroids(cluster_num * d);
    {
        std::vector<size_t> sample_id(n);
        for (size_t i = 0; i < n; i++) sample_id[i] = i;
        std::srand(283);
        std::random_shuffle(sample_id.begin(), sample_id.end());
        std::sort(sample_id.begin(), sample_id.begin() + cluster_num);
        size_t batch_num = 1000;
        size_t batch_size = n / batch_num;
        std::vector<float> data_buffer(batch_size * d);
        data_reader.reset();
        size_t ptr = 0;
        for (size_t i = 0; i < div_round_up(n, batch_size); i++) {
            size_t num = batch_size * (i + 1) < n ? batch_size : n - batch_size * i;
            data_reader.get_batch((char*)data_buffer.data(), num);
            while (ptr < cluster_num && sample_id[ptr] < i * batch_size + num) {
                memcpy(centroids.data() + ptr * d, data_buffer.data() + (sample_id[ptr] - i * batch_size) * d, d * sizeof(float));
                ptr++;
            }
        }
    }
    Kmeans kmeans(d, cluster_num);
    {
        kmeans.centroids_ = centroids;
        hnswlib::L2Space space(d);
        hnswlib::HierarchicalNSW<float> graph(&space, cluster_num, 20, 100);
#pragma omp parallel for
        for (size_t i = 0; i < cluster_num; i++) {
            graph.addPoint(centroids.data() + i * d, i);
        }
        graph.saveIndex(config.hnsw_file);
        size_t batch_num = 1000;
        size_t batch_size = n / 1000;
        std::vector<float> data_buffer(batch_size * d);
        std::vector<size_t> ids(batch_size);
        data_reader.reset();
        for (size_t i = 0; i < div_round_up(n, batch_size); i++) {
            size_t num = batch_size * (i + 1) < n ? batch_size : n - batch_size * i;
            for (size_t j = 0; j < num; j++) {
                ids[j] = i * batch_size + j;
            }
            data_reader.get_batch((char*)data_buffer.data(), num);
            kmeans.add2choice(num, data_buffer.data(), ids, graph);
        }
    }
    ClusterWriter cluster_writer(datafile, config.cluster_file, config.metadata_file);
    cluster_writer.writeClusters(kmeans.inverted_list_, kmeans.centroids_.data(), config.mem_budget);
    cluster_writer.writeMetadata(kmeans.inverted_list_);
}
