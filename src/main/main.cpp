#include <cstdio>
#include <algorithm>
#include <cassert>
#include <cstring>
#include <vector>
#include <array>
#include <filesystem>
#include <stdexcept>
#include <exception>
#include <cinttypes>
#include <atomic>
#include <cerrno>
#include <mutex>
#include <thread>
#include <condition_variable>
#include <chrono>
#include "audio_queue.h"
#include "../../switch/perf_stats.h"

#if !defined(__SWITCH__)
#include "nfd.h"
#endif

#include "ultramodern/ultra64.h"
#include "ultramodern/ultramodern.hpp"
#define SDL_MAIN_HANDLED
#ifdef _WIN32
#include "SDL.h"
#elif !defined(__SWITCH__)
#include "SDL2/SDL.h"
#include "SDL2/SDL_syswm.h"
// Undefine x11 macros that get included by SDL_syswm.h.
#undef None
#undef Status
#undef LockMask
#undef ControlMask
#undef Success
#undef Always
#else
#include <SDL2/SDL.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <switch.h>
#include <unistd.h>
#endif

#include "zelda_config.h"
#include "zelda_sound.h"
#include "zelda_support.h"
#include "recomp_api.h"
#include "recomp_data.h"
#include "ovl_patches.hpp"
#include "recompinput/input_events.h"
#include "recompinput/players.h"
#include "recompinput/profiles.h"
#include "recompui/program_config.h"
#include "recompui/renderer.h"
#include "recompui/recompui.h"
#include "util/file.h"
#include "librecomp/game.hpp"
#include "librecomp/mods.hpp"
#include "librecomp/helpers.hpp"

#include "mods/snowboardkids2_mod_template.h"
#include "mods/snowboardkids2_randomizer.h"
#include "mods/snowboardkids2_time_trial.h"
#include "sk2_game_version.h"
#include "sk2_launcher.h"
#include "sk2_theme.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <timeapi.h>
#include "SDL_syswm.h"
#endif

#include "../../lib/rt64/src/contrib/stb/stb_image.h"
#if defined(__SWITCH__)
#include "../../lib/RecompFrontend/recompui/lib/lunasvg/plutovg/include/plutovg.h"
#endif

const std::string version_string = sk2_game_version;
constexpr int sk2_max_players = 4;

#if defined(__SWITCH__)
void switch_log_checkpoint(const char* message, bool reset);
static bool switch_profile_enabled = true;
static std::atomic<float> switch_display_fps{0.0f};

extern "C" float switch_fps_value() {
    return switch_display_fps.load(std::memory_order_relaxed);
}

extern "C" void switch_fps_presented() {
    // Count completed presentations, including interpolation, independently
    // of detailed profiling. UI rendering reads the previous half-second window.
    using Clock = std::chrono::steady_clock;
    static auto window_start = Clock::time_point{};
    static uint32_t frames = 0;
    const auto now = Clock::now();
    if (window_start == Clock::time_point{}) {
        window_start = now;
        return;
    }
    frames++;
    const auto elapsed = now - window_start;
    if (elapsed >= std::chrono::milliseconds(500)) {
        switch_display_fps.store(float(frames / std::chrono::duration<double>(elapsed).count()),
            std::memory_order_relaxed);
        frames = 0;
        window_start = now;
    }
}

extern "C" void switch_perf_record(const char* stage, uint64_t elapsed_ns, uint64_t id) {
    if (!switch_profile_enabled) return;
    struct Entry { const char* name = nullptr; sk2::perf::Histogram stats; uint64_t id = 0; };
    static std::array<Entry, 32> entries;
    static std::mutex mutex;
    static auto last_report = std::chrono::steady_clock::now();
    std::lock_guard lock(mutex);
    for (auto& entry : entries) {
        if (!entry.name) entry.name = stage;
        if (std::strcmp(entry.name, stage) == 0) {
            entry.stats.add(elapsed_ns); entry.id = id; break;
        }
    }
    const auto now = std::chrono::steady_clock::now();
    if (now - last_report < std::chrono::seconds(2)) return;
    for (auto& entry : entries) {
        const auto& h = entry.stats;
        if (!h.count) continue;
        char message[320];
        std::snprintf(message, sizeof(message),
            "profile: stage=%s count=%llu mean_us=%llu p50_us=%llu p95_us=%llu p99_us=%llu max_us=%llu late=%llu id=%llu",
            entry.name, (unsigned long long)h.count, (unsigned long long)(h.total_ns / h.count / 1000),
            (unsigned long long)(h.percentile_ns(50) / 1000), (unsigned long long)(h.percentile_ns(95) / 1000),
            (unsigned long long)(h.percentile_ns(99) / 1000), (unsigned long long)(h.max_ns / 1000),
            (unsigned long long)h.late, (unsigned long long)entry.id);
        switch_log_checkpoint(message, false);
        entry.stats = {};
    }
    last_report = now;
}

namespace {
std::mutex switch_log_mutex;
u64 switch_log_start_tick = 0;
int switch_nxlink_socket = -1;
bool switch_socket_initialized = false;
constexpr uint16_t switch_screenshot_port = 47474;
std::atomic<bool> switch_screenshot_running{false};
std::thread switch_screenshot_thread;
std::atomic<bool> switch_screenshot_requested{false};
std::mutex switch_screenshot_mutex;
std::condition_variable switch_screenshot_condition;
std::vector<uint8_t> switch_screenshot_pixels;
uint32_t switch_screenshot_width = 0;
uint32_t switch_screenshot_height = 0;
bool switch_screenshot_ready = false;
std::atomic<bool> switch_manual_screenshot_pending{false};
uint64_t switch_manual_screenshot_sequence = 0;
uint64_t switch_manual_screenshot_served = 0;

bool switch_send_all(int socket_fd, const void *data, size_t size) {
    const uint8_t *bytes = static_cast<const uint8_t *>(data);
    size_t sent_total = 0;
    while (sent_total < size) {
        const ssize_t sent = send(socket_fd, bytes + sent_total, size - sent_total, MSG_NOSIGNAL);
        if (sent > 0) {
            sent_total += size_t(sent);
        }
        else if ((sent < 0) && (errno == EINTR)) {
            continue;
        }
        else {
            return false;
        }
    }

    return true;
}

bool switch_encode_screenshot_jpeg(const std::vector<uint8_t> &pixels,
    uint32_t width, uint32_t height, std::vector<uint8_t> &jpeg_buffer)
{
    if (pixels.empty() || (width == 0) || (height == 0)) {
        return false;
    }

    plutovg_surface_t *surface = plutovg_surface_create_for_data(
        const_cast<uint8_t *>(pixels.data()), int(width), int(height), int(width * 4));
    if (surface == nullptr) {
        return false;
    }

    auto write_jpeg = [](void *closure, void *data, int size) {
        auto *bytes = static_cast<std::vector<uint8_t> *>(closure);
        const uint8_t *source = static_cast<const uint8_t *>(data);
        bytes->insert(bytes->end(), source, source + size);
    };
    const bool encoded = plutovg_surface_write_to_jpg_stream(surface, write_jpeg,
        &jpeg_buffer, 90);
    plutovg_surface_destroy(surface);
    return encoded && !jpeg_buffer.empty();
}

void switch_screenshot_server() {
    const int listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0) {
        switch_log_checkpoint("screenshot: socket creation failed", false);
        return;
    }

