#!/usr/bin/env python3
"""Exercise production cache replacement, sample variants and loading geometry."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
tree = root / 'build-switch-deps/rt64/src'

def method(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n    }', start) + 6]

plume = (tree / 'contrib/plume/plume_vulkan.cpp').read_text()
store = method(plume, '    static bool storeSwitchPipelineCache(').replace('std::rename(', 'horizonRename(')
load = method(plume, '    static bool loadSwitchPipelineCache(')
cache = (tree / 'render/rt64_raster_shader_cache.cpp').read_text()
setup = method(cache, '    void RasterShaderCache::setup(')
progress = method(cache, '    std::pair<uint32_t, uint32_t> RasterShaderCache::warmupProgress(')

test = r'''
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
#include "common/rt64_switch_loading_bar.h"
const char* SwitchPipelineCachePath="cache.bin";
const char* SwitchPipelineCacheTemporaryPath="cache.tmp";
const char* SwitchPipelineCacheBackupPath="cache.bak";
constexpr size_t SwitchPipelineCacheSizeLimit=64*1024*1024;
bool failInstall=false;
int horizonRename(const char* from,const char* to) {
    if (std::filesystem::exists(to)) { errno=EEXIST;return -1; }
    if (failInstall && std::string(from)=="cache.tmp") { errno=EIO;return -1; }
    return std::rename(from,to);
}
''' + store + load + r'''
struct RenderDevice {};
enum class RenderShaderFormat { SPIRV };
struct RenderMultisampling { unsigned sampleCount=1; };
struct ShaderLibrary { bool usesHDR=false; };
struct RasterShader {};
unsigned createdUbers=0;
struct RasterShaderUber {
    unsigned id;
    RasterShaderUber(RenderDevice*,RenderShaderFormat,RenderMultisampling,const ShaderLibrary*,unsigned) : id(++createdUbers) {}
};
void switch_log_checkpoint(const char*,bool) {}
struct RasterShaderCache {
    RenderDevice* device=nullptr;
    RenderShaderFormat shaderFormat=RenderShaderFormat::SPIRV;
    RenderMultisampling multisampling;
    std::unique_ptr<RasterShaderUber> shaderUber;
    std::unordered_map<uint64_t,std::unique_ptr<RasterShader>> GPUShaders;
    std::unordered_map<uint64_t,bool> shaderHashes;
    struct SampleVariant {
        std::unique_ptr<RasterShaderUber> uber;
        std::unordered_map<uint64_t,std::unique_ptr<RasterShader>> shaders;
    };
    std::unordered_map<unsigned,SampleVariant> sampleVariants;
    unsigned ubershaderThreadCount=1;
    bool usesHDR=false;
    struct { void initialize() {} } optimizerCacheSPIRV;
    std::mutex submissionMutex,GPUShadersMutex;
    void loadPersistentShaderDescriptions() {
        // Description 1 is ready; description 2 was queued but cancelled at
        // the switch boundary. The restored hash must allow its resubmission.
        for (unsigned key : {1,2}) if (!shaderHashes[key]) shaderHashes[key]=true;
    }
    void setup(RenderDevice*,RenderShaderFormat,const ShaderLibrary*,const RenderMultisampling&);
    std::pair<uint32_t,uint32_t> warmupProgress();
};
''' + setup + progress + r'''
int main() {
    auto bar=RT64::SwitchLoadingBar::layout(1280,720,0.5f);
    assert(bar.left==320 && bar.right==960 && bar.top==345 && bar.bottom==375);
    assert(bar.fillRight==640);
    assert(RT64::SwitchLoadingBar::layout(1280,720,-1).fillRight==322);
    assert(RT64::SwitchLoadingBar::layout(1280,720,2).fillRight==958);
    assert(RT64::SwitchLoadingBar::layout(1280,720,NAN).fillRight==322);
    int previous=0;
    for (unsigned n=0;n<=100;n++) {
        int fill=RT64::SwitchLoadingBar::layout(1920,1080,float(n)/100).fillRight;
        assert(fill>=previous);previous=fill;
    }

    std::vector<uint8_t> a={1,2,3},b={4,5,6,7},actual;
    assert(storeSwitchPipelineCache(a.data(),a.size()));
    assert(storeSwitchPipelineCache(b.data(),b.size()));
    assert(loadSwitchPipelineCache(actual) && actual==b);
    // Simulate an interrupted destination replacement: the backup is valid.
    assert(horizonRename(SwitchPipelineCachePath,SwitchPipelineCacheBackupPath)==0);
    assert(loadSwitchPipelineCache(actual) && actual==b);
    assert(storeSwitchPipelineCache(a.data(),a.size()));
    assert(loadSwitchPipelineCache(actual) && actual==a);
    failInstall=true;
    assert(!storeSwitchPipelineCache(b.data(),b.size()));
    assert(loadSwitchPipelineCache(actual) && actual==a);
    failInstall=false;
    assert(horizonRename(SwitchPipelineCachePath,SwitchPipelineCacheBackupPath)==0);
    failInstall=true;
    assert(!storeSwitchPipelineCache(b.data(),b.size()));
    assert(loadSwitchPipelineCache(actual) && actual==a);
    failInstall=false;

    RenderDevice device;ShaderLibrary library;RasterShaderCache cache;
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{1});
    auto* native=cache.shaderUber.get();
    cache.GPUShaders[1]=std::make_unique<RasterShader>();
    auto* nativeSpecialized=cache.GPUShaders[1].get();
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{2});
    auto* two=cache.shaderUber.get();
    assert(two!=native && createdUbers==2);
    cache.GPUShaders[1]=std::make_unique<RasterShader>();
    auto* twoSpecialized=cache.GPUShaders[1].get();
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{4});
    auto* four=cache.shaderUber.get();
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{1});
    assert(cache.shaderUber.get()==native && cache.GPUShaders[1].get()==nativeSpecialized);
    assert(cache.warmupProgress()==std::make_pair(1u,2u));
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{2});
    assert(cache.shaderUber.get()==two && cache.GPUShaders[1].get()==twoSpecialized);
    cache.setup(&device,RenderShaderFormat::SPIRV,&library,{4});
    assert(cache.shaderUber.get()==four && createdUbers==3);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-shader-loading-') as temp:
    temp = Path(temp)
    source, executable = temp / 'test.cpp', temp / 'test'
    source.write_text(test)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-D__SWITCH__',
                    '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(tree), str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], cwd=temp, check=True)
print('PASS: centered loading geometry, clamped progress, Horizon cache replacement/recovery, retained 1X/2X/4X shaders and warmup counts')
