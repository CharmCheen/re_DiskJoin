#pragma once

#include <iostream>
#include <string>
#include <vector>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <omp.h>

#include "DataReader.h"
#include "../utils/utils.h"
#include "../utils/dist_func.h"

auto dist_l2 = utils::L2Sqr;

#define MAX_IO_SIZE 2147479552
#define PAGE_SIZE 4096

struct ClusterWriter {
    DataReader data_reader;
    std::string clusterfile;
    std::ofstream fcluster;
    std::ofstream fmeta;

    size_t n;
    size_t d;
    size_t cluster_num;
    size_t max_points;
    std::vector<size_t> bucket_sizes;
    float* centroids_;
    std::vector<float> radii;

    ClusterWriter(std::string datafile, std::string clusterfile, std::string metafile): 
        clusterfile(clusterfile), 
        data_reader(datafile),
        fcluster(clusterfile, std::ios::binary | std::ios::out),
        fmeta(metafile, std::ios::binary | std::ios::out) {
        n = data_reader.n;
        d = data_reader.d;
    }

    void writeClusters(std::vector<std::vector<size_t>>& assignment, float* centroids, float budget) {
        centroids_ = centroids;
        std::vector<unsigned> id_cluster_map(n);
        max_points = 0;
        for (size_t i = 0; i < assignment.size(); i++) {
            auto& cluster = assignment[i];
            if (cluster.size() > max_points) max_points = cluster.size();
            for (auto id : cluster) {
                id_cluster_map[id] = i;
            }
            bucket_sizes.push_back(cluster.size());
            std::sort(cluster.begin(), cluster.end());
        }
        cluster_num = assignment.size();
        radii.resize(cluster_num);
        size_t buffer_size = div_round_up(budget * (size_t)1024 * 1024 * 1024 / cluster_num, d * 4) * d * 4;
        char* buffer = new char[cluster_num * buffer_size];
        std::vector<size_t> buffer_pos(cluster_num);
        std::vector<size_t> file_pos(cluster_num);
        size_t cumu_size = 0;
        for (size_t i = 0; i < cluster_num; i++) {
            buffer_pos[i] = buffer_size * i;
            file_pos[i] = cumu_size * sizeof(float) * d;
            cumu_size += bucket_sizes[i];
        }
        size_t batch_size = n / 1000;
        float* data_buf = new float[batch_size * d];
        for (size_t i = 0; i < div_round_up(n, batch_size); i++) {
            size_t num = batch_size * (i + 1) < n ? batch_size : n - batch_size * i;
            data_reader.get_batch((char*)data_buf, num);
            for (size_t j = 0; j < num; j++) {
                auto id = j + batch_size * i;
                auto cluster = id_cluster_map[id];
                float dist = dist_l2(data_buf + j * d, centroids + cluster * d, &d);
                if (dist > radii[cluster]) radii[cluster] = dist;
                memcpy(buffer + buffer_pos[cluster], data_buf + j * d, d * 4);
                buffer_pos[cluster] += d * 4;
                if (buffer_pos[cluster] == buffer_size * (cluster + 1)) {
                    buffer_pos[cluster] -= buffer_size;
                    fcluster.seekp(file_pos[cluster], std::ios::beg);
                    fcluster.write(buffer + buffer_pos[cluster], buffer_size);
                    file_pos[cluster] += buffer_size;
                }
            }
        }
        for (size_t i = 0; i < cluster_num; i++) {
            if (buffer_pos[i] % buffer_size != 0) {
                fcluster.seekp(file_pos[i], std::ios::beg);
                fcluster.write(buffer + buffer_size * i, buffer_pos[i] % buffer_size);
            }
        }
        auto file_size = div_round_up(n * d * sizeof(float), 4096);
        fcluster.seekp(file_size, std::ios::beg);
        for (size_t i = 0; i < cluster_num; i++) {
            radii[i] = sqrt(radii[i]);
        }
    }