    int reuse_address = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse_address, sizeof(reuse_address));
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons(switch_screenshot_port);
    if ((bind(listener, reinterpret_cast<const sockaddr *>(&address), sizeof(address)) < 0) ||
        (listen(listener, 1) < 0))
    {
        close(listener);
        switch_log_checkpoint("screenshot: HTTP listener setup failed", false);
        return;
    }

    switch_log_checkpoint("screenshot: HTTP capture ready on port 47474", false);
    while (switch_screenshot_running.load(std::memory_order_relaxed)) {
        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(listener, &read_fds);
        timeval timeout{ 0, 250'000 };
        const int selected = select(listener + 1, &read_fds, nullptr, nullptr, &timeout);
        if ((selected <= 0) || !FD_ISSET(listener, &read_fds)) {
            continue;
        }

        const int client = accept(listener, nullptr, nullptr);
        if (client < 0) {
            continue;
        }

        timeval io_timeout{ 2, 0 };
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &io_timeout, sizeof(io_timeout));
        setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &io_timeout, sizeof(io_timeout));
        char request[1024]{};
        const ssize_t request_size = recv(client, request, sizeof(request) - 1, 0);
        const bool screenshot_request = (request_size > 0) &&
            (std::strncmp(request, "GET /screenshot.jpg ", 20) == 0);
        const bool manual_screenshot_request = (request_size > 0) &&
            (std::strncmp(request, "GET /manual.jpg ", 16) == 0);
        if (!screenshot_request && !manual_screenshot_request) {
            static constexpr char response[] =
                "HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n";
            switch_send_all(client, response, sizeof(response) - 1);
            close(client);
            continue;
        }

        std::vector<uint8_t> pixels;
        uint32_t width = 0;
        uint32_t height = 0;
        uint64_t manual_sequence = 0;
        if (screenshot_request) {
            std::unique_lock screenshot_lock(switch_screenshot_mutex);
            switch_screenshot_ready = false;
            switch_screenshot_requested.store(true, std::memory_order_release);
            const bool captured = switch_screenshot_condition.wait_for(screenshot_lock,
                std::chrono::seconds(2), []() { return switch_screenshot_ready; });
            switch_screenshot_requested.store(false, std::memory_order_release);
            if (captured) {
                pixels = switch_screenshot_pixels;
                width = switch_screenshot_width;
                height = switch_screenshot_height;
            }
        }
        else {
            const std::lock_guard screenshot_lock(switch_screenshot_mutex);
            if (switch_screenshot_ready &&
                (switch_manual_screenshot_sequence > switch_manual_screenshot_served))
            {
                pixels = switch_screenshot_pixels;
                width = switch_screenshot_width;
                height = switch_screenshot_height;
                manual_sequence = switch_manual_screenshot_sequence;
            }
            else {
                static constexpr char response[] =
                    "HTTP/1.1 204 No Content\r\nConnection: close\r\nContent-Length: 0\r\n\r\n";
                switch_send_all(client, response, sizeof(response) - 1);
                close(client);
                continue;
            }
        }

        std::vector<uint8_t> jpeg_buffer;
        const bool encoded = switch_encode_screenshot_jpeg(pixels, width, height,
            jpeg_buffer);

        if (encoded && !jpeg_buffer.empty()) {
            char header[256]{};
            const int header_size = std::snprintf(header, sizeof(header),
                "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: %zu\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
                jpeg_buffer.size());
            const bool sent = switch_send_all(client, header, size_t(header_size)) &&
                switch_send_all(client, jpeg_buffer.data(), jpeg_buffer.size());
            if (sent && manual_screenshot_request) {
                const std::lock_guard screenshot_lock(switch_screenshot_mutex);
                switch_manual_screenshot_served = std::max(
                    switch_manual_screenshot_served, manual_sequence);
            }
            char message[128]{};
            if (manual_screenshot_request) {
                std::snprintf(message, sizeof(message),
                    "screenshot: R3 JPEG #%" PRIu64 " served %ux%u bytes=%zu",
                    manual_sequence, width, height, jpeg_buffer.size());
            }
            else {
                std::snprintf(message, sizeof(message),
                    "screenshot: served JPEG %ux%u bytes=%zu",
                    width, height, jpeg_buffer.size());
            }
            switch_log_checkpoint(message, false);
        }
        else {
            static constexpr char body[] = "renderer capture timed out\n";
            char header[192]{};
            const int header_size = std::snprintf(header, sizeof(header),
                "HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
                int(sizeof(body) - 1));
            switch_send_all(client, header, size_t(header_size));
            switch_send_all(client, body, sizeof(body) - 1);
        }

        close(client);
    }

    close(listener);
}

void switch_initialize_logging() {
    const std::lock_guard<std::mutex> lock(switch_log_mutex);
    switch_log_start_tick = armGetSystemTick();

    // hbloader provides this address only when nxlink uploaded the NRO. Normal
    // SD-card launches avoid all socket setup and its timeout path.
    if (__nxlink_host.s_addr != 0 && R_SUCCEEDED(socketInitializeDefault())) {
        switch_socket_initialized = true;
        // Keep stdout/stderr untouched. nxlink's stdio redirection performs
        // blocking writes; when its receiver disappears or backpressures, a
        // render-thread checkpoint can freeze the whole process. Checkpoints
        // use explicit nonblocking sends below and may be dropped safely.
        switch_nxlink_socket = nxlinkConnectToHost(false, false);
        if (switch_nxlink_socket < 0) {
            socketExit();
            switch_socket_initialized = false;
        }
        else {
            const int socket_flags = fcntl(switch_nxlink_socket, F_GETFL, 0);
            if (socket_flags >= 0) {
                fcntl(switch_nxlink_socket, F_SETFL, socket_flags | O_NONBLOCK);
            }

            switch_screenshot_running.store(true, std::memory_order_relaxed);
            switch_screenshot_thread = std::thread(switch_screenshot_server);
        }
    }
}

void switch_shutdown_logging() {
    switch_screenshot_running.store(false, std::memory_order_relaxed);
    if (switch_screenshot_thread.joinable()) {
        switch_screenshot_thread.join();
    }

    {
        const std::lock_guard<std::mutex> lock(switch_log_mutex);
        if (switch_nxlink_socket >= 0) {
            close(switch_nxlink_socket);
            switch_nxlink_socket = -1;
        }
    }

    if (switch_socket_initialized) {
        socketExit();
        switch_socket_initialized = false;
    }
}
}

extern "C" bool switch_screenshot_capture_requested() {
    return switch_screenshot_requested.load(std::memory_order_acquire);
}

