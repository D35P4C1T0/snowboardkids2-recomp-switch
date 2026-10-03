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
