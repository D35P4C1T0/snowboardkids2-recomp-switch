#!/usr/bin/env python3
"""Verify production MSAA replacement excludes queue threads until publication."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parent.parent
source=(root/'build-switch-deps/rt64/src/hle/rt64_application.cpp').read_text()
start=source.index('    void Application::updateMultisampling()')
method=source[start:source.index('\n#ifdef _WIN32',start)].replace('Application::','')
stub=r'''
#include <cassert>
#include <cstdio>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
struct Queue {
    std::mutex threadMutex; unsigned waits=0,updated=0;
    void waitForWorkloadId(unsigned id) { assert(id==4); waits++; }
    void waitForPresentId(unsigned id) { assert(id==7); waits++; }
    void updateMultisampling();
};
Queue* work; Queue* present;
void excluded() {
    auto observer=std::async(std::launch::async, [] {
        std::unique_lock a(work->threadMutex,std::try_to_lock);
        std::unique_lock b(present->threadMutex,std::try_to_lock);
        assert(!a.owns_lock() && !b.owns_lock());
    });
    observer.get();
}
void Queue::updateMultisampling() { excluded(); updated++; }
struct RenderMultisampling { unsigned sampleCount; };
struct UserConfig { unsigned samples=2; unsigned msaaSampleCount() { return samples; } };
struct Device { struct { bool sampleLocations=true; } capabilities; auto getCapabilities() { return capabilities; } };
struct Interface { struct Capabilities { int shaderFormat=0; }; Capabilities getCapabilities() { return {}; } };
struct RasterShader {
    static RenderMultisampling generateMultisamplingPattern(unsigned n,bool available) { assert(available);return {n}; }
};
struct Library {
    bool replaced=false;
    void setupMultisamplingShaders(Interface*,Device*,RenderMultisampling m) { excluded(); assert(m.sampleCount==2); replaced=true; }
};
struct Uber { bool ready=false; void waitForPipelineCreation() { excluded(); ready=true; } };
struct Cache {
    Library* library;
    bool drained=false,destroyed=false,installed=false;
    std::unique_ptr<Uber> shaderUber=std::make_unique<Uber>();
    void waitForAll() { excluded(); drained=true; }
    void destroyAll() { excluded(); assert(drained); destroyed=true; }
    void setup(Device*,int,Library* l,RenderMultisampling m) { excluded(); assert(drained && !destroyed && l->replaced && m.sampleCount==2); installed=true; }
};
struct SwitchLoadingScreen {
    template<class... T> SwitchLoadingScreen(T...) { excluded(); }
    void draw(float progress) { excluded(); assert(progress==0); }
};
bool fastLoadActive=false;
struct SwitchFastLoad {
    SwitchFastLoad() { excluded(); assert(!fastLoadActive); fastLoadActive=true; }
    void finish() { excluded(); fastLoadActive=false; }
    ~SwitchFastLoad() { assert(!fastLoadActive); }
};
void waitForSwitchShaderWarmup(Cache* cache,SwitchLoadingScreen&) {
    excluded(); assert(cache->installed); cache->shaderUber->waitForPipelineCreation();
}
struct State {
    unsigned workloadId=4,presentId=7,updated=0;
    void updateMultisampling() { excluded(); updated++; }
};
struct Shared {
    Cache* cache; State* state;
    unsigned samples=1,targets=1,publications=0;
    void updateMultisampling(RenderMultisampling m) { excluded(); assert(samples==1); targets=m.sampleCount; }
    void setUserConfig(UserConfig config,bool discard) {
        assert(!fastLoadActive);
        excluded(); assert(discard && cache->installed && cache->shaderUber->ready);
        assert(work->updated==1 && state->updated==1 && targets==2 && samples==1);
        samples=config.samples; publications++;
    }
};
std::vector<std::string> checkpoints;
#define RT64_SWITCH_CHECKPOINT(x) checkpoints.emplace_back(x)
struct Application {
    std::unique_ptr<Device> device=std::make_unique<Device>();
    std::unique_ptr<Interface> renderInterface=std::make_unique<Interface>();
    std::unique_ptr<Queue> workloadQueue=std::make_unique<Queue>(),presentQueue=std::make_unique<Queue>();
    std::unique_ptr<Library> shaderLibrary=std::make_unique<Library>();
    std::unique_ptr<Cache> rasterShaderCache=std::make_unique<Cache>();
    std::unique_ptr<State> state=std::make_unique<State>();
    std::unique_ptr<Shared> sharedQueueResources=std::make_unique<Shared>();
    std::unique_ptr<int> presentGraphicsWorker=std::make_unique<int>(),swapChain=std::make_unique<int>();
    UserConfig userConfig;
    void destroyShaderCache() { assert(false); }
'''+method+r'''
};
int main() {
    Application app;
    work=app.workloadQueue.get(); present=app.presentQueue.get();
    app.sharedQueueResources->cache=app.rasterShaderCache.get();
    app.sharedQueueResources->state=app.state.get();
    app.updateMultisampling();
    assert(work->waits==1 && present->waits==1);
    assert(app.sharedQueueResources->samples==2 && app.sharedQueueResources->publications==1);
    assert(work->threadMutex.try_lock()); work->threadMutex.unlock();
    assert(present->threadMutex.try_lock()); present->threadMutex.unlock();
    // Missing programmable sample positions leaves resources untouched.
    app.device->capabilities.sampleLocations=false;
    app.updateMultisampling();
    assert(work->waits==1 && app.sharedQueueResources->publications==1);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-msaa-transition-') as temp:
    path=Path(temp)/'test.cpp';exe=Path(temp)/'test';path.write_text(stub)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D__SWITCH__','-DSAMPLE_LOCATIONS_REQUIRED=1',
                    '-Wall','-Wextra','-Werror','-pthread',str(path),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production MSAA transaction, drained queues, concurrent observers excluded throughout replacement, publication after shader readiness, lock release and capability guard')