extern "C" bool switch_manual_screenshot_enabled() {
    return switch_screenshot_running.load(std::memory_order_relaxed);
}

extern "C" bool switch_request_manual_screenshot() {
    if (!switch_manual_screenshot_enabled()) {
        return false;
    }

    bool expected = false;
    if (switch_manual_screenshot_pending.compare_exchange_strong(expected, true)) {
        switch_screenshot_requested.store(true, std::memory_order_release);
        switch_log_checkpoint("screenshot: R3 capture requested", false);
    }

    return true;
}

extern "C" void switch_screenshot_capture_complete(const void *pixels, size_t size,
    uint32_t width, uint32_t height)
{
    if ((pixels == nullptr) || (size != size_t(width) * height * 4)) {
        return;
    }

    uint64_t manual_sequence = 0;
    const bool manual_capture = switch_manual_screenshot_pending.exchange(false,
        std::memory_order_acq_rel);
    {
        const std::lock_guard screenshot_lock(switch_screenshot_mutex);
        const uint8_t *source = static_cast<const uint8_t *>(pixels);
        switch_screenshot_pixels.assign(source, source + size);
        switch_screenshot_width = width;
        switch_screenshot_height = height;
        switch_screenshot_ready = true;
        if (manual_capture) {
            manual_sequence = ++switch_manual_screenshot_sequence;
        }
        switch_screenshot_requested.store(false, std::memory_order_release);
    }

    switch_screenshot_condition.notify_all();
    if (manual_capture) {
        char message[96]{};
        std::snprintf(message, sizeof(message),
            "screenshot: R3 capture #%" PRIu64 " ready", manual_sequence);
        switch_log_checkpoint(message, false);
    }
}

void switch_log_checkpoint(const char* message, bool reset = false) {
    if (message == nullptr) {
        return;
    }

    const std::lock_guard<std::mutex> lock(switch_log_mutex);
    if (reset) {
        switch_log_start_tick = armGetSystemTick();
    }

    const u64 now = armGetSystemTick();
    const u64 elapsed_ms = armTicksToNs(now - switch_log_start_tick) / 1'000'000ULL;
    const size_t message_length = std::strlen(message);
    const bool has_newline = message_length > 0 && message[message_length - 1] == '\n';

    if (switch_nxlink_socket >= 0) {
        char live_line[1024]{};
        const int formatted_length = std::snprintf(
            live_line, sizeof(live_line), "[%8" PRIu64 " ms] %s%s",
            elapsed_ms, message, has_newline ? "" : "\n");
        if (formatted_length > 0) {
            const size_t live_length = std::min(
                size_t(formatted_length), sizeof(live_line) - 1);
            const ssize_t sent = send(switch_nxlink_socket, live_line,
                live_length, MSG_DONTWAIT | MSG_NOSIGNAL);
            if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK &&
                errno != EINTR) {
                close(switch_nxlink_socket);
                switch_nxlink_socket = -1;
            }
        }
    }
}

extern "C" {
extern void (*g_drm_shim_log_sink)(const char* message);

void dusk_switch_log(const char* message) {
    if (message != nullptr) {
        switch_log_checkpoint(message);
    }
}
}

void switch_driver_log_sink(const char* message) {
    if (message != nullptr && std::strncmp(message, "NVK ", 4) == 0) {
        switch_log_checkpoint(message);
        return;
    }
    // NVK emits many messages per GPU submission. Retain only Mesa WSI's
    // bounded first-present trace so network logging stays low-volume.
    static std::atomic<uint32_t> retained_messages{0};
    if ((message != nullptr) && (std::strncmp(message, "[wsi] qp:", 9) == 0) &&
        (retained_messages.fetch_add(1, std::memory_order_relaxed) < 8)) {
        switch_log_checkpoint(message);
    }
}
#else
void switch_log_checkpoint(const char*, bool = false) {
}
#endif

void switch_log_sdl_error(const char* operation) {
    char message[512]{};
    std::snprintf(message, sizeof(message), "%s: %s", operation, SDL_GetError());
    switch_log_checkpoint(message);
}

template <typename... Ts> void exit_error(const char* str, Ts... args) {
    switch_log_checkpoint("fatal: exit_error invoked");
    // TODO pop up an error
    ((void) fprintf(stderr, str, args), ...);
    assert(false);

    ultramodern::error_handling::quick_exit(__FILE__, __LINE__, __FUNCTION__);
}

ultramodern::gfx_callbacks_t::gfx_data_t create_gfx() {
    switch_log_checkpoint("gfx: create_gfx entered");
    SDL_SetHint(SDL_HINT_WINDOWS_DPI_AWARENESS, "permonitorv2");
    // RecompFrontend uses SDL's positional layout. The Switch input layer
    // explicitly translates its Nintendo face-button labels after polling.
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS4_RUMBLE, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS5_RUMBLE, "1");
    SDL_SetHint(SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER) < 0) {
        exit_error("Failed to initialize SDL2: %s\n", SDL_GetError());
    }
    switch_log_checkpoint("gfx: SDL video and controller initialized");

    fprintf(stdout, "SDL Video Driver: %s\n", SDL_GetCurrentVideoDriver());

    return {};
}

#if defined(__gnu_linux__)
#include "icon_bytes.h"

bool SetImageAsIcon(const char* filename, SDL_Window* window) {
    // Read data
    int width, height, bytesPerPixel;
    void* data = stbi_load_from_memory(reinterpret_cast<const uint8_t*>(icon_bytes), sizeof(icon_bytes), &width,
                                       &height, &bytesPerPixel, 4);

    // Calculate pitch
    int pitch;
    pitch = width * 4;
    pitch = (pitch + 3) & ~3;

    // Setup relevance bitmask
    int Rmask, Gmask, Bmask, Amask;

#if SDL_BYTEORDER == SDL_LIL_ENDIAN
    Rmask = 0x000000FF;
    Gmask = 0x0000FF00;
    Bmask = 0x00FF0000;
    Amask = 0xFF000000;
#else
    Rmask = 0xFF000000;
    Gmask = 0x00FF0000;
    Bmask = 0x0000FF00;
    Amask = 0x000000FF;
#endif

    SDL_Surface* surface = nullptr;
    if (data != nullptr) {
        surface = SDL_CreateRGBSurfaceFrom(data, width, height, 32, pitch, Rmask, Gmask, Bmask, Amask);
    }

    if (surface == nullptr) {
        if (data != nullptr) {
            stbi_image_free(data);
        }
        return false;
    } else {
        SDL_SetWindowIcon(window, surface);
        SDL_FreeSurface(surface);
        stbi_image_free(data);
        return true;
    }
}
#endif

SDL_Window* window;

