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
start = source.index('    bool NativeTarget::copyToNativeCPU(')
record_method = source[start:source.index('\n    }', start)+6].replace('bool NativeTarget::', 'bool ')
start = source.index('    bool NativeTarget::copyToRDRAMCPU(')
fused_method = source[start:source.index('\n    }', start)+6].replace('bool NativeTarget::', 'bool ')
fb_source = (root/'build-switch-deps/rt64/src/hle/rt64_framebuffer.cpp').read_text()
start = fb_source.index('    void Framebuffer::copyNativeToRAMCPU(')
commit_method = fb_source[start:fb_source.index('\n    }', start)+6].replace('void Framebuffer::', 'void ')
start = fb_source.index('    uint32_t Framebuffer::copyRAMToNativeAndChanges(')
upload_method = fb_source[start:fb_source.index('\n    }', start)+6].replace('uint32_t Framebuffer::', 'uint32_t ')
start = source.index('        void *dstData = readBuffer.nativeUploadBuffer->map();')
map_upload = source[start:source.index('        if (hasCurrentResource)',start)]
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
#include "common/rt64_switch_memory.h"
using RT64::switchFusedRAMTransfersEnabled;
using RT64::switchCopySwap32;
#define _byteswap_ulong __builtin_bswap32
static void RT64SwitchRecordBytes(const char*, uint64_t) {}
struct RT64SwitchPerfScope { explicit RT64SwitchPerfScope(const char*) {} };
constexpr unsigned G_IM_SIZ_16b=2, G_IM_FMT_RGBA=0, G_IM_FMT_DEPTH=6;
enum class RenderFormat { RGBA8, D32, RG8, R8G8B8A8_UNORM=RGBA8, D32_FLOAT=D32, R8G8_UNORM=RG8 };
static unsigned RenderFormatSize(RenderFormat format) { return format==RenderFormat::RG8 ? 2 : 4; }
struct RenderRange { unsigned size; RenderRange(unsigned offset,unsigned count):size(count) { assert(offset==0); } };
struct FakeBuffer {
    std::vector<uint8_t> bytes;
    bool mapped=false;
    unsigned expectedWrite=0;
    void* map() { assert(!mapped); mapped=true; return bytes.data(); }
    void* map(unsigned offset, RenderRange* range) {
        assert(!mapped && !offset && range->size==bytes.size()); mapped=true; return bytes.data();
    }
    void unmap() { assert(mapped); mapped=false; }
    void unmap(unsigned subresource, const RenderRange* range) {
        assert(!subresource && range && range->size==expectedWrite); unmap();
    }
};
struct RenderTexture {};
struct ShaderLibrary { bool usesHDR=false; };
struct RenderTarget {
    unsigned width=320,height=240;
    struct { unsigned sampleCount=1; } multisampling;
    RenderFormat format=RenderFormat::RGBA8;
    RenderTexture texture;
    void resolveTarget(void*, const ShaderLibrary*) {}
    RenderTexture* getResolvedTexture() { return &texture; }
};
struct RenderBufferDesc {
    unsigned bytes;
    static RenderBufferDesc ReadbackBuffer(unsigned bytes) { return {bytes}; }
};
struct RenderTextureCopyLocation {
    RenderFormat format{}; unsigned width=0,height=0,rowWidth=0; FakeBuffer* buffer=nullptr;
    static RenderTextureCopyLocation PlacedFootprint(FakeBuffer* b,RenderFormat f,unsigned w,unsigned h,unsigned d,unsigned r) {
        assert(d==1); return {f,w,h,r,b};
    }
    static RenderTextureCopyLocation Subresource(RenderTexture*) { return {}; }
};
struct RenderBox { unsigned start,end,width; RenderBox(unsigned x,unsigned y,unsigned w,unsigned e):start(y),end(e),width(w) {assert(!x);} };
enum class RenderBarrierStage { COPY };
enum class RenderBufferAccess { WRITE };
enum class RenderTextureLayout { COPY_SOURCE };
struct RenderBufferBarrier { RenderBufferBarrier(FakeBuffer*,RenderBufferAccess) {} };
struct RenderTextureBarrier { RenderTextureBarrier(RenderTexture*,RenderTextureLayout) {} };
struct FakeDevice {
    std::unique_ptr<FakeBuffer> createBuffer(RenderBufferDesc desc) {
        auto b=std::make_unique<FakeBuffer>(); b->bytes.resize(desc.bytes); return b;
    }
};
struct FakeList {
    unsigned copies=0, lastBytes=0, lastStart=0;
    void barriers(RenderBarrierStage, RenderBufferBarrier, RenderTextureBarrier) {}
    void copyTextureRegion(RenderTextureCopyLocation dest,RenderTextureCopyLocation,unsigned x,unsigned y,unsigned z,const RenderBox* box) {
        assert(!x && !y && !z && dest.width==dest.rowWidth && dest.width==box->width);
        assert(dest.height==box->end-box->start);
        lastBytes=dest.width*dest.height*RenderFormatSize(dest.format);
        assert(lastBytes<=dest.buffer->bytes.size()); lastStart=box->start; copies++;
    }
};
struct RenderWorker { FakeDevice* device; FakeList* commandList; };
struct FramebufferChange {};
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
upload_stub = r'''
    std::vector<uint8_t> lastUpload;
    static unsigned getNativeSize(unsigned width,unsigned height,unsigned size) { return (width << size >> 1)*height; }
    unsigned copyFromRAM(RenderWorker*,FramebufferChange&,unsigned width,unsigned height,unsigned,unsigned siz,unsigned,
                         const uint8_t* data,bool,const ShaderLibrary*,bool swapWords=false) {
        unsigned bufferSize=getNativeSize(width,height,siz);
        struct { std::unique_ptr<FakeBuffer> nativeUploadBuffer=std::make_unique<FakeBuffer>(); } readBuffer;
        readBuffer.nativeUploadBuffer->bytes.resize(bufferSize*2,0xab);
        readBuffer.nativeUploadBuffer->expectedWrite=bufferSize;
''' + map_upload + r'''
        assert(!readBuffer.nativeUploadBuffer->mapped);
        const auto& uploaded=readBuffer.nativeUploadBuffer->bytes;
        assert(std::all_of(uploaded.begin()+bufferSize,uploaded.end(),[](uint8_t b){return b==0xab;}));
        lastUpload.assign(uploaded.begin(),uploaded.begin()+bufferSize);
        return width*height;
    }
'''
fb_stub = r'''
struct Framebuffer {
    NativeTarget& nativeTarget;
    unsigned width=0,height=0,siz=G_IM_SIZ_16b;
    std::vector<uint8_t> nativeSwappedRAM;
    unsigned imageRowBytes(unsigned width) { return width<<siz>>1; }
''' + commit_method + upload_method + '\n};\n'
tests = r'''
int main(int argc,char**argv) {
    assert(argc==2);
    if(std::strcmp(argv[1],"gpu")==0) {
        FakeDevice device; FakeList list; RenderWorker worker{&device,&list};
        ShaderLibrary library; RenderTarget input; NativeTarget target;
        input.format=RenderFormat::RG8;
        for(unsigned width:{1U,3U,285U,320U}) for(unsigned start:{0U,7U}) {
            unsigned end=start+3;
            assert(target.copyToNativeCPU(&worker,&input,width,start,end,G_IM_SIZ_16b,G_IM_FMT_RGBA,3,0,&library,true));
            assert(list.lastBytes==width*3*2 && list.lastStart==start);
            assert(target.switchTextureReadbackEncodedBytes);
            assert(target.switchTextureReadbackRenderFormat==RenderFormat::RG8);
        }
        unsigned copies=list.copies;
        assert(!target.copyToNativeCPU(&worker,&input,3,0,3,G_IM_SIZ_16b,G_IM_FMT_RGBA,3,0,&library,false));
        input.multisampling.sampleCount=2;
        assert(!target.copyToNativeCPU(&worker,&input,3,0,3,G_IM_SIZ_16b,G_IM_FMT_RGBA,3,0,&library,true));
        assert(list.copies==copies);
        return 0;
    }
    if(std::strcmp(argv[1],"default")==0) unsetenv("SK2_SWITCH_CACHE_READBACKS");
    else setenv("SK2_SWITCH_CACHE_READBACKS",argv[1],1);
    const bool cached=std::strcmp(argv[1],"0")!=0;
    const bool directEncoded=std::strcmp(argv[1],"encoded")==0 || std::strcmp(argv[1],"default")==0;
    if(std::strcmp(argv[1],"default")==0) unsetenv("SK2_SWITCH_DIRECT_ENCODED_READBACKS");
    else setenv("SK2_SWITCH_DIRECT_ENCODED_READBACKS",directEncoded?"1":"0",1);
    setenv("SK2_SWITCH_FUSED_RAM_TRANSFERS",std::strcmp(argv[1],"fused")==0?"1":"0",1);
    NativeTarget target;
    const unsigned widths[]={320,1,3,13,15,16,17,31,32,33,285};
    for(unsigned width:widths) for(unsigned height:{1U,3U,52U})
    for(unsigned start:{0U,7U}) for(unsigned kind:{0U,1U,2U,3U}) for(unsigned pattern=0;pattern<4;pattern++) {
        auto& input=target.switchTextureReadbackBuffer->bytes;
        input.resize(width*height*4);
        for(unsigned i=0;i<input.size();i++) input[i]=uint8_t(i*37U+width+pattern+start);
        if(kind==2) for(unsigned i=0;i<width*height;i++) {
            const float samples[]={0.0f,0.5f,1.0f,-1.0f,2.0f,NAN,INFINITY};
            float depth=samples[i%7]; std::memcpy(input.data()+i*4,&depth,4);
        }
        if(kind==3) {
            for(unsigned i=0;i<width*height;i++) {
                input[i*2]=input[i*4]; input[i*2+1]=input[i*4+1];
            }
            input.resize(width*height*2);
        }
        target.switchTextureReadbackBufferSize=input.size();
        target.switchTextureReadbackRowWidth=width;
        target.switchTextureReadbackRowStart=start;
        target.switchTextureReadbackRowEnd=start+height;
        target.switchTextureReadbackEncodedBytes=kind==1 || kind==3;
        target.switchTextureReadbackN64Format=kind==2 ? G_IM_FMT_DEPTH : G_IM_FMT_RGBA;
        target.switchTextureReadbackRenderFormat=kind==2 ? RenderFormat::D32 : kind==3 ? RenderFormat::RG8 : RenderFormat::RGBA8;
        target.switchTextureReadbackDitherPattern=pattern;
        target.switchTextureReadbackDitherSeed=0x01234567;
        std::vector<uint8_t> output(width*height*2+16,0xad);
        if((directEncoded && kind==1) || kind==3) target.switchTextureReadbackCache.assign(11,0xed);
        const auto previousCache=target.switchTextureReadbackCache;
        target.copyToRAMCPU(output.data()+8);
        assert(!target.switchTextureReadbackBuffer->mapped);
        for(unsigned i=0;i<8;i++) assert(output[i]==0xad && output[output.size()-1-i]==0xad);
        if(kind==3) assert(std::equal(input.begin(),input.end(),output.begin()+8));
        if(kind==1) for(unsigned i=0;i<width*height;i++) {
            assert(output[8+i*2]==input[i*4]);
            assert(output[8+i*2+1]==input[i*4+1]);
        }
        if((directEncoded && kind==1) || kind==3) assert(target.switchTextureReadbackCache==std::vector<uint8_t>(11,0xed));
        else if(cached) assert(target.switchTextureReadbackCache==input);
        else assert(target.switchTextureReadbackCache==previousCache);
        // Execute the production Framebuffer commit, including the old swap
        // loop for odd rows/partial words, against an independent byte oracle.
        Framebuffer fb{target,width,start+height,G_IM_SIZ_16b,{}};
        const unsigned rowOffset=start*width*2;
        std::vector<uint8_t> committed(rowOffset+width*height*2+32,0xad);
        auto expected=committed;
        const unsigned byteCount=width*height*2;
        if(byteCount>=4) {
            std::copy(output.begin()+8,output.begin()+8+byteCount,expected.begin()+8+rowOffset);
            for(unsigned i=0;i+4<=byteCount;i+=4)
                std::reverse(expected.begin()+8+rowOffset+i,expected.begin()+8+rowOffset+i+4);
        } else {
            for(unsigned i=0;i<byteCount;i++) expected[8+rowOffset+(i^3)]=output[8+i];
        }
        fb.copyNativeToRAMCPU(committed.data()+8,width,start,start+height);
        assert(committed==expected && !target.switchTextureReadbackBuffer->mapped);
        // Only an aligned whole-word packed transfer may use the fused path.
        std::vector<uint8_t> probe(16+byteCount,0xcc);
        const bool eligible=kind==3 && byteCount%4==0;
        const bool enabled=std::strcmp(argv[1],"fused")==0;
        assert(target.copyToRDRAMCPU(probe.data()+8)==(eligible && enabled));
        assert(!target.switchTextureReadbackBuffer->mapped);
        if(!eligible || !enabled) assert(probe==std::vector<uint8_t>(16+byteCount,0xcc));
        assert(!target.copyToRDRAMCPU(probe.data()+9));
        assert(!target.switchTextureReadbackBuffer->mapped);
        assert(std::fwrite(committed.data(),1,committed.size(),stdout)==committed.size());
        assert(std::fwrite(output.data(),1,output.size(),stdout)==output.size());
    }
    FramebufferChange change; ShaderLibrary library; RenderWorker worker{};
    for(unsigned siz:{1U,2U,3U}) for(unsigned width:{1U,3U,16U,285U,320U}) for(unsigned rows:{1U,3U,52U}) {
        Framebuffer fb{target,width,rows,siz,{}};
        unsigned bytes=NativeTarget::getNativeSize(width,rows,siz);
        // Keep scratch tails recognizable, matching the reference's full-word
        // swap semantics even for tiny odd-sized uploads.
        fb.nativeSwappedRAM.assign(bytes+11,0xef);
        std::vector<uint8_t> input(bytes+16,0xcd), expected(bytes,0xef);
        for(unsigned i=0;i<bytes;i++) input[8+i]=uint8_t(i*37+siz);
        for(unsigned i=0;i+4<=bytes;i+=4) for(unsigned lane=0;lane<4;lane++)
            expected[i+lane]=input[8+i+3-lane];
        const auto oldScratch=fb.nativeSwappedRAM;
        assert(fb.copyRAMToNativeAndChanges(&worker,change,input.data()+8,0,rows,G_IM_FMT_RGBA,true,&library)==width*rows);
        assert(target.lastUpload==expected);
        if(std::strcmp(argv[1],"fused")==0 && bytes%4==0) assert(fb.nativeSwappedRAM==oldScratch);
        for(unsigned i=0;i<8;i++) assert(input[i]==0xcd && input[input.size()-1-i]==0xcd);
        assert(std::fwrite(target.lastUpload.data(),1,target.lastUpload.size(),stdout)==target.lastUpload.size());
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-readback-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(stub.split('struct NativeTarget')[0]+helpers+'\nstruct NativeTarget'+stub.split('struct NativeTarget')[1]+upload_stub+record_method+fused_method+method+'\n};\n'+fb_stub+tests)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D_POSIX_C_SOURCE=200809L',
                    '-O2','-Wall','-Wextra','-Werror','-D__SWITCH__','-I',str(root/'build-switch-deps/rt64/src'),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe),'gpu'],check=True)
    direct=subprocess.check_output([str(exe),'0'])
    cached=subprocess.check_output([str(exe),'1'])
    default=subprocess.check_output([str(exe),'default'])
    encoded=subprocess.check_output([str(exe),'encoded'])
    fused=subprocess.check_output([str(exe),'fused'])
    assert direct==cached==default==encoded==fused, 'Framebuffer encoding changed output'
print('PASS: cached/direct RGBA16 dithering, encoded depth bytes, packed RG8 bytes, float depth, odd widths, row offsets, resize reuse, bounds, unmap, fused RAM byte order and upload scratch bypass')
