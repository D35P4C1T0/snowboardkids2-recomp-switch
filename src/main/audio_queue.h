#pragma once

#include <cstdint>
#include <array>
#include <algorithm>
#include <cmath>
#include <vector>

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

// Correct only excessive output backlog. Keep phase and the previous stereo
// frame across chunks; never decimate an entire chunk by an integer factor.
class QueueCorrector {
    std::array<float, 2> previous{};
    double position = 0.0;
    double rate = 0.0;
    bool has_previous = false, catching_up = false;
public:
    void reset() { *this = QueueCorrector{}; }
    double correction() const { return rate; }
    void process(const float* input, size_t frames, uint64_t queued_us, std::vector<float>& output) {
        output.clear();
        if (!frames) return;
        if (queued_us > 110'000) catching_up = true;
        else if (queued_us < 80'000) catching_up = false;
        const double target = !catching_up ? 0.0 :
            queued_us > 500'000 ? 0.05 : queued_us > 250'000 ? 0.02 : 0.005;
        const size_t prefix = has_previous ? 1 : 0;
        const size_t available = frames + prefix;
        output.reserve(available * 2);
        while (position < double(available - 1)) {
            const size_t first = size_t(position);
            const float fraction = float(position - double(first));
            for (size_t channel = 0; channel < 2; channel++) {
                const float a = prefix && !first ? previous[channel] : input[(first - prefix) * 2 + channel];
                const float b = input[(first + 1 - prefix) * 2 + channel];
                output.push_back(a + (b - a) * fraction);
            }
            rate += std::clamp(target - rate, -0.0000005, 0.0000005);
            position += 1.0 + rate;
        }
        position -= double(available - 1);
        previous = {input[(frames - 1) * 2], input[(frames - 1) * 2 + 1]};
        has_previous = true;
    }
};
}