ultramodern::renderer::WindowHandle create_window(ultramodern::gfx_callbacks_t::gfx_data_t) {
    switch_log_checkpoint("gfx: create_window entered");
#if defined(__SWITCH__)
    // switch-sdl2 always creates an OpenGL ES surface for SDL windows. RT64
    // presents through NVK instead, so pass the default libnx NWindow as an
    // opaque handle and retain SDL solely for input/events/audio.
    window = reinterpret_cast<SDL_Window*>(nwindowGetDefault());
    switch_log_checkpoint("gfx: native libnx window selected");
    return window;
#else
    uint32_t flags = SDL_WINDOW_RESIZABLE;

#if defined(__APPLE__)
    flags |= SDL_WINDOW_METAL;
#elif defined(RT64_SDL_WINDOW_VULKAN)
    flags |= SDL_WINDOW_VULKAN;
#endif
    window = SDL_CreateWindow("Snowboard Kids 2: Recompiled", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                              1600, 960,
                              flags);
#if defined(__linux__)
    SetImageAsIcon("icons/512.png", window);
    if (ultramodern::renderer::get_graphics_config().wm_option ==
        ultramodern::renderer::WindowMode::Fullscreen) { // TODO: Remove once RT64 gets native fullscreen support on
                                                         // Linux
        SDL_SetWindowFullscreen(window, SDL_WINDOW_FULLSCREEN_DESKTOP);
    } else {
        SDL_SetWindowFullscreen(window, 0);
    }
#endif

    if (window == nullptr) {
        switch_log_sdl_error("gfx: SDL_CreateWindow failed");
        exit_error("Failed to create window: %s\n", SDL_GetError());
    }
    switch_log_checkpoint("gfx: SDL window created");

    // macOS can leave the launcher behind the terminal/harness that spawned it,
    // so explicitly ask SDL to surface the window after creation.
    SDL_RaiseWindow(window);
    SDL_SetWindowInputFocus(window);

    SDL_SysWMinfo wmInfo;
    SDL_VERSION(&wmInfo.version);
    SDL_GetWindowWMInfo(window, &wmInfo);

#if defined(_WIN32)
    return ultramodern::renderer::WindowHandle{ wmInfo.info.win.window, GetCurrentThreadId() };
#elif defined(__linux__) || defined(__ANDROID__) || defined(__SWITCH__)
    return ultramodern::renderer::WindowHandle{ window };
#elif defined(__APPLE__)
    SDL_MetalView view = SDL_Metal_CreateView(window);
    return ultramodern::renderer::WindowHandle{ wmInfo.info.cocoa.window, SDL_Metal_GetLayer(view) };
#else
    static_assert(false && "Unimplemented");
#endif
#endif
}

void update_gfx(void*) {
    static bool first_update = true;
    if (first_update) {
        switch_log_checkpoint("runtime: first input event pass entered");
    }
    recompinput::handle_events();
    if (first_update) {
        switch_log_checkpoint("runtime: first input event pass returned");
        first_update = false;
    }
}

static SDL_AudioCVT audio_convert;
static SDL_AudioDeviceID audio_device = 0;
static std::mutex audio_mutex;
static std::array<float, 8> duplicated_sample_buffer{};
#if defined(__SWITCH__)
static sk2::audio::QueueCorrector audio_corrector;
static std::vector<float> corrected_audio;
#endif

// Samples per channel per second.
static uint32_t sample_rate = 48000;
static uint32_t output_sample_rate = 48000;
// Channel count.
constexpr uint32_t input_channels = 2;
static uint32_t output_channels = 2;

// Terminology: a frame is a collection of samples for each channel. e.g. 2 input samples is one input frame. This is
// unrelated to graphical frames.

// Number of frames to duplicate for fixing interpolation at the start and end of a chunk.
constexpr uint32_t duplicated_input_frames = 4;
// The number of output frames to skip for playback (to avoid playing duplicate inputs twice).
static uint32_t discarded_output_frames;

constexpr uint32_t bytes_per_frame = input_channels * sizeof(float);

