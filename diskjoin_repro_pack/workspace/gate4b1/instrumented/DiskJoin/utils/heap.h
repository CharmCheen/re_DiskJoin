#pragma once

#include <iostream>
#include <functional>
#include <unordered_map>

//#define DYNAMIC_ALLOC

template <class TObj, class TKey, class compare_by = std::less<int>>
class updateable_heap {
    using _elem = std::pair<TObj, TKey>;
public:
    updateable_heap(size_t _size = 1024) : max_size(_size),
        current_bound(1) {
        storage = new _elem[max_size];
    }

    updateable_heap(const updateable_heap<TObj, TKey, compare_by>& target) { *this = target; }

    updateable_heap& operator = (const updateable_heap<TObj, TKey, compare_by>& target) {
        delete[] storage;
        max_size = target.max_size;
        storage = new _elem[max_size];
        for (unsigned i = 0; i < max_size; ++i)
            storage[i] = target.storage[i];
        current_bound = target.current_bound;
        positions = target.positions;
        return *this;
    }

    [[gnu::pure]] inline bool empty() { return (current_bound == 1); }

    [[gnu::pure]] inline _elem top() { return storage[1]; }

    [[gnu::pure]] inline _elem last_item() { return storage[0]; }

    [[gnu::hot]] inline void add(_elem target) {
        storage[current_bound] = target;
        sift_up(current_bound);
#ifdef DYNAMIC_ALLOC
        if (++current_bound == max_size) {
            max_size <<= 1;
            realloc(storage, max_size);
        }
#else
        ++current_bound;
#endif
    }

    [[gnu::hot]] inline _elem pop() {
        storage[0] = storage[1];
        positions.erase(storage[0].first);
        storage[1] = storage[--current_bound];

        sift_down(1);

        return storage[0];
    }

    [[gnu::hot]] inline void update(_elem target) {
        auto location = positions.find(target.first);

        if (location != positions.end()) {
            if (comparator(storage[location->second].second, target.second)) {
                storage[location->second].second = target.second;
                sift_down(location->second);
            } else {
                storage[location->second].second = target.second;
                sift_up(location->second);
            }
        } else {
            add(target);
        }
    }
    
    void run_diagnostic() {
        for (int i = 1; i < current_bound; ++i) {
            std::cout << storage[i].first << " " << storage[i].second << std::endl;
        }
        std::cout << "--------------------------------------\n";
    }
    
    ~updateable_heap() { delete[] storage; }

private:
    [[gnu::hot]] inline void sift_up(unsigned crawler) {
        _elem aux = storage[crawler];

        while (parent_pos(crawler) && comparator(aux.second, parent(crawler).second)) {
            storage[crawler] = parent(crawler);
            positions[parent(crawler).first] = crawler;
            crawler = parent_pos(crawler);
        }

        storage[crawler] = aux;
        positions[aux.first] = crawler;
    }

    [[gnu::hot]] inline void sift_down(unsigned crawler) {
        _elem aux = storage[crawler];

        while (!is_leaf(crawler)) {
            // [GATE4B1] Fix of an upstream latent bug (isolated copy only).
            // When crawler has a left son but NO right son
            // (right_son_pos(crawler) == current_bound), the original
            // operand order read right_son(crawler) — storage[2*crawler+1],
            // i.e. storage[current_bound] — BEFORE this guard: a
            // heap-buffer-overflow read when current_bound == max_size
            // (full heap; ASan: READ of size 8 one past a 63x16B region),
            // or a stale-slot read otherwise. The guard is now evaluated
            // first (|| short-circuits the read); the logical value is
            // unchanged whenever the original read was well defined (right
            // son exists => both orders evaluate the same two operands).
            // Reachable only via a key-DECREASING update() on a full heap:
            // the reference belady policies only ever INCREASE keys on
            // update (-> sift_up) and pop() sifts with current_bound
            // already decremented (62, even => no right-son gap exists
            // while sifting from pop), so the default path never hits it;
            // the new lru_forced policy does (recency keys decrease on
            // hit). Evidence: logs/prefix_crash_p3_lru_asan.stderr (real
            // run) and logs/prefix_policy_test_asan.stderr (standalone
            // unit-test reproduction, oracle/policy_test.cpp T3/T5).
            if (!comparator(aux.second, left_son(crawler).second) &&
                (right_son_pos(crawler) == current_bound ||
                 !comparator(right_son(crawler).second, left_son(crawler).second))) {
                storage[crawler] = left_son(crawler);
                positions[left_son(crawler).first] = crawler;
                crawler = left_son_pos(crawler);
            }
            // [GATE4B1] Same guard-first reordering on the right-son branch:
            // reaching this branch with no right son (guard true) means the
            // first condition failed, i.e. aux outranks its only (left) son,
            // so the correct action is to stop. The original condition read
            // right_son(crawler) = storage[current_bound] (stale slot, or OOB
            // on a full heap) before this decision. Unreachable in the
            // reference configurations (see comment above); fixed for the
            // same reason, with identical defined-case semantics.
            else if (right_son_pos(crawler) != current_bound &&
                     !comparator(aux.second, right_son(crawler).second)) {
                storage[crawler] = right_son(crawler);
                positions[right_son(crawler).first] = crawler;
                crawler = right_son_pos(crawler);
            }
            else {
                break;
            }
        }

        storage[crawler] = aux;
        positions[aux.first] = crawler;
    }

    [[gnu::hot, gnu::pure]] inline unsigned right_son_pos(unsigned pos) {
        return 1 + (pos << 1);
    }

    [[gnu::hot, gnu::pure]] inline _elem right_son(unsigned pos) {
        return storage[right_son_pos(pos)];
    }

    [[gnu::hot, gnu::pure]] inline unsigned left_son_pos(unsigned pos) {
        return (pos << 1);
    }

    [[gnu::hot, gnu::pure]] inline _elem left_son(unsigned pos) {
        return storage[left_son_pos(pos)];
    }

    [[gnu::hot, gnu::pure]] inline unsigned parent_pos(unsigned pos) {
        return (pos >> 1);
    }

    [[gnu::hot, gnu::pure]] inline _elem parent(unsigned pos) {
        return storage[parent_pos(pos)];
    }

    [[gnu::hot]] inline bool is_leaf(unsigned pos) {
        return !(right_son_pos(pos) < current_bound || left_son_pos(pos) < current_bound);
    }

    compare_by comparator;
    size_t max_size, current_bound;
    _elem* storage;

    std::unordered_map<TObj, unsigned> positions;
};