    void writeMetadata(std::vector<std::vector<size_t>>& assignment) {
        fmeta.write((char*)&n, sizeof(size_t));
        fmeta.write((char*)&d, sizeof(size_t));
        fmeta.write((char*)&cluster_num, sizeof(size_t));
        fmeta.write((char*)&max_points, sizeof(size_t));
        fmeta.write((char*)bucket_sizes.data(), sizeof(size_t) * cluster_num);
        fmeta.write((char*)centroids_, sizeof(float) * cluster_num * d);
        fmeta.write((char*)radii.data(), sizeof(float) * cluster_num);
        for (size_t i = 0; i < cluster_num; i++) {
            fmeta.write((char*)assignment[i].data(), assignment[i].size() * sizeof(size_t));
        }

        fmeta.seekp(0, std::ios::end);
    }

    ~ClusterWriter() {
        fcluster.close();
        fmeta.close();
    }
};

struct ClusterReader {
    std::ifstream fcluster;
    std::ifstream fmeta;

    int cluster_fd;

    size_t max_task_size;
    size_t task_num;

    size_t n;
    size_t d;
    size_t cluster_num;
    size_t max_points;
    std::vector<size_t> bucket_sizes;
    std::vector<float> centroids;
    std::vector<float> radii;
    std::vector<size_t> file_pos;
    std::vector<std::vector<size_t>> assignment;

    size_t buffer_size;
    char* buffer;

    double total;
    double used;

    ClusterReader(std::string clusterfile, std::string metafile, size_t max_task_size = 1):
        task_num(0),
        max_task_size(max_task_size), 
        fcluster(clusterfile, std::ios::binary | std::ios::in), 
        fmeta(metafile, std::ios::binary | std::ios::in),
        total(0),
        used(0) {
        cluster_fd = open(clusterfile.c_str(), O_RDONLY | O_DIRECT);
    }

    void readMetaData() {
        fmeta.read((char*)&n, sizeof(size_t));
        fmeta.read((char*)&d, sizeof(size_t));
        fmeta.read((char*)&cluster_num, sizeof(size_t));
        fmeta.read((char*)&max_points, sizeof(size_t));
        bucket_sizes.resize(cluster_num);
        fmeta.read((char*)bucket_sizes.data(), sizeof(size_t) * cluster_num);
        centroids.resize(d * cluster_num);
        fmeta.read((char*)centroids.data(), sizeof(float) * d * cluster_num);
        radii.resize(cluster_num);
        fmeta.read((char*)radii.data(), sizeof(float) * cluster_num);
        assignment.resize(cluster_num);
        for (size_t i = 0; i < cluster_num; i++) {
            assignment[i].resize(bucket_sizes[i]);
            fmeta.read((char*)assignment[i].data(), bucket_sizes[i] * sizeof(size_t));
        }

        file_pos.resize(cluster_num);
        size_t cumu_size = 0;
        for (size_t i = 0; i < cluster_num; i++) {
            file_pos[i] = cumu_size * sizeof(float) * d;
            cumu_size += bucket_sizes[i];
        }

        size_t page_num = div_round_up(max_points * d * 4, PAGE_SIZE);
        buffer_size = PAGE_SIZE * (page_num + 1);
        buffer = (char*)aligned_alloc(PAGE_SIZE, buffer_size * max_task_size);
    }

    void readCluster(size_t cluster_id, float* buffer) {
        fcluster.seekg(file_pos[cluster_id], std::ios::beg);
        fcluster.read((char*)buffer, bucket_sizes[cluster_id] * d * 4);
    }

    void posixDirectReadCluster(size_t cluster_id, float* data_buffer) {
        size_t buffer_offset = file_pos[cluster_id] % PAGE_SIZE;
        size_t file_offset = file_pos[cluster_id] - buffer_offset;
        size_t read_size = bucket_sizes[cluster_id] * d * 4;
        size_t aligned_read_size = div_round_up(buffer_offset + read_size, PAGE_SIZE) * PAGE_SIZE;
        total += aligned_read_size;
        used += read_size;
        lseek(cluster_fd, file_offset, SEEK_SET);
        auto count = read(cluster_fd, buffer, aligned_read_size);
        memcpy(data_buffer, buffer + buffer_offset, read_size);
    }

    ~ClusterReader() {
        fcluster.close();
        fmeta.close();
        close(cluster_fd);
        delete[] buffer;
    }
};