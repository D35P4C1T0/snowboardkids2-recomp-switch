#include "profiling.h"
#include "logging.h"
#include "perf_stats.h"

#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <mutex>

static std::atomic<bool> switch_profile_enabled{true};
static std::atomic<float> switch_display_fps{0.0f};

extern "C" float switch_fps_value() {
    return switch_display_fps.load(std::memory_order_relaxed);
}

extern "C" void switch_fps_presented() {
    // Count completed presentations, including interpolation, independently
    // of detailed profiling. UI rendering reads the previous half-second window.
    using Clock = std::chrono::steady_clock;
    static auto window_start = Clock::time_point{};
    static uint32_t frames = 0;
    const auto now = Clock::now();
    if (window_start == Clock::time_point{}) {
        window_start = now;
        return;
    }
    frames++;
    const auto elapsed = now - window_start;
    if (elapsed >= std::chrono::milliseconds(500)) {
        switch_display_fps.store(float(frames / std::chrono::duration<double>(elapsed).count()),
            std::memory_order_relaxed);
        frames = 0;
        window_start = now;
    }
}

static void switch_perf_collect(const char* stage, uint64_t value, uint64_t id, bool traffic) {
    if (!switch_profile_enabled.load(std::memory_order_relaxed)) return;
    using Clock = std::chrono::steady_clock;
    struct Entry {
        const char* name = nullptr;
        sk2::perf::Histogram stats;
        uint64_t id = 0, max_id = 0;
        Clock::time_point max_end{};
    };
    static std::array<Entry, 48> entries;
    struct TrafficEntry { const char* name = nullptr; uint64_t count = 0, bytes = 0, id = 0; };
    static std::array<TrafficEntry, 16> transfers;
    static std::array<TrafficEntry, 16> transfer_report;
    uint64_t interval_ns = 0;
    Clock::time_point report_time;
    static std::mutex mutex;
    static auto last_report = std::chrono::steady_clock::now();
    // Snapshot a completed window under the collection lock. Formatting and
    // socket writes must not hold up audio, display-list or GPU timing callers.
    static std::array<Entry, 48> report;
    static std::mutex report_mutex;
    std::unique_lock report_lock(report_mutex, std::defer_lock);
    {
        std::lock_guard lock(mutex);
        if (traffic) {
            for (auto& entry : transfers) {
                if (!entry.name) entry.name = stage;
                if (std::strcmp(entry.name, stage) == 0) {
                    entry.count++; entry.bytes += value; entry.id = id; break;
                }
            }
        }
        else {
            for (auto& entry : entries) {
                if (!entry.name) entry.name = stage;
                if (std::strcmp(entry.name, stage) == 0) {
                    if (!entry.stats.count || value > entry.stats.max_ns) {
                        entry.max_id = id;
                        entry.max_end = Clock::now();
                    }
                    entry.stats.add(value); entry.id = id; break;
                }
            }
        }
        const auto now = std::chrono::steady_clock::now();
        if (now - last_report < std::chrono::seconds(2)) return;
        // A slow previous report may still own the snapshot. Keep collecting
        // rather than waiting for it or allocating another report buffer.
        if (!report_lock.try_lock()) return;
        interval_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now - last_report).count();
        report_time = now;
        transfer_report = transfers;
        for (auto& entry : transfers) { entry.count = 0; entry.bytes = 0; }
        report = entries;
        for (auto& entry : entries) entry.stats = {};
        last_report = now;
    }
    for (const auto& entry : report) {
        const auto& h = entry.stats;
        if (!h.count) continue;
        char message[512];
        std::snprintf(message, sizeof(message),
            "profile: stage=%s count=%llu mean_us=%llu p50_us=%llu p95_us=%llu p99_us=%llu max_us=%llu late=%llu id=%llu max_id=%llu max_age_us=%llu interval_ns=%llu",
            entry.name, (unsigned long long)h.count, (unsigned long long)(h.total_ns / h.count / 1000),
            (unsigned long long)(h.percentile_ns(50) / 1000), (unsigned long long)(h.percentile_ns(95) / 1000),
            (unsigned long long)(h.percentile_ns(99) / 1000), (unsigned long long)(h.max_ns / 1000),
            (unsigned long long)h.late, (unsigned long long)entry.id,
            (unsigned long long)entry.max_id,
            (unsigned long long)(std::chrono::duration_cast<std::chrono::microseconds>(report_time - entry.max_end).count()),
            (unsigned long long)interval_ns);
        switch_log_checkpoint(message, false);
    }
    for (const auto& entry : transfer_report) {
        if (!entry.count) continue;
        char message[256];
        std::snprintf(message, sizeof(message),
            "traffic: stage=%s count=%llu bytes=%llu interval_ns=%llu id=%llu",
            entry.name, (unsigned long long)entry.count, (unsigned long long)entry.bytes,
            (unsigned long long)interval_ns, (unsigned long long)entry.id);
        switch_log_checkpoint(message, false);
    }
}

extern "C" void switch_perf_record(const char* stage, uint64_t elapsed_ns, uint64_t id) {
    switch_perf_collect(stage, elapsed_ns, id, false);
}

extern "C" void switch_perf_record_bytes(const char* stage, uint64_t bytes, uint64_t id) {
    switch_perf_collect(stage, bytes, id, true);
}

void switch_set_profile_enabled(bool enabled) {
    switch_profile_enabled.store(enabled, std::memory_order_relaxed);
}
