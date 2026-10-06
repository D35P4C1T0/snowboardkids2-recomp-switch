#!/usr/bin/env python3
"""Check bounded profiling histograms and overflow percentile behavior."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
test = r'''
#include "switch/perf_stats.h"
#include <cassert>
int main() {
    sk2::perf::Histogram h;
    assert(h.percentile_ns(99)==0);
    for (int i=0; i<100; i++) h.add(16'666'667);
    assert(h.count==100 && !h.late && h.percentile_ns(95)==16'750'000);
    h.add(100'000'000);
    assert(h.late==1 && h.max_ns==100'000'000);
    assert(h.percentile_ns(100)==100'000'000);
    h={}; h.add(0);
    assert(h.percentile_ns(50)==0);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-perf-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror',
                    '-I',str(root),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: percentile buckets, frame deadline, zero events, overflow, reset')

# Exercise the production collector with a stalled log sink. Other timing
# producers must complete before the sink is released, with no lost samples.
collector_test = r'''
#include "switch/profiling.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
using namespace std::chrono_literals;
std::mutex sinkMutex;
std::condition_variable sinkChanged;
bool sinkEntered=false, releaseSink=false;
std::vector<std::string> messages;
void switch_log_checkpoint(const char* message, bool) {
    std::unique_lock lock(sinkMutex);
    sinkEntered=true;
    sinkChanged.notify_all();
    sinkChanged.wait(lock, [] { return releaseSink; });
    messages.emplace_back(message);
}
int main() {
    switch_set_profile_enabled(true);
    switch_perf_record("first", 1000, 1);
    std::this_thread::sleep_for(2100ms);
    auto reporter=std::async(std::launch::async, [] {
        switch_perf_record("first", 3000, 2);
    });
    {
        std::unique_lock lock(sinkMutex);
        assert(sinkChanged.wait_for(lock, 1s, [] { return sinkEntered; }));
    }
    std::vector<std::future<void>> producers;
    for (int i=0; i<8; i++) producers.emplace_back(std::async(std::launch::async, [] {
        for (int j=0; j<100; j++) {
            switch_perf_record("concurrent", 2000, 3);
            switch_perf_record_bytes("readback", 320*240*2, 3);
        }
    }));
    for (auto& producer : producers) {
        assert(producer.wait_for(1s)==std::future_status::ready);
        producer.get();
    }
    // Cross another report deadline while the first sink is still stalled.
    // The snapshot lock must be attempted without blocking or losing samples.
    std::this_thread::sleep_for(2100ms);
    auto overlapping=std::async(std::launch::async, [] {
        switch_perf_record("concurrent", 2000, 6);
    });
    assert(overlapping.wait_for(1s)==std::future_status::ready);
    overlapping.get();
    {
        std::lock_guard lock(sinkMutex);
        releaseSink=true;
    }
    sinkChanged.notify_all();
    reporter.get();
    assert(messages.size()==1);
    assert(messages[0].find("stage=first count=2 mean_us=2")!=std::string::npos);
    assert(messages[0].find("max_id=2 max_age_us=")!=std::string::npos);
    assert(messages[0].find("interval_ns=")!=std::string::npos);
    // Disabled samples must not enter the next window.
    switch_set_profile_enabled(false);
    switch_perf_record("concurrent", 1000000, 4);
    switch_perf_record_bytes("readback", 1, 4);
    switch_set_profile_enabled(true);
    switch_perf_record("trigger", 0, 5);
    assert(messages.size()==4);
    assert(messages[1].find("stage=concurrent count=801 mean_us=2")!=std::string::npos);
    // Equal peaks keep the first maximum, not the last workload in the window.
    assert(messages[1].find("id=6 max_id=3 max_age_us=")!=std::string::npos);
    assert(messages[2].find("stage=trigger count=1")!=std::string::npos);
    assert(messages[3].find("traffic: stage=readback count=800 bytes=122880000 interval_ns=")!=std::string::npos);
    // Both collections reset after snapshotting.
    std::this_thread::sleep_for(2100ms);
    switch_perf_record_bytes("readback", 2, 7);
    assert(messages.size()==5);
    assert(messages[4].find("stage=readback count=1 bytes=2")!=std::string::npos);
    // All framebuffer + texture categories fit without dropped counters.
    static const char* names[]={"a","b","c","d","e","f","g","h","i","j","k","l"};
    for(auto name:names) switch_perf_record_bytes(name,17,8);
    std::this_thread::sleep_for(2100ms);
    switch_perf_record("trigger",0,9);
    assert(messages.size()==18);
    for(auto name:names) {
        std::string expected=std::string("traffic: stage=")+name+" count=1 bytes=17";
        bool found=false;
        for(const auto& message:messages) found|=message.find(expected)!=std::string::npos;
        assert(found);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-perf-collector-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(collector_test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror',
                    '-pthread','-I',str(root),str(src),str(root/'switch/profiling.cpp'),
                    '-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,timeout=20)
print('PASS: stalled reporting does not block producers, concurrent counts, window reset, disabled samples')
