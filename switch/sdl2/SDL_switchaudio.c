/*
  Simple DirectMedia Layer
  Copyright (C) 1997-2018 Sam Lantinga <slouken@libsdl.org>

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.
*/
/* Altered for SK2: maintain two queued native buffers; preserve a legacy mode.
 * See README.md for pinned provenance and private ABI requirements. */
#include <SDL2/SDL.h>
#include <malloc.h>
#include <stddef.h>
#if SDL_MAJOR_VERSION != 2 || SDL_MINOR_VERSION != 28 || SDL_PATCHLEVEL != 5
#error "Revalidate the Switch private audio ABI for this SDL version"
#endif

#if SDL_AUDIO_DRIVER_SWITCH

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <malloc.h>

#include <SDL2/SDL_audio.h>



#include "SDL_switchaudio.h"
_Static_assert(offsetof(SDL_AudioDevice, hidden) == 144, "SDL audio device ABI changed");
extern void switch_perf_record(const char*, uint64_t, uint64_t) __attribute__((weak));
static void record_event(const char* name) { if (switch_perf_record) switch_perf_record(name,0,0); }
static bool update_device(SDL_AudioDevice* device) {
    Result result=audrvUpdate(&device->hidden->driver);
    if (R_FAILED(result)) {
        record_event("audio_backend_failure");
        SDL_OpenedAudioDeviceDisconnected(device);
        return false;
    }
    return true;
}

static const AudioRendererConfig arConfig =
    {
        .output_rate     = AudioRendererOutputRate_48kHz,
        .num_voices      = 24,
        .num_effects     = 0,
        .num_sinks       = 1,
        .num_mix_objs    = 1,
        .num_mix_buffers = 2,
    };

static int
SWITCHAUDIO_OpenDevice(_THIS, const char *devname)
{
    static const u8 sink_channels[] = {0, 1};
    Result res;
    u32 size;
    int mpid;

    this->hidden = (struct SDL_PrivateAudioData *) SDL_calloc(1, sizeof(*this->hidden));
    if (this->hidden == NULL) {
        return SDL_OutOfMemory();
    }

    res = audrenInitialize(&arConfig);
    if (R_FAILED(res)) {
        return SDL_SetError("audrenInitialize failed (0x%x)", res);
    }
    this->hidden->audr_device = true;

    res = audrvCreate(&this->hidden->driver, &arConfig, 2);
    if (R_FAILED(res)) {
        return SDL_SetError("audrvCreate failed (0x%x)", res);
    }
    this->hidden->audr_driver = true;

    const char* legacy = SDL_getenv("SK2_SWITCH_LEGACY_AUDIO");
    this->hidden->legacy = legacy && *legacy == '1';
    this->spec.format = AUDIO_S16SYS;
    // Two 21 ms buffers tolerate the renderer's 5 ms update quantum.
    if (!this->hidden->legacy) this->spec.samples = 1024;
    SDL_CalculateAudioSpec(&this->spec);

    size = (u32) ((this->spec.size * 2) + 0xfff) & ~0xfff;
    this->hidden->pool = memalign(0x1000, size);
    if (!this->hidden->pool) return SDL_OutOfMemory();
    this->hidden->buffer_tmp = malloc(this->spec.size);
    if (!this->hidden->buffer_tmp) return SDL_OutOfMemory();
    for (int i = 0; i < 2; i++) {
        this->hidden->buffer[i].data_raw = this->hidden->pool;
        this->hidden->buffer[i].size = this->spec.size * 2;
        this->hidden->buffer[i].start_sample_offset = i * this->spec.samples;
        this->hidden->buffer[i].end_sample_offset = this->hidden->buffer[i].start_sample_offset + this->spec.samples;
    }

    mpid = audrvMemPoolAdd(&this->hidden->driver, this->hidden->pool, size);
    if (mpid < 0) return SDL_SetError("Audio memory pool creation failed");
    audrvMemPoolAttach(&this->hidden->driver, mpid);

    audrvDeviceSinkAdd(&this->hidden->driver, AUDREN_DEFAULT_DEVICE_NAME, 2, sink_channels);

    res = audrenStartAudioRenderer();
    if (R_FAILED(res)) {
        return SDL_SetError("audrenStartAudioRenderer failed (0x%x)", res);
    }

    audrvVoiceInit(&this->hidden->driver, 0, this->spec.channels, PcmFormat_Int16, this->spec.freq);
    audrvVoiceSetDestinationMix(&this->hidden->driver, 0, AUDREN_FINAL_MIX_ID);
    if (this->spec.channels == 1) {
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 1.0f, 0, 0);
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 1.0f, 0, 1);
    }
    else {
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 1.0f, 0, 0);
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 0.0f, 0, 1);
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 0.0f, 1, 0);
        audrvVoiceSetMixFactor(&this->hidden->driver, 0, 1.0f, 1, 1);
    }

    audrvVoiceStart(&this->hidden->driver, 0);

    return 0;
}

