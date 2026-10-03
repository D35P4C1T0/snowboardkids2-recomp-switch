#!/usr/bin/env python3
"""Check actual buffer and channel release paths against pending GPU work."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
subprocess.run(['git', '-C', str(root / 'build-switch-nvk/source'), 'apply',
                '--reverse', '--check', str(root / 'switch/nvk/switch-nvk-build.patch')], check=True)
source = (root / 'build-switch-nvk/source/winsys/drm_shim.c').read_text()
def function(name):
    start = source.rfind('\n', 0, source.index(name + '(')) + 1
    return source[start:source.index('\n}', start) + 2]
# drain_all has an earlier forward declaration; use its definition.
start = source.index('static int shim_async_drain_all(void)\n{')
drain = source[start:source.index('\n}', start) + 2]
stub = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define SHIM_MAX_CHANNELS 2
typedef struct { unsigned id, value; } NvFence;
#include "switch_async.h"
struct shim_bo { bool used, gpu_mapped; uint64_t gpu_va; int map; void *cpu; };
struct shim_channel { bool used; int chan, cmdbuf_bo, zcull_bo; struct shim_async_queue pending; };
struct drm_nouveau_gem_cpu_prep { uint32_t handle; };
struct drm_nouveau_channel_free { int channel; };
static struct { int lock; struct { int fd; } addr_space; struct shim_bo bos[2]; struct shim_channel channels[2]; } g_dev;
static bool fault;
static unsigned completed, waits, unmaps, closes, frees;
static int shim_async_fence_result(uint32_t channel, const NvFence *fence, int timeout) {
    assert(channel == 1 && g_dev.lock);
    if (fault) return -EIO;
    if (timeout) { completed = fence->value; waits++; }
    return completed >= fence->value ? 0 : -ETIME;
}
static bool drm_shim_owns_fd(int fd) { return fd == 1; }
static void mutexLock(int *lock) { assert(!*lock); *lock=1; }
static void mutexUnlock(int *lock) { assert(*lock); *lock=0; }
static struct shim_bo *bo_lookup(uint32_t h) { return h==1 && g_dev.bos[0].used ? &g_dev.bos[0] : NULL; }
static struct shim_channel *channel_lookup(uint32_t h) { return h==1 && g_dev.channels[0].used ? &g_dev.channels[0] : NULL; }
static void safe_to_release(void) { assert(g_dev.lock && !g_dev.channels[0].pending.count && !fault); }
static void nvioctlNvhostAsGpu_UnmapBuffer(int fd, uint64_t va) { (void)fd; (void)va; safe_to_release(); unmaps++; }
static void nvAddressSpaceUnmap(void *space, uint64_t va) { (void)space; (void)va; safe_to_release(); unmaps++; }
static void nvMapClose(int *map) { (void)map; safe_to_release(); closes++; }
static void release_memory(void *ptr) { (void)ptr; safe_to_release(); frees++; }
#define free release_memory
static void nvGpuChannelClose(int *channel) { (void)channel; safe_to_release(); closes++; }
'''
tests = r'''
static void reset(void) {
    memset(&g_dev,0,sizeof(g_dev));
    g_dev.bos[0]=(struct shim_bo){.used=true,.gpu_va=4096,.cpu=(void *)4096};
    g_dev.channels[0]=(struct shim_channel){.used=true,.cmdbuf_bo=0,.zcull_bo=-1,
        .pending={.fences={{0,1},{0,2}},.count=2}};
    fault=false; completed=waits=unmaps=closes=frees=0;
}
int main(void) {
    setenv("NVK_SWITCH_ASYNC","1",1);
    reset();
    assert(drmCloseBufferHandle(1,1)==0 && waits==2 && !g_dev.bos[0].used);
    assert(unmaps==1 && closes==1 && frees==1 && !g_dev.lock);
    reset(); fault=true;
    assert(drmCloseBufferHandle(1,1)==-EIO && g_dev.bos[0].used && !g_dev.lock);
    assert(!unmaps && !closes && !frees);
    reset(); struct drm_nouveau_gem_cpu_prep prep={1}; g_dev.lock=1;
    assert(nouveau_gem_cpu_prep(&prep)==0 && waits==2 && completed==2);
    reset(); fault=true; g_dev.lock=1;
    assert(nouveau_gem_cpu_prep(&prep)==-EIO && !waits);
    reset(); struct drm_nouveau_channel_free channel={1}; g_dev.lock=1;
    assert(nouveau_channel_free(&channel)==0 && waits==2 && !g_dev.channels[0].used);
    assert(unmaps==1 && closes==2 && frees==1);
    reset(); fault=true; g_dev.lock=1;
    assert(nouveau_channel_free(&channel)==-EIO && g_dev.channels[0].used && g_dev.bos[0].used);
    assert(!unmaps && !closes && !frees);
}
'''
functions = '\n'.join(function(name) for name in ['nouveau_gem_cpu_prep', 'drmCloseBufferHandle', 'nouveau_channel_free'])
with tempfile.TemporaryDirectory(prefix='sk2-retirement-') as temp:
    src=Path(temp)/'test.c'; exe=Path(temp)/'test'
    src.write_text(stub+'\n'+drain+'\n'+functions+'\n'+tests)
    subprocess.run([os.environ.get('CC','cc'), '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                    '-Wall','-Wextra','-Werror','-I',str(root/'build-switch-nvk/source/winsys'),
                    str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: pending work drains before buffer/channel release and CPU access; faults retain resources')
