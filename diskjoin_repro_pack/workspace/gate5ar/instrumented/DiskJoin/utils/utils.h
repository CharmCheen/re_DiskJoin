#pragma once

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <queue>
#include <array>
#include <fcntl.h>
#include <filesystem>
#include <linux/mman.h>
#include <memory>

typedef std::priority_queue<std::pair<float, unsigned>> candidate_pool;

struct Timer {
    std::chrono::_V2::system_clock::time_point s;
    std::chrono::_V2::system_clock::time_point e;
    std::chrono::duration<double> diff;

    void tick() {
        s = std::chrono::high_resolution_clock::now();
    }

    void tuck(std::string message, bool print = true) {
        e = std::chrono::high_resolution_clock::now();
        diff = e - s;
        if (print) {
            std::cout << "[" << diff.count() << " s] " << message << std::endl;
        }
    }
};

template <class T>
T* read_fbin(const char* filename, unsigned& n, unsigned& d) {
    std::ifstream in(filename, std::ios::binary);
    in.read((char*)&n, 4);
    in.read((char*)&d, 4);
    auto data = new T[n * d];
    in.read((char*)data, (size_t)n * (size_t)d * 4);
    in.close();
    return data;
}

void read_fvecs(char* filename, float*& data, unsigned& n, unsigned& d) {
    std::ifstream in(filename, std::ios::binary);
    if (!in.is_open()) {
        std::cout << "open file error" << std::endl;
        exit(-1);
    }
    float num, dim;
    in.read((char*)&dim, 4);
    in.seekg(0, std::ios::end);
    std::ios::pos_type ss = in.tellg();
    size_t fsize = (size_t)ss;
    num = (float)(fsize / (dim + 1) / 4);
    data = new float[(size_t)num * (size_t)dim];
    in.seekg(0, std::ios::beg);
    for (size_t i = 0; i < num; i++) {
        in.seekg(4, std::ios::cur);
        in.read((char*)(data + i * (size_t)dim), dim * 4);
    }
    in.close();
    n = (unsigned)num;
    d = (unsigned)dim;
    std::cout << "data num: " << n << ", dimension:" << d << std::endl;
}

size_t div_round_up(size_t x, size_t y) {
    return (x / y) + static_cast<size_t>((x % y) != 0);
}