static void
SWITCHAUDIO_PlayDevice(_THIS)
{
    int current = -1;
    if (!this->hidden->legacy && !update_device(this)) return;
    for (int i = 0; i < 2; i++) {
        if (this->hidden->buffer[i].state == AudioDriverWaveBufState_Free
            || this->hidden->buffer[i].state == AudioDriverWaveBufState_Done) {
            current = i;
            break;
        }
    }

    if (!this->hidden->legacy && current < 0) {
        // WaitDevice guarantees a reusable slot before the next SDL callback.
        record_event("audio_backend_failure");
        SDL_OpenedAudioDeviceDisconnected(this);
        return;
    }
    if (current >= 0) {
        Uint8 *ptr = (Uint8 *) (this->hidden->pool + (current * this->spec.size));
        memcpy(ptr, this->hidden->buffer_tmp, this->spec.size);
        armDCacheFlush(ptr, this->spec.size);
        if (!audrvVoiceAddWaveBuf(&this->hidden->driver, 0, &this->hidden->buffer[current])) {
            SDL_OpenedAudioDeviceDisconnected(this);
            return;
        }
        this->hidden->buffers_submitted++;
    }
    else if (!audrvVoiceIsPlaying(&this->hidden->driver, 0)) {
        audrvVoiceStart(&this->hidden->driver, 0);
    }

    if (!this->hidden->legacy) {
        // Queue immediately. Waiting for PLAYING here starves the other slot.
        if (!audrvVoiceIsPlaying(&this->hidden->driver, 0)) audrvVoiceStart(&this->hidden->driver, 0);
        update_device(this);
        record_event("audio_backend_feed");
        return;
    }
    audrvUpdate(&this->hidden->driver);

    if (current >= 0) {
        while (this->hidden->buffer[current].state != AudioDriverWaveBufState_Playing) {
            audrvUpdate(&this->hidden->driver);
            audrenWaitFrame();
        }
    }
    else {
        current = -1;
        for (int i = 0; i < 2; i++) {
            if (this->hidden->buffer[i].state == AudioDriverWaveBufState_Playing) {
                current = i;
                break;
            }
        }
        while (this->hidden->buffer[current].state == AudioDriverWaveBufState_Playing) {
            audrvUpdate(&this->hidden->driver);
            audrenWaitFrame();
        }
    }
}

static void
SWITCHAUDIO_WaitDevice(_THIS)
{
    if (this->hidden->legacy) return;
    while (!SDL_AtomicGet(&this->shutdown) && SDL_AtomicGet(&this->enabled)) {
        if (!update_device(this)) return;
        unsigned reusable = 0;
        for (int i = 0; i < 2; i++) {
            AudioDriverWaveBufState state=this->hidden->buffer[i].state;
            reusable += state == AudioDriverWaveBufState_Free || state == AudioDriverWaveBufState_Done;
        }
        if (reusable) {
            if (reusable == 2 && this->hidden->buffers_submitted >= 2) record_event("audio_backend_starved");
            return;
        }
        audrenWaitFrame();
    }
}

static Uint8
*SWITCHAUDIO_GetDeviceBuf(_THIS)
{
    return this->hidden->buffer_tmp;
}

static void
SWITCHAUDIO_CloseDevice(_THIS)
{
    if (this->hidden->audr_driver) {
        audrvClose(&this->hidden->driver);
    }

    if (this->hidden->audr_device) {
        audrenExit();
    }

    if (this->hidden->pool) free(this->hidden->pool);
    if (this->hidden->buffer_tmp) {
        free(this->hidden->buffer_tmp);
    }

    SDL_free(this->hidden);
}

static void
SWITCHAUDIO_ThreadInit(_THIS)
{

}

static SDL_bool
SWITCHAUDIO_Init(SDL_AudioDriverImpl *impl)
{
    impl->OpenDevice = SWITCHAUDIO_OpenDevice;
    impl->PlayDevice = SWITCHAUDIO_PlayDevice;
    impl->WaitDevice = SWITCHAUDIO_WaitDevice;
    impl->GetDeviceBuf = SWITCHAUDIO_GetDeviceBuf;
    impl->CloseDevice = SWITCHAUDIO_CloseDevice;
    impl->ThreadInit = SWITCHAUDIO_ThreadInit;

    impl->OnlyHasDefaultOutputDevice = 1;

    return 1;
}

AudioBootStrap SWITCHAUDIO_bootstrap = {
    "switch", "Nintendo Switch audio driver", SWITCHAUDIO_Init, 0
};

#endif /* SDL_AUDIO_DRIVER_SWITCH */
