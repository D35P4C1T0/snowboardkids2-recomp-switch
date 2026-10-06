#!/usr/bin/env python3
"""Check production RSP vector memory against N64 byte/DMEM-wrap semantics."""
from pathlib import Path
import os
import platform
import subprocess
import tempfile
root=Path(__file__).resolve().parent.parent
runtime=root/'build-switch-deps/N64ModernRuntime'
program=r'''
#define SK2_SWITCH_RSP_VECTOR_MEMORY 1
#include "librecomp/rsp.hpp"
#include "librecomp/rsp_vu_impl.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <utility>
uint8_t dmem[4096];
uint16_t rspReciprocals[512]{}, rspInverseSquareRoots[512]{};
template<unsigned E> void check() {
    RSP rsp{};
    std::array<uint8_t,4096> original{}, expected{};
    for(unsigned i=0;i<original.size();i++) original[i]=uint8_t(i*37U+(i>>4)+E);
    for(unsigned rs=0;rs<8192;rs++) for(int immediate:{-128,-1,0,1,127}) {
        const uint32_t address=rs+immediate*16;
        RSP::r128 vector{};
        for(unsigned i=0;i<16;i++) vector.byte(i)=uint8_t(i*13U+rs+E);
        auto expectedVector=vector;
        const unsigned count=16-(address&15);
        for(unsigned i=0;i<count && E+i<16;i++)
            expectedVector.byte(E+i)=original[((address+i)^3)&4095];
        std::memcpy(dmem,original.data(),4096);
        rsp.LQV<E>(vector,rs,int8_t(immediate));
        assert(std::memcmp(&vector,&expectedVector,16)==0);
        assert(std::memcmp(dmem,original.data(),4096)==0);
        // Store the loaded vector, including untouched lanes and wrapped e.
        expected=original;
        for(unsigned i=0;i<count;i++)
            expected[((address+i)^3)&4095]=vector.byte((E+i)&15);
        rsp.SQV<E>(vector,rs,int8_t(immediate));
        assert(std::memcmp(dmem,expected.data(),4096)==0);
    }
}
template<size_t... E> void all(std::index_sequence<E...>) { (check<E>(),...); }
int main() { all(std::make_index_sequence<16>{}); }
'''
# r128 is a nested RSP type in the production API.
with tempfile.TemporaryDirectory(prefix='sk2-rsp-memory-') as temp:
    temp=Path(temp); src=temp/'test.cpp'; exe=temp/'test'; src.write_text(program)
    options=['-std=c++20','-O2','-fno-strict-aliasing',
             '-I'+str(runtime/'N64Recomp/include'),'-I'+str(runtime/'librecomp/include'),
             '-I'+str(runtime/'ultramodern/include'),'-I'+str(runtime/'thirdparty/sse2neon')]
    if platform.machine() in ('x86_64','AMD64'): options.append('-msse4.1')
    subprocess.run([os.environ.get('CXX','c++'),*options,str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,timeout=30)
print('PASS: production LQV/SQV, all 16 elements, aligned/partial vectors, 8192 addresses, signed immediates, DMEM wrapping, untouched bytes')
