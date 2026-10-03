#!/usr/bin/env python3
"""Exercise the actual bounded pending queue and timeline history."""
from pathlib import Path
import os
import subprocess
import tempfile

root=Path(__file__).resolve().parent.parent
subprocess.run(['git','-C',str(root/'build-switch-nvk/source'),'apply','--reverse','--check',
                str(root/'switch/nvk/switch-nvk-build.patch')],check=True)
test=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef struct { unsigned id,value; } NvFence;
#include "switch_async.h"
static unsigned gpu[4], blocked;
static bool fault;
static int shim_async_fence_result(uint32_t channel,const NvFence* fence,int timeout) {
    assert(channel>0 && channel<=4);
    if (fault) return -EIO;
    if (timeout) {gpu[fence->id]=fence->value;blocked++;}
    return gpu[fence->id]>=fence->value ? 0 : -ETIME;
}
int main(void) {
    struct shim_async_history h={0};
    bool ready=true;
    assert(shim_async_ready(&h,0,false,false,&ready)==0 && !ready);
    for(unsigned i=1;i<=8;i++) {
        NvFence f={0,i};
        assert(shim_async_attach(&h,i,&f,1)==0 && h.count==i);
    }
    NvFence ninth={0,9};
    assert(shim_async_attach(&h,9,&ninth,1)==0 && blocked==1 && h.count==8 && h.completed==1);
    gpu[0]=4;
    assert(shim_async_ready(&h,3,true,false,&ready)==0 && ready && h.completed==4);
    assert(shim_async_ready(&h,9,true,false,&ready)==0 && !ready);
    assert(shim_async_ready(&h,9,true,true,&ready)==0 && ready);
    assert(shim_async_ready(&h,10,true,true,&ready)==0 && !ready);
    fault=true;gpu[0]=99;
    assert(shim_async_progress(&h)==-EIO && h.completed==4);
    struct shim_async_queue q={.fences={{0,5},{0,6}},.count=2};
    assert(shim_async_reap(&q,1,2)==-EIO && q.failed && q.count==2);
    fault=false;
    assert(shim_async_reap(&q,1,0)==-EIO); /* failure is sticky */
    q=(struct shim_async_queue){.fences={{0,10},{0,11}},.count=2};gpu[0]=9;
    assert(shim_async_reap(&q,1,0)==0 && q.count==2);
    assert(shim_async_reap(&q,1,1)==0 && q.count==1 && gpu[0]==10);
    assert(shim_async_reap(&q,1,2)==0 && q.count==0 && gpu[0]==11);
    memset(&h,0,sizeof(h));
    shim_async_signal(&h,12);
    assert(shim_async_ready(&h,12,true,false,&ready)==0 && ready);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-async-') as temp:
    src=Path(temp)/'test.c';exe=Path(temp)/'test'
    src.write_text(test)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror',
                    '-I',str(root/'build-switch-nvk/source/winsys'),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: bounded timeline history, oldest-point backpressure, pending/available, failed work, drain, reset')
