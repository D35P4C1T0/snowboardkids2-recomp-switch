#!/usr/bin/env python3
"""Verify production copy/swap SIMD boundaries, alignment, and untouched guards."""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sanitize', action='store_true', help='enable AddressSanitizer and UndefinedBehaviorSanitizer')
args = parser.parse_args()
code = r'''
#include "common/rt64_switch_memory.h"
#include <cassert>
#include <vector>
int main() {
    for(unsigned bytes:{0U,4U,8U,12U,16U,20U,28U,32U,36U,60U,64U,68U,1024U})
    for(unsigned srcOffset=0;srcOffset<16;srcOffset++) for(unsigned dstOffset=0;dstOffset<16;dstOffset++) {
        std::vector<uint8_t> input(bytes+32,0xae), output(bytes+32,0xcd);
        for(unsigned i=0;i<bytes;i++) input[srcOffset+i]=uint8_t(i*37U+bytes);
        auto expected=output;
        for(unsigned i=0;i<bytes;i++) expected[dstOffset+(i^3U)]=input[srcOffset+i];
        const auto original=input;
        RT64::switchCopySwap32(input.data()+srcOffset,output.data()+dstOffset,bytes);
        assert(output==expected && input==original);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-memory-transfer-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(code)
    flags=['-fsanitize=address,undefined'] if args.sanitize else []
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                    *flags,'-I',str(root/'build-switch-deps/rt64/src'),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production swap/copy helper, every 0–15 byte alignment, vector/tail sizes, untouched source and guards' +
      (', ASan and UBSan' if args.sanitize else ''))
