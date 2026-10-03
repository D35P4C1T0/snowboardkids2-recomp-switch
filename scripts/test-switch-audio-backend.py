#!/usr/bin/env python3
"""Exercise the production SDL native buffer handoff with a fake renderer."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root / 'switch/sdl2/SDL_switchaudio.c').read_text()
def function(name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    if source[start:].startswith(name):
        start = source.rfind('\n', 0, start - 1) + 1
    return source[start:source.index('\n}', start) + 2]
stub = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t Uint8;
typedef unsigned Result;
#define R_FAILED(r) ((r)!=0)
enum { AudioDriverWaveBufState_Free, AudioDriverWaveBufState_Waiting,
       AudioDriverWaveBufState_Queued, AudioDriverWaveBufState_Playing, AudioDriverWaveBufState_Done };
typedef int AudioDriverWaveBufState;
typedef struct { int state; } AudioDriverWaveBuf;
typedef struct { bool playing; } AudioDriver;
struct Hidden { AudioDriver driver; AudioDriverWaveBuf buffer[2];
    void *pool, *buffer_tmp; bool legacy; uint64_t buffers_submitted; };
typedef struct { struct Hidden *hidden; struct { unsigned size; } spec; int enabled, shutdown; } SDL_AudioDevice;
#define _THIS SDL_AudioDevice *this
static unsigned waits, added, failures, feeds, errors;
static bool fail_update;
static struct Hidden hidden;
static void record_event(const char *name) {
    if (!strcmp(name,"audio_backend_feed")) feeds++;
    if (!strcmp(name,"audio_backend_failure")) failures++;
}
static void SDL_OpenedAudioDeviceDisconnected(SDL_AudioDevice *d) { d->enabled=0; errors++; }
static int SDL_AtomicGet(int *value) { return *value; }
static Result audrvUpdate(AudioDriver *d) { (void)d; return fail_update; }
static bool audrvVoiceIsPlaying(AudioDriver *d,int id) { (void)id; return d->playing; }
static void audrvVoiceStart(AudioDriver *d,int id) { (void)id; d->playing=true; }
static void armDCacheFlush(void *ptr,unsigned size) { (void)ptr; (void)size; }
static bool audrvVoiceAddWaveBuf(AudioDriver *d,int id,AudioDriverWaveBuf *buf) {
    (void)d;(void)id; assert(buf->state==AudioDriverWaveBufState_Free || buf->state==AudioDriverWaveBufState_Done);
    buf->state=AudioDriverWaveBufState_Queued; added++; return true;
}
static void audrenWaitFrame(void) {
    assert(++waits < 5);
    hidden.buffer[0].state=AudioDriverWaveBufState_Done;
    hidden.buffer[1].state=AudioDriverWaveBufState_Playing;
}
'''
test = r'''
int main(void) {
    uint8_t pool[16]={0}, data[8]={1,2,3,4,5,6,7,8};
    hidden.pool=pool; hidden.buffer_tmp=data;
    SDL_AudioDevice device={.hidden=&hidden,.spec={8},.enabled=1};
    SWITCHAUDIO_PlayDevice(&device);
    assert(added==1 && waits==0 && !memcmp(pool,data,8));
    SWITCHAUDIO_WaitDevice(&device);
    assert(waits==0); /* second free slot must be filled immediately */
    SWITCHAUDIO_PlayDevice(&device);
    assert(added==2 && waits==0 && !memcmp(pool+8,data,8));
    SWITCHAUDIO_WaitDevice(&device);
    assert(waits==1); /* now wait for completion, not start of playback */
    data[0]=42;
    SWITCHAUDIO_PlayDevice(&device);
    assert(added==3 && pool[0]==42 && feeds==3);
    device.shutdown=1;
    SWITCHAUDIO_WaitDevice(&device);
    assert(waits==1);
    device.shutdown=0;fail_update=true;
    SWITCHAUDIO_WaitDevice(&device);
    assert(!device.enabled && failures==1 && errors==1);
    puts("PASS: prefill both slots, no waiting/dropped chunk in Play, wait-before-reuse, shutdown, update failure");
}
'''
functions = '\n'.join(function(name) for name in ['update_device','SWITCHAUDIO_PlayDevice','SWITCHAUDIO_WaitDevice'])
with tempfile.TemporaryDirectory(prefix='sk2-audio-backend-') as temp:
    src = Path(temp)/'test.c'; exe=Path(temp)/'test'
    src.write_text(stub+'\n'+functions+'\n'+test)
    subprocess.run([os.environ.get('CC','cc'), '-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
