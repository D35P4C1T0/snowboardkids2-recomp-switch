#!/usr/bin/env python3
"""Check actual texture upload scheduling, including prefix and staging fences."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root / 'build-switch-deps/rt64/src/render/rt64_texture_cache.cpp').read_text()
start = source.index('                    const size_t decodedCount = switchDecodedCommandIndices.size();')
end = source.index('                    switchDirectWaitComplete = true;', start)
schedule = source[start:end]
test = r'''
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
struct RenderCommandList { int kind, index; };
struct TextureUpload { unsigned width=16, height=16; };
void plume_switch_set_submit_context(const char*) {}
struct Queue {
    bool prefix=false;
    int prefixes=0, stages=0, images=0, submits=0;
    std::vector<bool> ready, done;
    std::vector<const RenderCommandList*> pending;
    explicit Queue(int n):ready(n),done(n) {}
    void executeCommandLists(const RenderCommandList* const* lists, unsigned count,
        void*, unsigned, void*, unsigned, int*) {
        assert(pending.empty() && count>0 && count<=8);
        submits++;
        for(unsigned i=0;i<count;i++) {
            if(lists[i]->kind==2) assert(ready[lists[i]->index]);
            pending.push_back(lists[i]);
        }
    }
    void executeCommandLists(const RenderCommandList* list,int* fence) {
        executeCommandLists(&list,1,nullptr,0,nullptr,0,fence);
    }
    void wait() {
        assert(!pending.empty());
        for(auto list:pending) {
            if(list->kind==0) { assert(!prefix); prefix=true; prefixes++; }
            if(list->kind==1) { assert(prefix && !ready[list->index]); ready[list->index]=true; stages++; }
            if(list->kind==2) { assert(prefix && ready[list->index] && !done[list->index]); done[list->index]=true; images++; }
        }
        pending.clear();
    }
};
struct Worker {
    Queue* commandQueue;
    std::unique_ptr<int> commandFence=std::make_unique<int>(0);
    void wait() { commandQueue->wait(); }
};
void run(bool batch,bool prefix,int n) {
    setenv("SK2_SWITCH_BATCH_UPLOADS",batch?"1":"0",1);
    setenv("SK2_SWITCH_BATCH_UPLOAD_PREFIX",prefix?"1":"0",1);
    Queue queue(n); Worker worker{&queue}; auto directWorker=&worker;
    RenderCommandList before{0,0}; const RenderCommandList* directCommandList=&before;
    std::vector<unsigned> switchDecodedCommandIndices;
    std::vector<std::unique_ptr<RenderCommandList>> switchDecodedStageCommandLists, switchDecodedCommandLists;
    std::vector<TextureUpload> queueCopy(n);
    char switchUploadContext[512]{};
    for(int i=0;i<n;i++) {
        switchDecodedCommandIndices.push_back(i);
        switchDecodedStageCommandLists.push_back(std::make_unique<RenderCommandList>(RenderCommandList{1,i}));
        switchDecodedCommandLists.push_back(std::make_unique<RenderCommandList>(RenderCommandList{2,i}));
    }
'''+schedule+r'''
    assert(queue.prefixes==1 && queue.stages==n && queue.images==n && queue.pending.empty());
    for(int i=0;i<n;i++) assert(queue.ready[i] && queue.done[i]);
    int expected=1+2*n;
    if(batch) expected=(prefix && n>0)?2*(1+(std::max(n-7,0)+7)/8):1+2*((n+7)/8);
    assert(queue.submits==expected);
}
int main() {
    for(bool batch:{false,true}) for(bool prefix:{false,true})
    for(int n=0;n<=33;n++) run(batch,prefix,n);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-upload-prefix-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O2',
                    '-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production upload prefix, 0–33 textures, eight-list bound, staging/image fences, legacy fallbacks')
