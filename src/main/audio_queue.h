#pragma once

#include <cstdint>

namespace sk2::audio {
// Queue bytes always belong to the output device, not the game's input rate.
constexpr uint64_t queued_microseconds(uint64_t bytes, uint32_t output_rate,
                                      uint32_t channels, uint32_t sample_bytes = sizeof(float)) {
    return output_rate && channels && sample_bytes
        ? (bytes / (uint64_t(channels) * sample_bytes)) * 1'000'000 / output_rate : 0;
}

constexpr uint64_t remaining_input_frames(uint64_t bytes, uint32_t input_rate,
                                          uint32_t output_rate, uint32_t channels) {
    return output_rate && channels
        ? (bytes / (uint64_t(channels) * sizeof(float))) * input_rate / output_rate : 0;
}
}
