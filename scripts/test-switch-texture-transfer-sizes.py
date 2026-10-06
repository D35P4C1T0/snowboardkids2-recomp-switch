#!/usr/bin/env python3
"""Execute production texture map/staging blocks against reused oversized buffers."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root/'build-switch-deps/rt64/src/render/rt64_texture_cache.cpp').read_text()
start = source.index('                    uint8_t *uploadData = reinterpret_cast<uint8_t *>(switchDecodedUploads[i]->map());')
write = source[start:source.index('                    dstTexture->memorySize = uploadSize;', start)]
start = source.index('                    RenderCommandList *stageCommandList = switchDecodedStageCommandLists[commandListIndex].get();')
stage = source[start:source.index('                    RenderCommandList *decodedCommandList', start)]
start = source.index('                            void *dstData = tmemUploadResources[i]->map();')
tmem = source[start:source.index('\n                        }', start)]
test = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
struct RenderRange { uint64_t begin,end; RenderRange(uint64_t b,uint64_t e):begin(b),end(e) {} };
struct Buffer {
    std::vector<uint8_t> bytes;
    bool mapped=false;
    size_t flushed=0;
    explicit Buffer(size_t size):bytes(size,0xa5) {}
    void* map() { assert(!mapped); mapped=true; return bytes.data(); }
    void unmap(unsigned subresource,const RenderRange* range) {
        assert(mapped && subresource==0 && range && range->begin==0 && range->end<=bytes.size());
        flushed=range->end; mapped=false;
    }
};
enum class RenderBarrierStage { COPY };
enum class RenderBufferAccess { READ,WRITE };
struct RenderBufferBarrier {
    Buffer* buffer; RenderBufferAccess access;
    RenderBufferBarrier(Buffer* b,RenderBufferAccess a):buffer(b),access(a) {}
};
struct RenderCommandList {
    int step=0; size_t copied=0;
    void begin() { assert(step==0); step++; }
    void barriers(RenderBarrierStage,RenderBufferBarrier barrier) {
        assert((step==1 && barrier.access==RenderBufferAccess::WRITE) ||
               (step==3 && barrier.access==RenderBufferAccess::READ)); step++;
    }
    void copyBufferRegion(Buffer* destination,Buffer* source,size_t size) {
        assert(step==2 && size<=source->flushed && size<=destination->bytes.size());
        std::memcpy(destination->bytes.data(),source->bytes.data(),size); copied=size; step++;
    }
    void end() { assert(step==4); step++; }
};
struct Texture { unsigned format=4; };
unsigned RenderFormatSize(unsigned format) { return format; }
struct Upload { unsigned width,height; uint64_t hash=9; std::vector<uint8_t> bytesTMEM; };
std::unordered_map<std::string,uint64_t> counters;
void RT64SwitchRecordBytes(const char* name,uint64_t bytes,uint64_t hash) {
    assert(hash==9); counters[name]+=bytes;
}
int main() {
    constexpr size_t capacity=256*256*4;
    std::vector<std::unique_ptr<Buffer>> switchDecodedUploads, switchDecodedDeviceUploads, tmemUploadResources;
    switchDecodedUploads.push_back(std::make_unique<Buffer>(capacity));
    switchDecodedDeviceUploads.push_back(std::make_unique<Buffer>(capacity));
    tmemUploadResources.push_back(std::make_unique<Buffer>(4096));
    std::vector<uint32_t> switchDecodedUploadSizes{capacity};
    std::vector<std::unique_ptr<RenderCommandList>> switchDecodedStageCommandLists;
    switchDecodedStageCommandLists.push_back(std::make_unique<RenderCommandList>());
    size_t i=0, commandListIndex=0, total=0, textures=0;
    Texture texture; auto dstTexture=&texture;
    // Grow/shrink/odd dimensions, multiple reuse cycles, tight RGBA footprints.
    for(auto dimensions:std::vector<std::pair<unsigned,unsigned>>{
        {1,1},{256,256},{3,17},{128,128},{1,3},{32,32},{17,15},{256,256},{2,1}}) {
        Upload upload{dimensions.first,dimensions.second,9,{}};
        unsigned uploadSize=upload.width*upload.height*4;
        std::vector<uint8_t> decodedBytes(uploadSize);
        for(unsigned n=0;n<uploadSize;n++) decodedBytes[n]=uint8_t(n*23+textures);
        auto oldSource=switchDecodedUploads[i]->bytes;
        auto oldDestination=switchDecodedDeviceUploads[i]->bytes;
''' + write + stage + r'''
        assert(!switchDecodedUploads[i]->mapped && switchDecodedUploads[i]->flushed==uploadSize);
        assert(switchDecodedStageCommandLists[0]->step==5);
        assert(switchDecodedStageCommandLists[0]->copied==uploadSize);
        assert(std::equal(decodedBytes.begin(),decodedBytes.end(),switchDecodedDeviceUploads[i]->bytes.begin()));
        assert(std::equal(oldSource.begin()+uploadSize,oldSource.end(),switchDecodedUploads[i]->bytes.begin()+uploadSize));
        assert(std::equal(oldDestination.begin()+uploadSize,oldDestination.end(),switchDecodedDeviceUploads[i]->bytes.begin()+uploadSize));
        switchDecodedStageCommandLists[0]->step=0;
        total+=uploadSize; textures++;
    }
    assert(counters["texture_cpu_write"]==total && counters["texture_gpu_staging"]==total);
    assert(counters["texture_staging_capacity"]==capacity*textures);
    for(size_t length:{1,3,17,2048,4096,7}) {
        Upload upload{0,0,9,std::vector<uint8_t>(length,0x37)};
        auto before=tmemUploadResources[i]->bytes;
''' + tmem + r'''
        assert(!tmemUploadResources[i]->mapped && tmemUploadResources[i]->flushed==length);
        assert(std::equal(upload.bytesTMEM.begin(),upload.bytesTMEM.end(),tmemUploadResources[i]->bytes.begin()));
        assert(std::equal(before.begin()+length,before.end(),tmemUploadResources[i]->bytes.begin()+length));
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-texture-size-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'; src.write_text(test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D__SWITCH__','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-fno-omit-frame-pointer',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production texture writes/flushes/staging copy only active bytes; retained tails, RGBA/TMEM reuse, traffic and barriers; ASan/UBSan')