void queue_samples(int16_t* audio_data, size_t sample_count) {
    std::lock_guard audio_lock(audio_mutex);
    // Buffer for holding the output of swapping the audio channels. This is reused across
    // calls to reduce runtime allocations.
    static std::vector<float> swap_buffer;
#if defined(__SWITCH__)
    uint32_t chunk_peak = 0;
#endif

    // Make sure the swap buffer is large enough to hold the audio data, including any extra space needed for
    // resampling.
    size_t resampled_sample_count = sample_count + duplicated_input_frames * input_channels;
    size_t max_sample_count = std::max(resampled_sample_count, resampled_sample_count * audio_convert.len_mult);
    if (max_sample_count > swap_buffer.size()) {
        swap_buffer.resize(max_sample_count);
    }

    // Copy the duplicated frames from last chunk into this chunk
    for (size_t i = 0; i < duplicated_input_frames * input_channels; i++) {
        swap_buffer[i] = duplicated_sample_buffer[i];
    }

    // Convert the audio from 16-bit values to floats and swap the audio channels into the
    // swap buffer to correct for the address xor caused by endianness handling.
    float cur_main_volume = zelda64::get_main_volume() / 100.0f; // Get the current main volume, normalized to 0.0-1.0.
    for (size_t i = 0; i < sample_count; i += input_channels) {
#if defined(__SWITCH__)
        const int32_t left = audio_data[i + 0];
        const int32_t right = audio_data[i + 1];
        chunk_peak = std::max(chunk_peak, uint32_t(std::max(std::abs(left), std::abs(right))));
#endif
        swap_buffer[i + 0 + duplicated_input_frames * input_channels] =
            audio_data[i + 1] * (0.5f / 32768.0f) * cur_main_volume;
        swap_buffer[i + 1 + duplicated_input_frames * input_channels] =
            audio_data[i + 0] * (0.5f / 32768.0f) * cur_main_volume;
    }

    // TODO handle cases where a chunk is smaller than the duplicated frame count.
    assert(sample_count > duplicated_input_frames * input_channels);

    // Copy the last converted samples into the duplicated sample buffer to reuse in resampling the next queued chunk.
    for (size_t i = 0; i < duplicated_input_frames * input_channels; i++) {
        duplicated_sample_buffer[i] = swap_buffer[i + sample_count];
    }

    audio_convert.buf = reinterpret_cast<Uint8*>(swap_buffer.data());
    audio_convert.len = (sample_count + duplicated_input_frames * input_channels) * sizeof(swap_buffer[0]);

    int ret = SDL_ConvertAudio(&audio_convert);

    if (ret < 0) {
        printf("Error using SDL audio converter: %s\n", SDL_GetError());
        throw std::runtime_error("Error using SDL audio converter");
    }

    uint64_t cur_queued_microseconds = sk2::audio::queued_microseconds(
        SDL_GetQueuedAudioSize(audio_device), output_sample_rate, output_channels);
    uint32_t num_bytes_to_queue =
        audio_convert.len_cvt - output_channels * discarded_output_frames * sizeof(swap_buffer[0]);
    float* samples_to_queue = swap_buffer.data() + output_channels * discarded_output_frames / 2;

    // Bound queue latency. Switch uses gradual, continuous rate correction;
    // the other platforms retain their existing sample-skipping policy.
    uint32_t skip_factor = 0;
#if defined(__SWITCH__)
    audio_corrector.process(samples_to_queue, num_bytes_to_queue / (output_channels * sizeof(float)),
        cur_queued_microseconds, corrected_audio);
    samples_to_queue = corrected_audio.data();
    num_bytes_to_queue = uint32_t(corrected_audio.size() * sizeof(float));
    skip_factor = audio_corrector.correction() > 0.0;
#else
    skip_factor = uint32_t(std::min<uint64_t>(cur_queued_microseconds / 100000, 8));
    if (skip_factor != 0) {
        uint32_t skip_ratio = 1 << skip_factor;
        num_bytes_to_queue /= skip_ratio;
        for (size_t i = 0; i < num_bytes_to_queue / (output_channels * sizeof(swap_buffer[0])); i++) {
            samples_to_queue[2 * i + 0] = samples_to_queue[2 * skip_ratio * i + 0];
            samples_to_queue[2 * i + 1] = samples_to_queue[2 * skip_ratio * i + 1];
        }
    }
#endif

    // Queue the swapped audio data.
    // Offset the data start by only half the discarded frame count as the other half of the discarded frames are at the
    // end of the buffer.
    const int queue_result = SDL_QueueAudio(audio_device, samples_to_queue, num_bytes_to_queue);
#if defined(__SWITCH__)
    static uint64_t queue_count = 0;
    static uint64_t empty_queue_count = 0;
    static uint64_t queue_failure_count = 0;
    static uint32_t interval_peak = 0;
    static uint64_t interval_min_us = UINT64_MAX, interval_max_us = 0, interval_gap_us = 0;
    static uint64_t interval_input_frames = 0, interval_output_frames = 0, interval_corrections = 0;
    static auto previous_queue_time = std::chrono::steady_clock::time_point{};
    const auto queue_time = std::chrono::steady_clock::now();
    if (previous_queue_time != std::chrono::steady_clock::time_point{}) {
        interval_gap_us = std::max(interval_gap_us, uint64_t(std::chrono::duration_cast<
            std::chrono::microseconds>(queue_time - previous_queue_time).count()));
    }
    previous_queue_time = queue_time;
    interval_min_us = std::min(interval_min_us, cur_queued_microseconds);
    interval_max_us = std::max(interval_max_us, cur_queued_microseconds);
    interval_input_frames += sample_count / input_channels;
    interval_output_frames += num_bytes_to_queue / (output_channels * sizeof(float));
    interval_corrections += skip_factor != 0;
    const uint32_t queued_bytes = SDL_GetQueuedAudioSize(audio_device);

    queue_count++;
    interval_peak = std::max(interval_peak, chunk_peak);
    if ((cur_queued_microseconds == 0) && (queue_count > 1)) {
        empty_queue_count++;
    }
    if (queue_result != 0) {
        queue_failure_count++;
    }

    static std::atomic<bool> logged_first_audio_queue{false};
    if (!logged_first_audio_queue.exchange(true, std::memory_order_relaxed)) {
        char message[320]{};
        std::snprintf(message, sizeof(message),
            "audio: first queue samples=%zu input_rate=%u output_rate=%u bytes=%u result=%d status=%d queued=%u peak=%u volume=%.2f error='%s'",
            sample_count, sample_rate, output_sample_rate, num_bytes_to_queue,
            queue_result, int(SDL_GetAudioDeviceStatus(audio_device)),
            queued_bytes, chunk_peak, double(cur_main_volume), SDL_GetError());
        switch_log_checkpoint(message);
    }

    // Audio callbacks normally arrive about thirty times per second. Keep this
    // diagnostic infrequent so nxlink logging cannot become a source of
    // underruns itself.
    if ((queue_count % 120) == 0) {
        char message[320]{};
        std::snprintf(message, sizeof(message),
            "audio: health queues=%llu empty_before=%llu failures=%llu queued=%u status=%d peak=%u volume=%.2f",
            static_cast<unsigned long long>(queue_count),
            static_cast<unsigned long long>(empty_queue_count),
            static_cast<unsigned long long>(queue_failure_count), queued_bytes,
            int(SDL_GetAudioDeviceStatus(audio_device)), interval_peak, double(cur_main_volume));
        switch_log_checkpoint(message);
        interval_peak = 0;
        std::snprintf(message, sizeof(message),
            "audio: timing min_us=%llu max_us=%llu gap_us=%llu input_frames=%llu output_frames=%llu corrections=%llu",
            (unsigned long long)interval_min_us, (unsigned long long)interval_max_us,
            (unsigned long long)interval_gap_us, (unsigned long long)interval_input_frames,
            (unsigned long long)interval_output_frames, (unsigned long long)interval_corrections);
        switch_log_checkpoint(message);
        interval_min_us = UINT64_MAX;
        interval_max_us = interval_gap_us = interval_input_frames = interval_output_frames = interval_corrections = 0;
    }
#endif
}

size_t get_frames_remaining() {
    std::lock_guard audio_lock(audio_mutex);
    constexpr float buffer_offset_frames = 1.0f;
    // Get the number of remaining buffered audio bytes.
    uint64_t buffered_byte_count = sk2::audio::remaining_input_frames(
        SDL_GetQueuedAudioSize(audio_device), sample_rate, output_sample_rate, output_channels) * bytes_per_frame;

    // Adjust the reported count to be some number of refreshes in the future, which helps ensure that
    // there are enough samples even if the audio thread experiences a small amount of lag. This prevents
    // audio popping on games that use the buffered audio byte count to determine how many samples
    // to generate.
    uint32_t frames_per_vi = (sample_rate / 60);
    if (buffered_byte_count > (buffer_offset_frames * bytes_per_frame * frames_per_vi)) {
        buffered_byte_count -= (buffer_offset_frames * bytes_per_frame * frames_per_vi);
    } else {
        buffered_byte_count = 0;
    }
    // Convert from byte count to sample count.
    return static_cast<uint32_t>(buffered_byte_count / bytes_per_frame);
}

void update_audio_converter() {
    int ret = SDL_BuildAudioCVT(&audio_convert, AUDIO_F32, input_channels, sample_rate, AUDIO_F32, output_channels,
                                output_sample_rate);

    if (ret < 0) {
        printf("Error creating SDL audio converter: %s\n", SDL_GetError());
        throw std::runtime_error("Error creating SDL audio converter");
    }

    // Calculate the number of samples to discard based on the sample rate ratio and the duplicate frame count.
    discarded_output_frames = duplicated_input_frames * output_sample_rate / sample_rate;
}

void set_frequency(uint32_t freq) {
    std::lock_guard audio_lock(audio_mutex);
    if (!freq || freq == sample_rate) return;
    sample_rate = freq;
    duplicated_sample_buffer.fill(0);
#if defined(__SWITCH__)
    audio_corrector.reset();
#endif
    update_audio_converter();
}

