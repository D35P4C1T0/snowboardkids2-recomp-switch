#pragma once

#include <cstddef>
#include <cstdint>

void switch_start_screenshots();
void switch_stop_screenshots();

extern "C" {
bool switch_screenshot_capture_requested();
bool switch_manual_screenshot_enabled();
bool switch_request_manual_screenshot();
void switch_screenshot_capture_complete(const void* pixels, size_t size,
    uint32_t width, uint32_t height);
}
