#!/usr/bin/env python3
"""Exercise the actual pinned Switch DRM wait functions with a fake GPU clock."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
# Ensure tests exercise the durable patch, not an unrelated ignored-tree edit.
subprocess.run(['git', '-C', str(root / 'build-switch-nvk/source'), 'apply',
                '--reverse', '--check', str(root / 'switch/nvk/switch-nvk-build.patch')], check=True)
source = (root / 'build-switch-nvk/source/winsys/drm_shim.c').read_text()

def function(name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    end = source.index('\n}', start) + 2
    return source[start:end]

stub = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#define DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL 1
#define DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT 2
#define DRM_SYNCOBJ_WAIT_FLAGS_WAIT_AVAILABLE 4
#define R_SUCCEEDED(r) ((r) == 0)
typedef struct { unsigned id, value; } NvFence;
struct shim_syncobj { bool used, signaled; uint64_t value; bool has_fence; NvFence fence; };
static struct { int lock; struct shim_syncobj syncobjs[4]; } g_dev;
static int64_t now;
static unsigned gpu_progress[4], sleeps;
static void (*on_sleep)(void);
static bool drm_shim_owns_fd(int fd) { return fd == 1; }
static void mutexLock(int *lock) { assert(*lock == 0); *lock = 1; }
static void mutexUnlock(int *lock) { assert(*lock == 1); *lock = 0; }
static struct shim_syncobj *syncobj_lookup(uint32_t handle) {
    return handle > 0 && handle <= 4 && g_dev.syncobjs[handle-1].used ? &g_dev.syncobjs[handle-1] : NULL;
}
static int nvFenceWait(const NvFence *fence, int timeout) {
    assert(!g_dev.lock && timeout == 0);
    return gpu_progress[fence->id] >= fence->value ? 0 : 1;
}
static int64_t shim_monotonic_ns(void) { return now; }
static void svcSleepThread(int64_t duration) {
    assert(!g_dev.lock && duration > 0 && duration <= 50000);
    now += duration; sleeps++;
    assert(sleeps < 100);
    if (on_sleep) on_sleep();
}
'''
tests = r'''
static void reset(void) {
    memset(&g_dev, 0, sizeof(g_dev)); memset(gpu_progress, 0, sizeof(gpu_progress));
    for (unsigned i=0; i<4; i++) g_dev.syncobjs[i].used = true;
    now=0; sleeps=0; on_sleep=NULL;
}
static void submit_later(void) {
    if (sleeps == 2) {
        g_dev.syncobjs[0].has_fence=true;
        g_dev.syncobjs[0].fence=(NvFence){0, 5};
        g_dev.syncobjs[0].value=3;
        gpu_progress[0]=5;
    }
}
int main(void) {
    const unsigned pending=DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT;
    uint32_t handles[]={1,2}, which=99;
    uint64_t point=3;
    reset();
    assert(drmSyncobjWait(1,handles,1,0,pending,NULL)==-ETIME);
    assert(drmSyncobjWait(1,handles,1,125000,pending,NULL)==-ETIME && now==125000);
    reset(); on_sleep=submit_later;
    assert(drmSyncobjWait(1,handles,1,200000,pending,NULL)==0 && sleeps==2);
    reset();
    g_dev.syncobjs[0].signaled=true; g_dev.syncobjs[0].value=2;
    assert(drmSyncobjTimelineWait(1,handles,&point,1,0,pending,NULL)==-ETIME);
    on_sleep=submit_later;
    assert(drmSyncobjTimelineWait(1,handles,&point,1,200000,pending,NULL)==0 && sleeps==2);
    reset();
    g_dev.syncobjs[0].has_fence=true; g_dev.syncobjs[0].fence=(NvFence){0,5};
    assert(drmSyncobjWait(1,handles,1,0,pending,NULL)==-ETIME);
    assert(drmSyncobjWait(1,handles,1,0,pending|DRM_SYNCOBJ_WAIT_FLAGS_WAIT_AVAILABLE,NULL)==0);
    assert(drmSyncobjSignal(1,handles,1)==0);
    assert(!g_dev.syncobjs[0].has_fence && drmSyncobjWait(1,handles,1,0,pending,NULL)==0);
    assert(drmSyncobjReset(1,handles,1)==0);
    assert(drmSyncobjWait(1,handles,1,0,pending,NULL)==-ETIME);
    reset(); g_dev.syncobjs[1].signaled=true;
    assert(drmSyncobjWait(1,handles,2,0,pending,&which)==0 && which==1 && sleeps==0);
    assert(drmSyncobjWait(1,handles,2,0,pending|DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL,NULL)==-ETIME);
    on_sleep=submit_later;
    assert(drmSyncobjWait(1,handles,2,200000,pending|DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL,NULL)==0);
    reset();
    assert(drmSyncobjWait(9,handles,1,0,pending,NULL)==-EBADF);
    handles[0]=99;
    assert(drmSyncobjWait(1,handles,1,0,pending,NULL)==-ENOENT);
    puts("PASS: pending fence, late submission, timeline value, GPU completion, wait-any/all, reset, deadline, invalid handles");
}
'''
functions = '\n'.join(function(name) for name in [
    'shim_syncobj_wait', 'drmSyncobjWait', 'drmSyncobjTimelineWait',
    'drmSyncobjSignal', 'drmSyncobjReset'])
with tempfile.TemporaryDirectory(prefix='sk2-sync-test-') as temp:
    src = Path(temp)/'test.c'; binary=Path(temp)/'test'
    src.write_text(stub+'\n'+functions+'\n'+tests)
    subprocess.run([os.environ.get('CC','cc'), '-std=c11', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