bool reset_audio(uint32_t output_freq) {
    std::lock_guard audio_lock(audio_mutex);
    SDL_AudioSpec spec_desired{ .freq = (int) output_freq,
                                .format = AUDIO_F32,
                                .channels = (Uint8) output_channels,
                                .silence = 0, // calculated
                                .samples =
                                    0x100,    // Fairly small sample count to reduce the latency of internal buffering
                                .padding = 0, // unused
                                .size = 0,    // calculated
                                .callback = nullptr,
                                .userdata = nullptr };

    SDL_AudioSpec spec_obtained{};
    audio_device = SDL_OpenAudioDevice(nullptr, false, &spec_desired, &spec_obtained, 0);
    if (audio_device == 0) {
        std::string audio_error =
            std::string("No audio device could be found. Please make sure an audio device is available.\n"
                        "Error opening audio device: ") +
            SDL_GetError();
        recompui::message_box(audio_error.c_str());
        return false;
    }
    SDL_PauseAudioDevice(audio_device, 0);

    output_sample_rate = uint32_t(spec_obtained.freq);
    output_channels = uint32_t(spec_obtained.channels);
    update_audio_converter();

#if defined(__SWITCH__)
    char message[320]{};
    std::snprintf(message, sizeof(message),
        "audio: device opened driver='%s' id=%u requested=%dHz/%u/0x%04X obtained=%dHz/%u/0x%04X samples=%u status=%d",
        SDL_GetCurrentAudioDriver() != nullptr ? SDL_GetCurrentAudioDriver() : "none",
        unsigned(audio_device), spec_desired.freq, unsigned(spec_desired.channels),
        unsigned(spec_desired.format), spec_obtained.freq, unsigned(spec_obtained.channels),
        unsigned(spec_obtained.format), unsigned(spec_obtained.samples),
        int(SDL_GetAudioDeviceStatus(audio_device)));
    switch_log_checkpoint(message);
#endif

    return true;
}

extern RspUcodeFunc aspMain;

RspUcodeFunc* get_rsp_microcode(const OSTask* task) {
    switch (task->t.type) {
        case M_AUDTASK:
            return aspMain;

        default:
            fprintf(stderr, "Unknown task: %" PRIu32 "\n", task->t.type);
            return nullptr;
    }
}

extern "C" void recomp_entrypoint(uint8_t* rdram, recomp_context* ctx);
extern "C" void recomp_run_ui_callbacks(uint8_t* rdram, recomp_context* ctx);
gpr get_entrypoint_address();

// array of supported GameEntry objects
std::vector<recomp::GameEntry> supported_games = {
    {
        .rom_hash = 0x81f434ff431162ebULL,
        .internal_name = "SNOWBOARD KIDS2",
        .display_name = "Snowboard Kids 2",
        .game_id = u8"snowboardkids2.n64.us",
        .mod_game_id = "snowboardkids2",
        .save_type = recomp::SaveType::Eep4k,
        .is_enabled = true,
        .has_compressed_code = false,
        .entrypoint_address = get_entrypoint_address(),
        .entrypoint = recomp_entrypoint,
    },
};

// TODO: move somewhere else
namespace zelda64 {
std::string get_game_thread_name(const OSThread* t) {
    std::string name = "[Game] ";

    switch (t->id) {
        case 0:
            switch (t->priority) {
                case 150:
                    name += "PIMGR";
                    break;

                case 254:
                    name += "VIMGR";
                    break;

                default:
                    name += std::to_string(t->id);
                    break;
            }
            break;

        case 1:
            name += "IDLE";
            break;

        case 2:
            switch (t->priority) {
                case 5:
                    name += "SLOWLY";
                    break;

                case 127:
                    name += "FAULT";
                    break;

                default:
                    name += std::to_string(t->id);
                    break;
            }
            break;

        case 3:
            name += "MAIN";
            break;

        case 4:
            name += "GRAPH";
            break;

        case 5:
            name += "SCHED";
            break;

        case 7:
            name += "PADMGR";
            break;

        case 10:
            name += "AUDIOMGR";
            break;

        case 13:
            name += "FLASHROM";
            break;

        case 18:
            name += "DMAMGR";
            break;

        case 19:
            name += "IRQMGR";
            break;

        default:
            name += std::to_string(t->id);
            break;
    }

    return name;
}
} // namespace zelda64

#ifdef _WIN32

struct PreloadContext {
    HANDLE handle;
    HANDLE mapping_handle;
    SIZE_T size;
    PVOID view;
};

