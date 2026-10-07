#pragma once
#include "clock_state.h"

namespace sk2::clocks {
struct Snapshot {
    Selection desired;
    RateLists rates;
    Rates actual{}, effective{};
    Environment environment;
    std::string status;
    uint32_t error = 0;
    bool loading = false;
};
void initialize();
void shutdown();
void tick();
bool configure(Selection selection);
Snapshot snapshot();
void create_performance_tab();
}
