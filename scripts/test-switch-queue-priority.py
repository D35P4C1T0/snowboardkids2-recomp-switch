#!/usr/bin/env python3
"""Verify exclusivity and progress of the production Switch queue mutex."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
test = r'''
#include "plume_queue_mutex.h"
#include <cassert>
#include <chrono>
#include <future>
#include <thread>
#include <vector>
using namespace std::chrono_literals;
int main() {
    for (bool priority : {false, true}) {
        plume::SwitchQueueMutex mutex(priority);
        int count = 0;
        std::vector<std::thread> threads;
        for (int t = 0; t < 8; ++t) threads.emplace_back([&, t] {
            for (int i = 0; i < 2000; ++i) {
                if (t % 2) {
                    mutex.lockPresent();
                    std::unique_lock lock(mutex, std::adopt_lock);
                    ++count;
                } else {
                    std::lock_guard lock(mutex);
                    ++count;
                }
            }
        });
        for (auto& thread : threads) thread.join();
        assert(count == 16000);
    }
    plume::SwitchQueueMutex mutex(true);
    mutex.lock();
    std::promise<void> presentEntered, releasePresent, submitEntered;
    auto presentReady = presentEntered.get_future();
    auto release = releasePresent.get_future();
    auto submitReady = submitEntered.get_future();
    std::thread present([&] {
        mutex.lockPresent();
        std::unique_lock lock(mutex, std::adopt_lock);
        presentEntered.set_value();
        release.wait();
    });
    auto deadline = std::chrono::steady_clock::now() + 5s;
    while (mutex.waitingPresents() != 1) {
        assert(std::chrono::steady_clock::now() < deadline);
        std::this_thread::yield();
    }
    std::thread submit([&] {
        std::lock_guard lock(mutex);
        submitEntered.set_value();
    });
    mutex.unlock();
    assert(presentReady.wait_for(5s) == std::future_status::ready);
    assert(submitReady.wait_for(20ms) == std::future_status::timeout);
    releasePresent.set_value();
    assert(submitReady.wait_for(5s) == std::future_status::ready);
    present.join(); submit.join();
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-queue-priority-') as temp:
    source = Path(temp) / 'test.cpp'
    exe = Path(temp) / 'test'
    source.write_text(test)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-O2',
                    '-pthread', '-Wall', '-Wextra', '-Werror',
                    '-I', str(root / 'build-switch-deps/rt64/src/contrib/plume'),
                    str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=20)
print('Switch queue priority: exclusivity, presentation ordering and progress passed')
