#pragma once

#include <cstdint>

void switch_set_profile_enabled(bool enabled);

extern "C" {
float switch_fps_value();
void switch_fps_presented();
void switch_perf_record(const char* stage, uint64_t elapsed_ns, uint64_t id);
}
