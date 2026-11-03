#pragma once

#include <vector>
#include <iostream>
#include <fstream>
#include <string>
#include <fcntl.h>
#include <unistd.h>

struct DataReader {
    size_t n;
    size_t d;
    std::ifstream in;

    DataReader() {}

    DataReader(std::string fn): in(fn, std::ios::binary) {
        unsigned n_, d_;
        in.read((char*)&n_, 4);
        in.read((char*)&d_, 4);
        n = n_;
        d = d_;
    }

    void get_batch(char* buf, size_t num) {
        in.read(buf, d * num * 4);
    }

    void reset() {
        in.seekg(8, std::ios::beg);
    }

    void get_batch_at(char* buf, size_t num, size_t start) {
        in.seekg(start * d * 4 + 8, std::ios::beg);
        in.read(buf, d * num * 4);
    }

    ~DataReader() {
        in.close();
    }
};