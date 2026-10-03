#!/usr/bin/env python3
"""Compile and exercise the production audio queue arithmetic on the host."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
test = r'''
#include "src/main/audio_queue.h"
#include <cassert>
#include <cstdio>
int main() {
    using namespace sk2::audio;
    assert(queued_microseconds(38400, 48000, 2) == 100000);
    assert(queued_microseconds(17640, 48000, 2) == 45937);
    assert(queued_microseconds(38400 - 8, 48000, 2) < 100000);
    assert(queued_microseconds(38400 + 8, 48000, 2) > 100000);
    assert(queued_microseconds(19200, 48000, 1) == 100000);
    assert(remaining_input_frames(38400, 22050, 48000, 2) == 2205);
    assert(remaining_input_frames(38400, 48000, 48000, 2) == 4800);
    assert(remaining_input_frames(38400, 32000, 48000, 2) == 3200);
    assert(queued_microseconds(7, 48000, 2) == 0);
    assert(queued_microseconds(8, 0, 2) == 0);
    assert(remaining_input_frames(38400, 22050, 0, 2) == 0);
    assert(queued_microseconds(UINT32_MAX, 48000, 2) > UINT32_MAX);
    puts("PASS: output queue units, input-rate conversion, thresholds, alignment, wide arithmetic");
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-audio-') as temp:
    src = Path(temp) / 'test.cpp'
    exe = Path(temp) / 'test'
    src.write_text(test)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra',
                    '-Werror', '-I', str(root), str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
