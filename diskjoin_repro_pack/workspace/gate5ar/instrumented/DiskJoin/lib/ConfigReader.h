#pragma once

#include <fstream>
#include <iostream>

using namespace std;

struct ConfigReader{
    string data_file;
    float radius;
    size_t cluster_num;
    string cluster_file;
    string metadata_file;
    string hnsw_file;
    size_t K;
    float mem_budget;
    float error_bound;
    size_t gt;

    ConfigReader() = default;

    ConfigReader(string config) {
        ifstream in(config);
        string dummy_str;
        in >> dummy_str >> data_file;
        in >> dummy_str >> radius;
        in >> dummy_str >> cluster_num;
        in >> dummy_str >> cluster_file;
        in >> dummy_str >> metadata_file;
        in >> dummy_str >> hnsw_file;
        in >> dummy_str >> K;
        in >> dummy_str >> mem_budget;
        in >> dummy_str >> error_bound;
        in >> dummy_str >> gt;
    }
};