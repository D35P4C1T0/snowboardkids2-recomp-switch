#!/usr/bin/env python3
"""Exercise the production color/depth submission schedule with a fenced worker."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root / 'build-switch-deps/rt64/src/hle/rt64_state.cpp').read_text()
start = source.index('                const bool combinedColorDepthCopyback =')
prepare = source[start:source.index('\n#endif', start)]
start = source.index('                submitSwitchFramebuffer(combinedColorDepthCopyback ?')
end = source.index('                    framebufferPairCursor = maxFramebufferPair;', start) + len('                    framebufferPairCursor = maxFramebufferPair;')
schedule = '#if defined(__SWITCH__)\n' + source[start:end] + '\n                }\n'
test = r'''
#include <algorithm>
#include <cassert>
#include <string>
#include <vector>
struct List {
    bool recording=true;
    void begin() { assert(!recording); recording=true; }
    void end() { assert(recording); recording=false; }
};
struct Worker { List* commandList; };
struct Extensions { Worker* framebufferGraphicsWorker; };
struct FB {
    unsigned addressStart=0, height=8;
    bool ready=false;
    int commits=0;
    void copyNativeToRAMCPU(unsigned char*, unsigned, unsigned, unsigned) {
        assert(ready); commits++; ready=false;
    }
    void copyNativeToRAM(unsigned char* p,unsigned w,unsigned s,unsigned e) {
        copyNativeToRAMCPU(p,w,s,e);
    }
};
void run(bool enabled, bool pending, bool colorCPU, bool depthCPU) {
    List list;
    Worker worker{&list}; Extensions ext{&worker};
    FB color, depth; FB* colorFb=&color; FB* depthFb=&depth;
    unsigned char RDRAM[64]{};
    unsigned framebufferPairCursor=0, maxFramebufferPair=1, pairCursor=0;
    unsigned colorWriteWidth=8, colorRowStart=0, colorRowEnd=8;
    unsigned depthWriteWidth=pending?8:0, depthRowStart=0, depthRowEnd=8;
    bool switchCopybackOnly=true, switchDrawAndColorCopyback=false;
    bool switchDepthCopybackPending=pending, lastPairChunk=true;
    bool switchColorCPUReadback=colorCPU, switchDepthCPUReadback=depthCPU;
    unsigned switchStartOperations=0, switchEndOperations=3;
    bool batchColorDepthCopyback=enabled, depthRecorded=false;
    int depthRecords=0;
    std::vector<std::string> submissions;
    auto getFramebufferPairs=[](unsigned index) { assert(index==0); return true; };
    auto recordSwitchDepthCopyback=[&] {
        assert(list.recording && !depthRecorded);
        depthRecorded=true; depthRecords++;
    };
    auto submitSwitchFramebuffer=[&](const char* phase,unsigned startOps,unsigned endOps) {
        assert(!list.recording && startOps==0);
        submissions.emplace_back(phase);
        if(submissions.size()==1) {
            assert(!color.commits && !depth.commits);
            color.ready=true;
            assert(endOps==((pending && !enabled)?0:3));
        } else {
            assert(color.commits==1 && !depth.commits);
            assert(endOps==3);
        }
        if(depthRecorded) { depth.ready=true; depthRecorded=false; }
    };
'''
test += prepare + '\n    list.end();\n' + schedule + r'''
    assert(framebufferPairCursor==1);
    assert(color.commits==1 && depth.commits==(pending?1:0));
    assert(depthRecords==(pending?1:0));
    assert(submissions.size()==((pending && !enabled)?2:1));
    assert(submissions[0]==((pending && enabled)?"color+depth copyback":"color copyback"));
    if(submissions.size()==2) assert(submissions[1]=="depth copyback");
}
int main() {
    for(bool enabled:{false,true}) for(bool pending:{false,true})
    for(bool colorCPU:{false,true}) for(bool depthCPU:{false,true})
        run(enabled,pending,colorCPU,depthCPU);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-copyback-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D__SWITCH__',
                    '-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production copyback schedule, single depth recording, fenced CPU reads, isolated fallback, CPU/native encoders')