bool preload_executable(PreloadContext& context) {
    wchar_t module_name[MAX_PATH];
    GetModuleFileNameW(NULL, module_name, MAX_PATH);

    context.handle =
        CreateFileW(module_name, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (context.handle == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "Failed to load executable into memory!");
        context = {};
        return false;
    }

    LARGE_INTEGER module_size;
    if (!GetFileSizeEx(context.handle, &module_size)) {
        fprintf(stderr, "Failed to get size of executable!");
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    context.size = module_size.QuadPart;

    context.mapping_handle = CreateFileMappingW(context.handle, nullptr, PAGE_READONLY, 0, 0, nullptr);
    if (context.mapping_handle == nullptr) {
        fprintf(stderr, "Failed to create file mapping of executable!");
        CloseHandle(context.handle);
        context = {};
        return EXIT_FAILURE;
    }

    context.view = MapViewOfFile(context.mapping_handle, FILE_MAP_READ, 0, 0, 0);
    if (context.view == nullptr) {
        fprintf(stderr, "Failed to map view of of executable!");
        CloseHandle(context.mapping_handle);
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    DWORD pid = GetCurrentProcessId();
    HANDLE process_handle = OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (process_handle == nullptr) {
        fprintf(stderr, "Failed to open own process!");
        CloseHandle(context.mapping_handle);
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    SIZE_T minimum_set_size, maximum_set_size;
    if (!GetProcessWorkingSetSize(process_handle, &minimum_set_size, &maximum_set_size)) {
        fprintf(stderr, "Failed to get working set size!");
        CloseHandle(context.mapping_handle);
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    if (!SetProcessWorkingSetSize(process_handle, minimum_set_size + context.size, maximum_set_size + context.size)) {
        fprintf(stderr, "Failed to set working set size!");
        CloseHandle(context.mapping_handle);
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    if (VirtualLock(context.view, context.size) == 0) {
        fprintf(stderr, "Failed to lock view of executable! (Error: %08lx)\n", GetLastError());
        CloseHandle(context.mapping_handle);
        CloseHandle(context.handle);
        context = {};
        return false;
    }

    return true;
}

void release_preload(PreloadContext& context) {
    VirtualUnlock(context.view, context.size);
    CloseHandle(context.mapping_handle);
    CloseHandle(context.handle);
    context = {};
}

#elif defined(__linux__) || defined(__APPLE__) || defined(__SWITCH__)

struct PreloadContext {};

bool preload_executable(PreloadContext&) {
    // Explicit executable locking is only needed on Windows.
    return true;
}

void release_preload(PreloadContext&) {
}

#else

struct PreloadContext {};

// TODO implement on other platforms
bool preload_executable(PreloadContext&) {
    return false;
}

void release_preload(PreloadContext&) {
}

#endif

void enable_texture_pack(recomp::mods::ModContext& context, const recomp::mods::ModHandle& mod) {
    recompui::renderer::enable_texture_pack(context, mod);
}

void disable_texture_pack(recomp::mods::ModContext&, const recomp::mods::ModHandle& mod) {
    recompui::renderer::disable_texture_pack(mod);
}

void reorder_texture_pack(recomp::mods::ModContext&) {
    recompui::renderer::trigger_texture_pack_update();
}

ultramodern::input::connected_device_info_t get_sk2_connected_device_info(int controller_num) {
    if (controller_num >= 0 && controller_num < sk2_max_players) {
        return {
            .connected_device = ultramodern::input::Device::Controller,
            .connected_pak = ultramodern::input::Pak::RumblePak,
        };
    }

    return {
        .connected_device = ultramodern::input::Device::None,
        .connected_pak = ultramodern::input::Pak::None,
    };
}

#define REGISTER_FUNC(name) recomp::overlays::register_base_export(#name, name)

int main(int argc, char** argv) {
    (void) argc;
    (void) argv;
#if defined(__SWITCH__)
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--no-fps") == 0)
            SDL_setenv("SK2_SWITCH_FPS", "0", 1);
        if (std::strcmp(argv[i], "--no-profile") == 0) {
            switch_profile_enabled = false;
            SDL_setenv("SK2_SWITCH_PROFILE", "0", 1);
        }
        if (std::strcmp(argv[i], "--legacy-texture-uploads") == 0)
            SDL_setenv("SK2_SWITCH_BATCH_UPLOADS", "0", 1);
        if (std::strcmp(argv[i], "--async-submissions") == 0)
            SDL_setenv("NVK_SWITCH_ASYNC", "1", 1);
        if (std::strcmp(argv[i], "--legacy-audio-backend") == 0)
            SDL_setenv("SK2_SWITCH_LEGACY_AUDIO", "1", 1);
    }
    std::set_terminate([]() {
        const std::exception_ptr active_exception = std::current_exception();
        if (active_exception != nullptr) {
            try {
                std::rethrow_exception(active_exception);
            }
            catch (const std::exception& exception) {
                char message[1024]{};
                std::snprintf(message, sizeof(message),
                    "fatal: unhandled C++ exception: %s", exception.what());
                switch_log_checkpoint(message);
            }
            catch (...) {
                switch_log_checkpoint("fatal: unhandled non-standard C++ exception");
            }
        }
        else {
            switch_log_checkpoint("fatal: std::terminate without active exception");
        }
        switch_shutdown_logging();
        std::_Exit(EXIT_FAILURE);
    });
    const std::filesystem::path switch_root = "sdmc:/switch/snowboardkids2-recompiled";
    std::error_code switch_path_error;
    std::filesystem::create_directories(switch_root / "assets", switch_path_error);
    std::filesystem::create_directories(switch_root / "mods", switch_path_error);
    std::filesystem::create_directories(switch_root / "saves", switch_path_error);
    std::filesystem::create_directories(switch_root / "config", switch_path_error);
    std::filesystem::create_directories(switch_root / "cache", switch_path_error);
    switch_initialize_logging();
    switch_log_checkpoint("startup: entered main", true);
    switch_log_checkpoint("startup: nonblocking nxlink checkpoints enabled");
    const char* asynchronous = SDL_getenv("NVK_SWITCH_ASYNC");
    switch_log_checkpoint(asynchronous && *asynchronous == '1'
        ? "startup: NVK bounded asynchronous submissions selected"
        : "startup: NVK synchronous submissions selected");
    g_drm_shim_log_sink = switch_driver_log_sink;

    // NVK does not advertise the non-conformant GM20B device unless the
    // application opts in explicitly.
    SDL_setenv("NVK_I_WANT_A_BROKEN_VULKAN_DRIVER", "1", 1);
    // Zero-copy scanout is required for playable performance. Keep CPU-copy as
    // a recovery mode selectable from the SD card without rebuilding the NRO.
    const bool force_cpu_copy =
        std::filesystem::exists(switch_root / "config" / "force-cpu-copy", switch_path_error);
    SDL_setenv("NVK_SWITCH_WSI_CPU_COPY", force_cpu_copy ? "1" : "0", 1);
    switch_log_checkpoint(force_cpu_copy
        ? "startup: NVK CPU-copy recovery mode selected"
        : "startup: NVK zero-copy presentation selected");

    // Render the N64 scene at its native resolution and let the VI pass scale
    // it to the fixed 1280x720 swapchain. The 480p internal target overloads
    // GM20B/NVK once gameplay begins and eventually loses the device. Keep a
    // recovery marker for comparing driver behavior without rebuilding.
    const bool force_480p = std::filesystem::exists(
        switch_root / "config" / "force-480p", switch_path_error);
    SDL_setenv("SK2_SWITCH_DIAGNOSTIC_NATIVE_RESOLUTION",
        force_480p ? "0" : "1", 1);
    switch_log_checkpoint(force_480p
        ? "startup: 480p internal-resolution recovery mode selected"
        : "startup: native internal resolution selected; 720p output retained");
#endif
    recomp::Version project_version{};
    if (!recomp::Version::from_string(version_string, project_version)) {
        ultramodern::error_handling::message_box(("Invalid version string: " + version_string).c_str());
        return EXIT_FAILURE;
    }
    switch_log_checkpoint("startup: version parsed");

    // Map this executable into memory and lock it, which should keep it in physical memory. This ensures
    // that there are no stutters from the OS having to load new pages of the executable whenever a new code page is
    // run.
    PreloadContext preload_context;
    bool preloaded = preload_executable(preload_context);
    switch_log_checkpoint("startup: executable preload attempted");

    if (!preloaded) {
        fprintf(stderr, "Failed to preload executable!\n");
    }

#ifdef _WIN32
    // Set up high resolution timing period.
    timeBeginPeriod(1);

    // Process arguments.
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--show-console") == 0) {
            if (GetConsoleWindow() == nullptr) {
                AllocConsole();
                freopen("CONIN$", "r", stdin);
                freopen("CONOUT$", "w", stderr);
                freopen("CONOUT$", "w", stdout);
            }
            break;
        }
    }

    // Set up console output to accept UTF-8 on windows
    SetConsoleOutputCP(CP_UTF8);

    // Change to a font that supports Japanese characters
    CONSOLE_FONT_INFOEX cfi;
    cfi.cbSize = sizeof cfi;
    cfi.nFont = 0;
    cfi.dwFontSize.X = 0;
    cfi.dwFontSize.Y = 16;
    cfi.FontFamily = FF_DONTCARE;
    cfi.FontWeight = FW_NORMAL;
    wcscpy_s(cfi.FaceName, L"NSimSun");
    SetCurrentConsoleFontEx(GetStdHandle(STD_OUTPUT_HANDLE), FALSE, &cfi);
#endif

#ifdef _WIN32
    // Force wasapi on Windows, as there seems to be some issue with sample queueing with directsound currently.
    SDL_setenv("SDL_AUDIODRIVER", "wasapi", true);
#endif

#if defined(__linux__) && defined(RECOMP_FLATPAK)
    // When using Flatpak, applications tend to launch from the home directory by default.
    // Mods might use the current working directory to store the data, so we switch it to a directory
    // with persistent data storage and write permissions under Flatpak to ensure it works.
    std::error_code ec;
    std::filesystem::current_path("/var/data", ec);
#endif

    recompui::programconfig::set_program_name(std::string{ zelda64::program_name });
    recompui::programconfig::set_program_id(std::u8string{ zelda64::program_id });

    // Initialize SDL audio and set the output frequency.
    switch_log_checkpoint("audio: initialization entered");
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) < 0) {
        std::string audio_error = std::string("Failed to initialize audio.\nSDL error: ") + SDL_GetError();
        recompui::message_box(audio_error.c_str());
        return EXIT_FAILURE;
    }
    if (!reset_audio(48000)) {
        return EXIT_FAILURE;
    }
    switch_log_checkpoint("audio: initialized at 48 kHz");

    // Initialize native file dialogs after all fallible startup services have succeeded.
#if !defined(__SWITCH__)
    NFD_Init();
#endif

    // Source controller mappings file
    std::u8string controller_db_path = (recompui::file::get_program_path() / "recompcontrollerdb.txt").u8string();
    if (SDL_GameControllerAddMappingsFromFile(reinterpret_cast<const char*>(controller_db_path.c_str())) < 0) {
        fprintf(stderr, "Failed to load controller mappings: %s\n", SDL_GetError());
    }

    sk2::theme::apply();
    recomp::register_config_path(recompui::file::get_app_folder_path());

    // Register supported games and patches
    for (const auto& game : supported_games) {
        recomp::register_game(game);
    }

    recomp::mods::register_embedded_mod(
        "snowboardkids2_mod_template",
        { reinterpret_cast<const uint8_t*>(snowboardkids2_mod_template), snowboardkids2_mod_template_size });
    recomp::mods::register_embedded_mod(
        "snowboardkids2_randomizer",
        { reinterpret_cast<const uint8_t*>(snowboardkids2_randomizer), snowboardkids2_randomizer_size });
    recomp::mods::register_embedded_mod(
        "snowboardkids2_time_trial",
        { reinterpret_cast<const uint8_t*>(snowboardkids2_time_trial), snowboardkids2_time_trial_size });

    REGISTER_FUNC(recomp_get_target_aspect_ratio);
    REGISTER_FUNC(recomp_get_target_hud_aspect_ratio);
    REGISTER_FUNC(recomp_get_target_framerate);
    REGISTER_FUNC(recomp_get_film_grain_enabled);
    REGISTER_FUNC(recomp_get_vertical_2p_split_screen_enabled);
    REGISTER_FUNC(recomp_get_invert_y_axis_mode);
    REGISTER_FUNC(recomp_get_radio_comm_box_mode);
    REGISTER_FUNC(recomp_get_camera_inputs);
    REGISTER_FUNC(recomp_get_targeting_mode);
    REGISTER_FUNC(recomp_get_bgm_volume);
    REGISTER_FUNC(recomp_get_low_health_beeps_enabled);
    REGISTER_FUNC(recomp_get_gyro_deltas);
    REGISTER_FUNC(recomp_get_mouse_deltas);
    REGISTER_FUNC(recomp_get_inverted_axes);
    REGISTER_FUNC(recomp_get_analog_inverted_axes);
    REGISTER_FUNC(recomp_set_right_analog_suppressed);
    REGISTER_FUNC(recomp_set_game_player_count);
    REGISTER_FUNC(recomp_run_ui_callbacks);
    recompui::register_ui_exports();
    recomputil::register_data_api_exports();

    zelda64::register_overlays();
    zelda64::register_patches();
    zelda64::init_config();

    sk2::launcher::register_callbacks(supported_games[0]);
    switch_log_checkpoint("startup: game, mods, and launcher registered");

    recomp::rsp::callbacks_t rsp_callbacks{
        .get_rsp_microcode = get_rsp_microcode,
    };

    ultramodern::renderer::callbacks_t renderer_callbacks{
        .create_render_context =
            [](uint8_t* rdram, ultramodern::renderer::WindowHandle window_handle, bool developer_mode) {
                switch_log_checkpoint("renderer: context creation entered");
                auto context = recompui::renderer::create_render_context(
                    rdram, window_handle, ultramodern::renderer::PresentationMode::PresentEarly, developer_mode);
                switch_log_checkpoint("renderer: context created");
                return context;
            },
    };

    ultramodern::gfx_callbacks_t gfx_callbacks{
        .create_gfx = create_gfx,
        .create_window = create_window,
        .update_gfx = update_gfx,
    };

    ultramodern::audio_callbacks_t audio_callbacks{
        .queue_samples = queue_samples,
        .get_frames_remaining = get_frames_remaining,
        .set_frequency = set_frequency,
    };

    ultramodern::input::callbacks_t input_callbacks{
        .poll_input = recompinput::poll_inputs,
        .get_input = recompinput::profiles::get_n64_input,
        .set_rumble = recompinput::set_rumble,
        .get_connected_device_info = get_sk2_connected_device_info,
    };

    ultramodern::events::callbacks_t thread_callbacks{
        .vi_callback = recompinput::update_rumble,
        .gfx_init_callback = nullptr,
    };

    ultramodern::error_handling::callbacks_t error_handling_callbacks{
        .message_box = recompui::message_box,
    };

    ultramodern::threads::callbacks_t threads_callbacks{
        .get_game_thread_name = zelda64::get_game_thread_name,
    };

    // Register the texture pack content type with rt64.json as its content file.
    recomp::mods::ModContentType texture_pack_content_type{
        .content_filename = "rt64.json",
        .allow_runtime_toggle = true,
        .on_enabled = enable_texture_pack,
        .on_disabled = disable_texture_pack,
        .on_reordered = reorder_texture_pack,
    };
    auto texture_pack_content_type_id = recomp::mods::register_mod_content_type(texture_pack_content_type);

    // Register the .rtz texture pack file format with the previous content type as its only allowed content type.
    recomp::mods::register_mod_container_type("rtz", std::vector{ texture_pack_content_type_id }, false);

    switch_log_checkpoint("runtime: recomp::start entered");
    recomp::start(project_version, {}, rsp_callbacks, renderer_callbacks, audio_callbacks, input_callbacks,
                  gfx_callbacks, thread_callbacks, error_handling_callbacks, threads_callbacks);
    switch_log_checkpoint("runtime: recomp::start returned cleanly");

#if !defined(__SWITCH__)
    NFD_Quit();
#endif

    if (preloaded) {
        release_preload(preload_context);
    }

#if defined(__SWITCH__)
    switch_shutdown_logging();
#endif

#ifdef _WIN32
    // End high resolution timing period.
    timeEndPeriod(1);
#endif

    return EXIT_SUCCESS;
}
