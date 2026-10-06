#!/usr/bin/env python3
"""Compare the generated audio RSP at O2/O3 on deterministic ABI tasks."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parent.parent
runtime=root/'build-switch-deps/N64ModernRuntime'
rom=root/'snowboardkids2.z64'
assert rom.is_file(), 'Provide the supported local ROM for audio task tables'
program=r'''
#include "librecomp/rsp.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <fstream>
#include <vector>
uint8_t dmem[0x1000];
uint16_t rspReciprocals[512]{}, rspInverseSquareRoots[512]{};
RspExitReason aspO2(uint8_t*,uint32_t);
RspExitReason aspO3(uint8_t*,uint32_t);
int main(int argc,char**argv) {
    assert(argc==2);
    std::array<uint8_t,0x260> tables{};
    std::ifstream input(argv[1],std::ios::binary);
    input.seekg(0x9de70); input.read(reinterpret_cast<char*>(tables.data()),tables.size());
    assert(input && tables[0x10]==0x11 && tables[0x11]==0x18);
    for(unsigned count:{32U,128U,320U}) for(unsigned gain:{0U,1U,0x4000U,0x7fffU,0x8000U,0xffffU})
    for(unsigned repeats:{1U,8U,40U}) {
        std::vector<uint8_t> original(0x10000);
        for(unsigned i=0;i<original.size();i++) original[i]=uint8_t(i*37U+gain+count);
        std::array<uint8_t,0x1000> initial{};
        for(unsigned i=0;i<tables.size();i++) initial[i^3]=tables[i];
        auto put=[&](unsigned address,uint32_t word) { std::memcpy(original.data()+address,&word,4); };
        unsigned cursor=0x6000;
        auto command=[&](uint32_t first,uint32_t second) { put(cursor,first); put(cursor+4,second); cursor+=8; };
        command(0x08000000, (0x200U<<16)|count); // Set input, output and byte count.
        command(0x02000200, count);            // Clear output.
        command(0x04000000, 0x1000);           // Load input waveform.
        for(unsigned i=0;i<repeats;i++) command(0x0c000000|gain,0x00000200); // Mix and saturate.
        command(0x06000000, 0x2000);           // Save output.
        uint32_t address=0x6000, size=cursor-address;
        std::memcpy(initial.data()+0xff0,&address,4);
        std::memcpy(initial.data()+0xff4,&size,4);
        auto first=original, second=original;
        std::memcpy(dmem,initial.data(),initial.size());
        assert(aspO2(first.data(),0)==RspExitReason::Broke);
        std::array<uint8_t,0x1000> firstDMEM{};
        std::memcpy(firstDMEM.data(),dmem,sizeof(dmem));
        std::memcpy(dmem,initial.data(),initial.size());
        assert(aspO3(second.data(),0)==RspExitReason::Broke);
        assert(first==second && std::memcmp(firstDMEM.data(),dmem,sizeof(dmem))==0);
        assert(std::memcmp(first.data()+0x2000,original.data()+0x2000,count)!=0);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-rsp-opt-') as temp:
    temp=Path(temp); compiler=os.environ.get('CXX','c++')
    options=['-std=c++20','-DNDEBUG','-fno-strict-aliasing',
             '-I'+str(runtime/'N64Recomp/include'),'-I'+str(runtime/'librecomp/include'),'-I'+str(runtime/'ultramodern/include'),
             '-I'+str(runtime/'thirdparty/sse2neon')]
    # Keep asserts in the harness; production objects use the release defines.
    for opt in ['2','3']:
        optimized=['-DSK2_SWITCH_RSP_VECTOR_MEMORY=1','-DRSP=SwitchOptimizedRSP',
                   '-DRspContext=SwitchOptimizedRspContext'] if opt=='3' else []
        subprocess.run([compiler,*options,*optimized,'-O'+opt,'-DaspMain=aspO'+opt,'-c',
                        str(root/'rsp/aspMain.cpp'),'-o',str(temp/('o'+opt+'.o'))],check=True)
    src=temp/'test.cpp'; src.write_text(program); exe=temp/'test'
    subprocess.run([compiler,*[x for x in options if x!='-DNDEBUG'],str(src),
                    str(temp/'o2.o'),str(temp/'o3.o'),'-o',str(exe)],check=True)
    subprocess.run([str(exe),str(rom)],check=True,timeout=20)
print('PASS: generated O2/O3 audio RSP, 54 load/clear/mix/save tasks, signed gain extremes, saturation, DMA chunk boundaries, full RDRAM/DMEM equality')
