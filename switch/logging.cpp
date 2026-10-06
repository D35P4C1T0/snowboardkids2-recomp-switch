#include "logging.h"
#include "screenshots.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <switch.h>
#include <unistd.h>

namespace {
std::mutex switch_log_mutex;
u64 switch_log_start_tick = 0;
int switch_nxlink_socket = -1;
bool switch_socket_initialized = false;
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

            switch_start_screenshots();
        }
    }
}

void switch_shutdown_logging() {
    switch_stop_screenshots();

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

void switch_log_checkpoint(const char* message, bool reset) {
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

void switch_install_driver_log_sink() {
    g_drm_shim_log_sink = switch_driver_log_sink;
}
