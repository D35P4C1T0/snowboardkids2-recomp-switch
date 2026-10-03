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
#include <vector>
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
    QueueCorrector corrector;
    std::vector<float> input(200 * 2), output, joined;
    // Exact unity-rate continuity, including single-frame chunks.
    for (int chunk=0; chunk<4; chunk++) {
        for (int i=0; i<200; i++) {
            input[i*2] = float(chunk*200+i);
            input[i*2+1] = -input[i*2];
        }
        corrector.process(input.data(), 200, 60000, output);
        joined.insert(joined.end(), output.begin(), output.end());
    }
    assert(joined.size() == 799*2);
    for (size_t i=0; i<799; i++) assert(joined[i*2]==float(i) && joined[i*2+1]==-float(i));
    corrector.reset();
    for (int i=0; i<200; i++) {
        float pair[]={float(i), -float(i)};
        corrector.process(pair, 1, 60000, output);
        assert(output.size() == (i ? 2 : 0));
        if (i) assert(output[0]==float(i-1) && output[1]==-float(i-1));
    }
    // High backlog shortens output gradually, preserving stereo and phase.
    corrector.reset();
    float last=-1;
    size_t count=0;
    for (int chunk=0; chunk<400; chunk++) {
        for (int i=0; i<200; i++) {
            input[i*2]=float(chunk*200+i);
            input[i*2+1]=-input[i*2];
        }
        corrector.process(input.data(), 200, 300000, output);
        assert(output.size()%2==0);
        for (size_t i=0; i<output.size(); i+=2) {
            assert(output[i]>last && output[i]-last < 1.1f);
            assert(output[i+1]==-output[i]);
            last=output[i];
        }
        count+=output.size()/2;
    }
    assert(count < 79999 && count > 78000);
    assert(corrector.correction() <= 0.020001);
    for (int i=0; i<400; i++) corrector.process(input.data(), 200, 40000, output);
    assert(corrector.correction()==0.0);
    corrector.reset();
    corrector.process(input.data(), 200, 60000, output);
    assert(output.size()==398 && corrector.correction()==0.0);
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
