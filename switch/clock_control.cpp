#include "clock_control.h"
#include "logging.h"
#include "common/rt64_switch_fast_load.h"
#include <switch.h>
#include <chrono>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <memory>
#include <thread>

namespace {
// Read-only sys-clk API v4 wire layout. No overrides or profile writes.
// Source: common/include/sysclk/clock_manager.h, commit
// 1fd95096eb08e21e390b50d8cc05223d0ebb6795. ABI fields, not client code.
struct SysClkContextV4 {
    uint8_t enabled;
    uint64_t applicationId;
    uint32_t profile;
    uint32_t freqs[3], realFreqs[3], overrideFreqs[3], temps[3];
    int32_t power[2];
    uint32_t ramLoad[2];
};
static_assert(sizeof(SysClkContextV4) == 88);
struct ManagerReader {
    std::atomic<bool> stop{false}, done{false};
    std::mutex mutex;
    sk2::clocks::Manager value = sk2::clocks::Manager::Unknown;
    std::chrono::steady_clock::time_point updated{};
    uint32_t error = 0;
};
std::shared_ptr<ManagerReader> managerReader;
std::thread managerThread;
void startManagerReader() {
    managerReader = std::make_shared<ManagerReader>();
    managerThread = std::thread([reader = managerReader] {
        bool initialized = R_SUCCEEDED(smInitialize());
        Service service{};
        uint32_t version = 0;
        while (initialized && !reader->stop.load()) {
            sk2::clocks::Manager value = sk2::clocks::Manager::Unknown;
            u8 present = 0;
            auto name = smEncodeName("sys:clk");
            Result rc = hosversionIsAtmosphere() ? tipcDispatchInOut(smGetServiceSessionTipc(), 65100, name, present) : MAKERESULT(Module_Libnx, LibnxError_IncompatSysVer);
            if (R_SUCCEEDED(rc) && !present) {
                serviceClose(&service); version = 0;
                value = sk2::clocks::Manager::Absent;
            } else if (R_SUCCEEDED(rc)) {
                if (!serviceIsActive(&service)) {
                    rc = smGetService(&service, "sys:clk");
                    if (R_SUCCEEDED(rc)) rc = serviceDispatchOut(&service, 0, version);
                }
                if (R_SUCCEEDED(rc) && version == 4) {
                    SysClkContextV4 context{};
                    rc = serviceDispatchOut(&service, 2, context);
                    if (R_SUCCEEDED(rc) && context.enabled <= 1) value = context.enabled ? sk2::clocks::Manager::Present : sk2::clocks::Manager::Inactive;
                } else if (R_SUCCEEDED(rc)) {
                    rc = MAKERESULT(Module_Libnx, LibnxError_IncompatSysVer);
                }
                if (R_FAILED(rc)) { serviceClose(&service); version = 0; }
            }
            { std::lock_guard lock(reader->mutex); reader->value = value; reader->error = rc; reader->updated = std::chrono::steady_clock::now(); }
            for (unsigned i = 0; i < 10 && !reader->stop.load(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(25));
        }
        serviceClose(&service);
        if (initialized) smExit();
        reader->done.store(true);
    });
}
void stopManagerReader() {
    if (!managerReader) return;
    managerReader->stop.store(true);
    // A vanished/stalled IPC service must never hang the application exit.
    for (unsigned i = 0; i < 30 && !managerReader->done.load(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if (managerThread.joinable()) {
        if (managerReader->done.load()) managerThread.join();
        else managerThread.detach(); // Reader owns its memory and SM reference.
    }
    managerReader.reset();
}
}

namespace sk2::clocks {
bool beginLoading();
bool endLoading();
namespace {
class HorizonBackend : public Backend {
public:
    std::array<ClkrstSession, 3> sessions{};
    std::array<bool, 3> opened{};
    bool clkrst = false, psm = false, apm = false;
    bool hardwareKnown = false, mariko = false;
    uint32_t error = 0;
    bool result(Result rc) { if (R_FAILED(rc)) error = rc; return R_SUCCEEDED(rc); }
    void open(RateLists& lists) {
        if (hosversionBefore(8, 0, 0)) return;
        clkrst = result(clkrstInitialize());
        psm = result(psmInitialize());
        apm = result(apmInitialize());
        u64 sku = 0;
        if (R_SUCCEEDED(splInitialize())) {
            hardwareKnown = result(splGetConfig(SplConfigItem_HardwareType, &sku)) && sku <= 5;
            mariko = sku >= 2 && sku <= 5;
            splExit();
        }
        if (!clkrst) return;
        const PcvModuleId modules[]{PcvModuleId_CpuBus, PcvModuleId_GPU, PcvModuleId_EMC};
        for (unsigned i = 0; i < 3; ++i) {
            opened[i] = result(clkrstOpenSession(&sessions[i], modules[i], 3));
            if (!opened[i]) continue;
            std::array<u32, 128> rates{};
            s32 count = 0;
            PcvClockRatesListType type{};
            if (result(clkrstGetPossibleClockRates(&sessions[i], rates.data(), rates.size(), &type, &count)) &&
                type == PcvClockRatesListType_Discrete && count > 0 && count <= s32(rates.size())) {
                lists[i] = policyRates(i, {rates.begin(), rates.begin() + count});
            }
        }
    }
    void close() {
        for (unsigned i = 0; i < 3; ++i) if (opened[i]) { clkrstCloseSession(&sessions[i]); opened[i] = false; }
        if (clkrst) clkrstExit();
        if (psm) psmExit();
        if (apm) apmExit();
        clkrst = psm = apm = false;
    }
    Manager manager() {
        // Atmosphere's nonblocking HasService extension, no temporary service
        // registration and no potentially deferred GetServiceHandle request.
        if (!managerReader) return Manager::Unknown;
        std::lock_guard lock(managerReader->mutex);
        if (std::chrono::steady_clock::now() - managerReader->updated > std::chrono::milliseconds(1500)) return Manager::Unknown;
        if (managerReader->error) error = managerReader->error;
        return managerReader->value;
    }
    Environment environment() {
        Environment value;
        value.manager = manager();
        value.mariko = mariko;
        value.focused = appletGetFocusState() == AppletFocusState_InFocus;
        value.available = clkrst && psm && apm && hardwareKnown && std::all_of(opened.begin(), opened.end(), [](bool open) { return open; });
        if (!value.available) return value;
        ApmPerformanceMode mode;
        PsmChargerType charger;
        if (!result(apmGetPerformanceMode(&mode)) || !result(psmGetChargerType(&charger)) ||
            !result(apmGetPerformanceConfiguration(mode, &value.configuration))) { value.available = false; return value; }
        value.docked = mode == ApmPerformanceMode_Boost;
        value.charger = unsigned(charger);
        return value;
    }
    bool read(Rates& values) override {
        Rates resultValues{};
        for (unsigned i = 0; i < 3; ++i) if (!opened[i] || !result(clkrstGetClockRate(&sessions[i], &resultValues[i]))) return false;
        values = resultValues;
        return true;
    }
    bool write(unsigned module, uint32_t hz) override { return opened[module] && hz && result(clkrstSetClockRate(&sessions[module], hz)); }
    bool resetProfile() override {
        ApmPerformanceMode mode;
        u32 config;
        return result(apmGetPerformanceMode(&mode)) && result(apmGetPerformanceConfiguration(mode, &config)) && result(apmSetPerformanceConfiguration(mode, config));
    }
} backend;
State state(backend);
std::mutex mutex;
bool initialized = false, loading = false, resetPending = false;
AppletHookCookie hookCookie{};
std::atomic<bool> changed{false}, exitRequested{false};
std::atomic<bool> resumePending{false};
std::chrono::steady_clock::time_point lastTick{};
std::string lastLog;
void logState() {
    char line[320];
    std::snprintf(line, sizeof(line), "clocks: %s CPU=%u GPU=%u MEM=%u cap=%u rc=0x%08X", state.status.c_str(), state.actual[0], state.actual[1], state.actual[2], state.environment.gpuCap(), backend.error);
    if (lastLog != line) { switch_log_checkpoint(line); lastLog = line; }
}
void hook(AppletHookType type, void*) {
    if (type == AppletHookType_OnExitRequest) exitRequested.store(true);
    if (type == AppletHookType_OnResume ||
        (type == AppletHookType_OnFocusState && appletGetFocusState() != AppletFocusState_InFocus)) resumePending.store(true);
    if (type == AppletHookType_OnFocusState || type == AppletHookType_OnOperationMode ||
        type == AppletHookType_OnPerformanceMode || type == AppletHookType_OnResume || type == AppletHookType_OnExitRequest) changed.store(true);
}
void poll() {
    auto environment = backend.environment();
    environment.exiting = exitRequested.load();
    // Preserve a focus-loss/resume event even if Horizon suspended execution
    // before the next tick. Release stale ownership before reacquiring.
    if (resumePending.exchange(false)) {
        auto inactive = environment;
        inactive.focused = false;
        state.poll(inactive);
        logState();
    }
    state.poll(environment);
    logState();
}
}

void initialize() {
    std::lock_guard lock(mutex);
    if (initialized) return;
    backend.open(state.supported);
    startManagerReader();
    appletHook(&hookCookie, hook, nullptr);
    backend.result(appletSetFocusHandlingMode(AppletFocusHandlingMode_SuspendHomeSleepNotify));
    initialized = true;
    std::atexit(shutdown);
    RT64::SwitchFastLoad::setCallbacks(beginLoading, endLoading);
    poll();
}
void shutdown() {
    std::lock_guard lock(mutex);
    if (!initialized) return;
    if (loading) appletSetCpuBoostMode(ApmCpuBoostMode_Normal);
    loading = false;
    resetPending = false;
    // An external manager takes precedence even during clean shutdown.
    auto manager = backend.manager();
    if (manager == Manager::Absent || manager == Manager::Inactive) state.release(!state.environment.samePower(backend.environment()));
    logState();
    appletUnhook(&hookCookie);
    backend.close(); initialized = false;
    stopManagerReader();
}
void tick() {
    std::lock_guard lock(mutex);
    if (!initialized) return;
    auto now = std::chrono::steady_clock::now();
    if (!changed.exchange(false) && now - lastTick < std::chrono::milliseconds(500)) return;
    lastTick = now;
    if (loading) {
        if (resetPending) {
            Result rc = appletSetCpuBoostMode(ApmCpuBoostMode_Normal);
            if (R_FAILED(rc) && hosversionAtLeast(10, 0, 0)) rc = appletCancelCpuBoostMode();
            if (R_SUCCEEDED(rc)) { loading = resetPending = false; poll(); state.apply(); }
            else backend.error = rc;
        }
        backend.read(state.actual); logState();
        return;
    }
    poll();
}
bool configure(Selection selection) {
    std::lock_guard lock(mutex);
    if (!initialized) return false;
    if (!loading) poll();
    if (state.canControl()) backend.error = 0;
    bool ok;
    if (loading) { // Preserve preference, apply after FastLoad restores Normal.
        ok = state.valid(selection);
        if (ok) state.desired = selection;
    } else ok = state.configure(selection);
    logState();
    return ok;
}
Snapshot snapshot() {
    std::lock_guard lock(mutex);
    return {state.desired, state.supported, state.actual, state.effective, state.environment,
        loading ? "FastLoad active; gameplay settings resume after loading" : state.status, backend.error, loading};
}

bool beginLoading() {
    std::lock_guard lock(mutex);
    if (!initialized || loading || !state.desired.fastLoad) return false;
    poll();
    if (!state.canControl() || !state.release()) return false;
    Result rc = appletSetCpuBoostMode(ApmCpuBoostMode_FastLoad);
    if (R_FAILED(rc)) { state.apply(); switch_log_checkpoint("FastLoad unavailable; retained gameplay clocks"); return false; }
    loading = true;
    backend.read(state.actual);
    state.status = "FastLoad enabled"; logState();
    return true;
}
bool endLoading() {
    std::lock_guard lock(mutex);
    if (!loading) return true;
    Result rc = appletSetCpuBoostMode(ApmCpuBoostMode_Normal);
    if (R_FAILED(rc) && hosversionAtLeast(10, 0, 0)) rc = appletCancelCpuBoostMode();
    if (R_FAILED(rc)) { resetPending = true; backend.error = rc; state.status = "FastLoad reset failed; retry pending"; logState(); return false; }
    loading = resetPending = false;
    state.status = "FastLoad disabled"; switch_log_checkpoint("FastLoad disabled; restoring gameplay selection");
    poll();
    state.apply(); logState();
    return true;
}
}
