#pragma once
#include <algorithm>
#include <array>
#include <cstdint>

namespace sk2::perf {
struct Histogram {
    // 250 us buckets, with an overflow bucket. Report the bucket's upper bound.
    std::array<uint32_t, 257> buckets{};
    uint64_t count = 0, total_ns = 0, max_ns = 0, late = 0;
    void add(uint64_t ns) {
        buckets[std::min<uint64_t>(ns / 250'000, buckets.size() - 1)]++;
        count++; total_ns += ns; max_ns = std::max(max_ns, ns);
        late += ns > 16'666'667;
    }
    uint64_t percentile_ns(unsigned percent) const {
        if (!count || !max_ns) return 0;
        const uint64_t target = (count * percent + 99) / 100;
        uint64_t accumulated = 0;
        for (size_t i = 0; i < buckets.size(); i++) {
            accumulated += buckets[i];
            if (accumulated >= target) return i == buckets.size() - 1 ? max_ns : (i + 1) * 250'000;
        }
        return max_ns;
    }
};
}
