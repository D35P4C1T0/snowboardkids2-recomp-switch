#include "clock_control.h"
#include "recompui/config.h"
#include "util/file.h"
#include "logging.h"
#include <cstdio>
#include <fstream>

namespace sk2::clocks {
namespace {
constexpr const char* id = "switch_performance";
constexpr const char* modules[]{"cpu", "gpu", "memory"};
std::string persistenceStatus;
std::string mhz(uint32_t hz) {
    if (!hz) return "Unavailable";
    char text[32];
    if (hz % 1000000 == 0) std::snprintf(text, sizeof(text), "%u MHz", hz / 1000000);
    else std::snprintf(text, sizeof(text), "%.1f MHz", double(hz) / 1000000);
    return text;
}
void apply(bool saving) {
    auto& config = recompui::config::get_config(id);
    Selection selection;
    selection.custom = std::get<uint32_t>(config.get_option_value("control")) == 1;
    selection.fastLoad = std::get<bool>(config.get_option_value("fast_load"));
    for (unsigned i = 0; i < 3; ++i) selection.hz[i] = std::get<uint32_t>(config.get_option_value(modules[i]));
    char message[192];
    std::snprintf(message, sizeof(message), "performance config: %s custom=%u CPU=%u GPU=%u MEM=%u fast_load=%u", saving ? "save" : "load", unsigned(selection.custom), selection.hz[0], selection.hz[1], selection.hz[2], unsigned(selection.fastLoad));
    switch_log_checkpoint(message);
    if (saving) {
        nlohmann::json saved;
        std::ifstream file(recompui::file::get_app_folder_path() / "switch_performance.json");
        try { file >> saved; } catch (const nlohmann::json::exception&) { saved = nullptr; }
        persistenceStatus = saved == config.get_json_config() ? "" : "Save verification failed; settings applied for this session only";
        switch_log_checkpoint(persistenceStatus.empty() ? "performance config: saved settings verified on SD" : persistenceStatus.c_str());
    }
    configure(selection);
}
void refresh() {
    auto& config = recompui::config::get_config(id);
    auto view = snapshot();
    bool unavailable = !view.environment.available || (view.environment.manager != Manager::Absent && view.environment.manager != Manager::Inactive);
    config.update_option_disabled("control", unavailable);
    config.update_option_disabled("fast_load", unavailable);
    bool custom = std::get<uint32_t>(config.get_temp_option_value("control")) == 1;
    for (unsigned i = 0; i < 3; ++i) {
        config.update_option_disabled(modules[i], unavailable || !custom || view.rates[i].empty());
        std::string details = "Current: " + mhz(view.actual[i]);
        if (view.desired.custom && view.desired.hz[i]) {
            details += " | Requested: " + mhz(view.desired.hz[i]);
            if (view.effective[i] && view.effective[i] != view.desired.hz[i]) details += " | Applied: " + mhz(view.effective[i]);
        }
        if (config.get_enum_option_details(config.get_config_schema().options_by_id.at(modules[i])) != details) config.update_option_enum_details(modules[i], details);
    }
    std::string details = view.status;
    if (!persistenceStatus.empty()) details += " | " + persistenceStatus;
    if (view.environment.manager == Manager::Inactive) details += " | sys-clk disabled";
    if (view.environment.available) {
    details += " | " + std::string(view.environment.mariko ? "Mariko" : "Erista");
    details += view.environment.docked ? " / Docked" : view.environment.charger == 1 ? " / Charger" : view.environment.charger == 2 ? " / USB power" : " / Battery";
    details += " | GPU limit: " + mhz(view.environment.gpuCap());
    }
    if (view.error) { char error[32]; std::snprintf(error, sizeof(error), " | Error 0x%08X", view.error); details += error; }
    if (config.get_enum_option_details(config.get_config_schema().options_by_id.at("status")) != details) config.update_option_enum_details("status", details);
}
}
void create_performance_tab() {
    initialize();
    auto view = snapshot();
    auto& config = recompui::config::create_config_tab("Performance", id, true);
    config.add_enum_option("status", "Clock status", "Live ownership and power mode. If sys-clk is enabled it manages clocks; use its own controls or disable it there to use Custom here. Selecting System and Apply resets application overrides.", {}, 0);
    config.update_option_disabled("status", true);
    config.add_enum_option("control", "Clock control", "System returns clock control to Horizon. Custom applies the frequencies below. Select System and Apply to reset clocks. An installed sys-clk manager takes precedence.", {{0, "system", "System"}, {1, "custom", "Custom"}}, 0);
    const char* names[]{"CPU clock", "GPU clock", "Memory clock"};
    const char* descriptions[]{
        "CPU frequency for gameplay. Higher CPU clocks may help emulation. Only supported rates up to 1785 MHz are offered.",
        "GPU frequency for gameplay. Battery and charger limits apply automatically; your saved request is retained when power mode changes.",
        "Memory frequency for gameplay. System or a supported 1600 MHz rate. No voltage changes or extended memory rates are used."
    };
    for (unsigned i = 0; i < 3; ++i) {
        std::vector<recomp::config::ConfigOptionEnumOption> choices{{0, "system", "System"}};
        for (auto hz : view.rates[i]) choices.emplace_back(hz, std::to_string(hz), mhz(hz));
        config.add_enum_option(modules[i], names[i], descriptions[i], choices, 0);
    }
    config.add_bool_option("fast_load", "Boost during loading", "Temporarily boosts CPU while shader loading is displayed. GPU clocks are reduced during this period. Gameplay clocks resume afterward. Disabled when sys-clk owns clocks.", true);
    config.set_load_callback([] { apply(false); });
    config.set_save_callback([] { apply(true); });
    recompui::config::set_refresh_callback(refresh);
}
}
