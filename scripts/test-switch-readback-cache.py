#!/usr/bin/env python3
"""Compare actual direct/cached framebuffer encoders byte for byte."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
subprocess.run(['git', '-C', str(root/'build-switch-deps/rt64'), 'apply', '--reverse', '--check',
                str(root/'switch/patches/rt64-switch.patch')], check=True)
source = (root/'build-switch-deps/rt64/src/render/rt64_native_target.cpp').read_text()
helpers = source[source.index('namespace {'):source.index('\n}\n#endif')+2]
start = source.index('    void NativeTarget::copyToRAMCPU(')
method = source[start:source.index('\n    }', start)+6].replace('void NativeTarget::', 'void ')
stub = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
struct RT64SwitchPerfScope { explicit RT64SwitchPerfScope(const char*) {} };
constexpr unsigned G_IM_SIZ_16b=2, G_IM_FMT_RGBA=0, G_IM_FMT_DEPTH=6;
enum class RenderFormat { RGBA8, D32 };
static unsigned RenderFormatSize(RenderFormat) { return 4; }
struct RenderRange { unsigned size; RenderRange(unsigned offset,unsigned count):size(count) { assert(offset==0); } };
struct FakeBuffer {
    std::vector<uint8_t> bytes;
    bool mapped=false;
    void* map(unsigned offset, RenderRange* range) {
        assert(!mapped && !offset && range->size==bytes.size()); mapped=true; return bytes.data();
    }
    void unmap() { assert(mapped); mapped=false; }
};
struct NativeTarget {
    std::unique_ptr<FakeBuffer> switchTextureReadbackBuffer=std::make_unique<FakeBuffer>();
    std::vector<uint8_t> switchTextureReadbackCache;
    uint32_t switchTextureReadbackBufferSize=0, switchTextureReadbackRowWidth=0,
        switchTextureReadbackRowStart=0, switchTextureReadbackRowEnd=0,
        switchTextureReadbackDitherPattern=0, switchTextureReadbackDitherSeed=0;
    uint8_t switchTextureReadbackSize=G_IM_SIZ_16b, switchTextureReadbackN64Format=G_IM_FMT_RGBA;
    RenderFormat switchTextureReadbackRenderFormat=RenderFormat::RGBA8;
    bool switchTextureReadbackEncodedBytes=false;
'''
tests = r'''
int main(int argc,char**argv) {
    assert(argc==2);
    if(std::strcmp(argv[1],"default")==0) unsetenv("SK2_SWITCH_CACHE_READBACKS");
    else setenv("SK2_SWITCH_CACHE_READBACKS",argv[1],1);
    const bool cached=std::strcmp(argv[1],"0")!=0;
    const bool directEncoded=std::strcmp(argv[1],"encoded")==0 || std::strcmp(argv[1],"default")==0;
    if(std::strcmp(argv[1],"default")==0) unsetenv("SK2_SWITCH_DIRECT_ENCODED_READBACKS");
    else setenv("SK2_SWITCH_DIRECT_ENCODED_READBACKS",directEncoded?"1":"0",1);
    NativeTarget target;
    const unsigned widths[]={320,1,3,13,15,16,17,31,32,33,285};
    for(unsigned width:widths) for(unsigned height:{1U,3U,52U})
    for(unsigned start:{0U,7U}) for(unsigned kind:{0U,1U,2U}) for(unsigned pattern=0;pattern<4;pattern++) {
        auto& input=target.switchTextureReadbackBuffer->bytes;
        input.resize(width*height*4);
        for(unsigned i=0;i<input.size();i++) input[i]=uint8_t(i*37U+width+pattern+start);
        if(kind==2) for(unsigned i=0;i<width*height;i++) {
            const float samples[]={0.0f,0.5f,1.0f,-1.0f,2.0f,NAN,INFINITY};
            float depth=samples[i%7]; std::memcpy(input.data()+i*4,&depth,4);
        }
        target.switchTextureReadbackBufferSize=input.size();
        target.switchTextureReadbackRowWidth=width;
        target.switchTextureReadbackRowStart=start;
        target.switchTextureReadbackRowEnd=start+height;
        target.switchTextureReadbackEncodedBytes=kind==1;
        target.switchTextureReadbackN64Format=kind==2 ? G_IM_FMT_DEPTH : G_IM_FMT_RGBA;
        target.switchTextureReadbackRenderFormat=kind==2 ? RenderFormat::D32 : RenderFormat::RGBA8;
        target.switchTextureReadbackDitherPattern=pattern;
        target.switchTextureReadbackDitherSeed=0x01234567;
        std::vector<uint8_t> output(width*height*2+16,0xad);
        if(directEncoded && kind==1) target.switchTextureReadbackCache.assign(11,0xed);
        target.copyToRAMCPU(output.data()+8);
        assert(!target.switchTextureReadbackBuffer->mapped);
        for(unsigned i=0;i<8;i++) assert(output[i]==0xad && output[output.size()-1-i]==0xad);
        if(kind==1) for(unsigned i=0;i<width*height;i++) {
            assert(output[8+i*2]==input[i*4]);
            assert(output[8+i*2+1]==input[i*4+1]);
        }
        if(directEncoded && kind==1) assert(target.switchTextureReadbackCache==std::vector<uint8_t>(11,0xed));
        else if(cached) assert(target.switchTextureReadbackCache==input);
        else assert(target.switchTextureReadbackCache.empty());
        assert(std::fwrite(output.data(),1,output.size(),stdout)==output.size());
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-readback-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(stub.split('struct NativeTarget')[0]+helpers+'\nstruct NativeTarget'+stub.split('struct NativeTarget')[1]+method+'\n};\n'+tests)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D_POSIX_C_SOURCE=200809L',
                    '-O2','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    direct=subprocess.check_output([str(exe),'0'])
    cached=subprocess.check_output([str(exe),'1'])
    default=subprocess.check_output([str(exe),'default'])
    encoded=subprocess.check_output([str(exe),'encoded'])
    assert direct==cached==default==encoded, 'Framebuffer encoding changed output'
print('PASS: cached/direct RGBA16 dithering, encoded depth bytes, float depth, odd widths, row offsets, resize reuse, bounds and unmap')
