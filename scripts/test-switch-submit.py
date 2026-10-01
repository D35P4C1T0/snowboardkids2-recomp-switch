#!/usr/bin/env python3
"""Exercise the real NVK submit path with completed fences and native faults."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
# Ensure tests exercise the durable patch, not an unrelated ignored-tree edit.
subprocess.run(['git', '-C', str(ROOT / 'build-switch-nvk/source'), 'apply',
                '--reverse', '--check', str(ROOT / 'switch/nvk/switch-nvk-build.patch')], check=True)
source = (ROOT / 'build-switch-nvk/source/winsys/drm_shim.c').read_text()

def function(name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    return source[start:source.index('\n}', start) + 2]

stub = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef u32 Result;
#define R_SUCCEEDED(r) ((r) == 0)
#define R_FAILED(r) ((r) != 0)
#define ARRAY_SIZE_LOCAL(a) (sizeof(a)/sizeof((a)[0]))
#define SHIM_LOG(...) ((void)0)
#define SHIM_MAX_BOS 1
#define GPFIFO_ENTRY_NOT_MAIN 1
#define GPFIFO_ENTRY_NO_PREFETCH 2
typedef struct { unsigned id, value; } NvFence;
typedef struct { uint64_t timestamp; u32 info32; uint16_t info16, status; } NvNotification;
typedef struct { u32 type, info[31]; } NvError;
struct shim_channel {
    int chan; bool engines_bound; uint64_t cmdbuf_va;
    unsigned fence_num_cmds, flush_num_cmds, setobj_num_cmds;
};
struct shim_bo { bool used; uint64_t gpu_va, size, gpu_bo_offset; void *cpu; };
struct shim_syncobj { bool signaled, has_fence; NvFence fence; uint64_t value; };
struct drm_nouveau_sync { u32 handle; uint64_t timeline_value; };
struct drm_nouveau_exec_push { uint64_t va; u32 va_len, flags; };
struct drm_nouveau_exec { u32 channel, push_count, wait_count, sig_count; uint64_t push_ptr, wait_ptr, sig_ptr; };
static struct { uint64_t va_base, va_size; struct shim_bo bos[1]; } g_dev;
static struct shim_channel channel;
static struct shim_syncobj syncobj;
static Result kickoff_result, fence_result, notification_result;
static unsigned fault_type, error_type, logged, detail_reads;
static bool decoded_method;
static struct { uint64_t va; u32 len, flags; } entries[8];
static unsigned entry_count;
static struct shim_channel *channel_lookup(unsigned id) { return id == 1 ? &channel : NULL; }
static struct shim_syncobj *syncobj_lookup(unsigned id) { return id == 1 ? &syncobj : NULL; }
static void log_sink(const char *message) {
    assert(message && strlen(message) < 256); logged++;
    if (strstr(message, "NVK method fault:")) {
        assert(strstr(message, "class=0xb197 method=0x1614"));
        decoded_method=true;
    }
}
static void (*g_drm_shim_log_sink)(const char *) = log_sink;
static Result nvGpuChannelGetErrorNotification(int *ch, NvNotification *n) {
    (void)ch; n->info32=fault_type; return notification_result;
}
static Result nvGpuChannelGetErrorInfo(int *ch, NvError *e) {
    (void)ch; e->type=error_type ? error_type : fault_type;
    e->info[0]=0x00200000; e->info[1]=0x80101614; e->info[4]=0xb197;
    detail_reads++; return 0;
}
static int nvFenceGetFd(void) { return 0; }
static Result nvioctlNvhostCtrl_SyncptRead(int fd, unsigned id, u32 *cur) { (void)fd; (void)id; *cur=100; return 0; }
static Result nvFenceWait(const NvFence *f, int timeout) { (void)f; (void)timeout; return fence_result; }
static void nvGpuChannelGetFence(int *ch, NvFence *f) { (void)ch; *f=(NvFence){1,100}; }
static void nvGpuChannelAppendEntry(int *ch, uint64_t va, u32 len, u32 flags, u32 extra) {
    (void)ch; (void)extra;
    assert(entry_count < 8);
    entries[entry_count].va=va; entries[entry_count].len=len; entries[entry_count].flags=flags;
    entry_count++;
}
static void nvGpuChannelIncrFence(int *ch) { (void)ch; }
static Result kickoff_retry(int *ch) { (void)ch; return kickoff_result; }
'''
tests = r'''
static void reset(void) {
    memset(&syncobj,0,sizeof(syncobj)); memset(&channel,0,sizeof(channel));
    kickoff_result=fence_result=fault_type=error_type=logged=detail_reads=0;
    decoded_method=false;
    entry_count=0; channel.cmdbuf_va=0x7000;
    channel.fence_num_cmds=3; channel.flush_num_cmds=10; channel.setobj_num_cmds=10;
    notification_result=0xea01; /* libnx: no pending notification */
    g_drm_shim_log_sink=log_sink;
}
int main(void) {
    struct drm_nouveau_exec_push push={0x1000,4,0};
    struct drm_nouveau_sync signal={1,7};
    struct drm_nouveau_exec req={.channel=1,.push_count=1,.sig_count=1,
        .push_ptr=(uintptr_t)&push,.sig_ptr=(uintptr_t)&signal};
    reset();
    assert(nouveau_exec(&req)==0 && syncobj.has_fence && syncobj.value==7);
    /* Cache invalidation precedes GPU work; a separate no-prefetch flush
     * follows it before the completion fence. Protect the hardware fix. */
    assert(entry_count==5);
    assert(entries[1].va==0x700c && entries[1].len==10);
    assert(entries[2].va==push.va && entries[2].len==1);
    assert(entries[3].va==0x700c && entries[3].len==10);
    assert(entries[4].va==0x7000 && entries[4].len==3);
    for (unsigned i=0;i<entry_count;i++) assert(entries[i].flags==3);
    uint32_t cache_commands[16]={0};
    unsigned count=gen_flush_cmdlist(cache_commands);
    assert(count==10);
    assert(cache_commands[count-2]==0x80000014); /* SET_REFERENCE */
    assert(cache_commands[count-1]==0); /* command-processing boundary */
    reset(); notification_result=0; fault_type=32;
    /* The exact regression: a completed fence after PBDMA reset is NOT success. */
    assert(nouveau_exec(&req)==-EIO && !syncobj.has_fence && !syncobj.signaled && syncobj.value==0);
    assert(detail_reads==1 && logged>=10);
    reset(); notification_result=0; fault_type=31; error_type=2;
    assert(nouveau_exec(&req)==-EIO && decoded_method && !syncobj.signaled);
    reset(); notification_result=0; fault_type=31; g_drm_shim_log_sink=NULL;
    assert(nouveau_exec(&req)==-EIO && !syncobj.signaled); /* detection without logging */
    reset(); fence_result=1;
    assert(nouveau_exec(&req)==-EIO && !syncobj.has_fence);
    reset(); kickoff_result=1;
    assert(nouveau_exec(&req)==-EIO && !syncobj.has_fence);
    reset(); req.wait_count=1; req.wait_ptr=(uintptr_t)&signal;
    syncobj.has_fence=true; syncobj.value=3; fence_result=1;
    assert(nouveau_exec(&req)==-EIO && syncobj.value==3);
    puts("PASS: cache boundaries, native GPU faults, failed work never signals/recycles, timeout/kickoff/dependency failures");
}
'''
functions = '\n'.join(function(name) for name in [
    'gen_flush_cmdlist', 'shim_channel_check_error', 'report_submit_status', 'nouveau_exec'])
with tempfile.TemporaryDirectory(prefix='sk2-submit-test-') as temp:
    src=Path(temp)/'test.c'; binary=Path(temp)/'test'
    src.write_text(stub+'\n'+functions+'\n'+tests)
    subprocess.run([os.environ.get('CC','cc'), '-std=c11', '-Wall', '-Wextra',
                    '-Wno-unused-variable', '-Werror', str(src), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
