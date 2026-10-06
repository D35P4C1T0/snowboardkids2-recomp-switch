#include "screenshots.h"
#include "logging.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cinttypes>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include "../lib/RecompFrontend/recompui/lib/lunasvg/plutovg/include/plutovg.h"

namespace {
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
}

void switch_start_screenshots() {
    switch_screenshot_running.store(true, std::memory_order_relaxed);
    switch_screenshot_thread = std::thread(switch_screenshot_server);
}
void switch_stop_screenshots() {
    switch_screenshot_running.store(false, std::memory_order_relaxed);
    if (switch_screenshot_thread.joinable()) {
        switch_screenshot_thread.join();
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
