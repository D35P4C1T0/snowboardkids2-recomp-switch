#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace sk2::clocks {
using Rates = std::array<uint32_t, 3>;
using RateLists = std::array<std::vector<uint32_t>, 3>;
enum class Manager { Absent, Inactive, Present, Unknown };
struct Environment {
    bool available = false, focused = true, exiting = false, mariko = false, docked = false;
    unsigned charger = 0;
    uint32_t configuration = 0;
    Manager manager = Manager::Unknown;
    bool samePower(const Environment& other) const {
        return docked == other.docked && charger == other.charger && configuration == other.configuration;
    }
    uint32_t gpuCap() const { return docked || charger == 1 || charger == 2 ? 768000000 : mariko ? 614400000 : 460800000; }
};
struct Selection {
    bool custom = false, fastLoad = true;
    Rates hz{}; // Zero means system managed, never a zero-Hz clock request.
};
inline std::vector<uint32_t> policyRates(unsigned module, const std::vector<uint32_t>& supported) {
    const std::array<std::vector<uint32_t>, 3> policy{{
        {1020000000, 1224000000, 1326000000, 1428000000, 1581000000, 1683000000, 1785000000},
        {76800000, 153600000, 230400000, 307200000, 384000000, 460800000, 537600000, 614400000, 691200000, 768000000},
        {1600000000}
    }};
    std::vector<uint32_t> result;
    for (auto hz : policy.at(module)) if (std::find(supported.begin(), supported.end(), hz) != supported.end()) result.push_back(hz);
    return result;
}
struct Backend {
    virtual ~Backend() = default;
    virtual bool read(Rates&) = 0;
    virtual bool write(unsigned module, uint32_t hz) = 0;
    virtual bool resetProfile() = 0;
};
// Platform-independent ownership/transaction logic; all calls are serialized
// by the application controller, including loading scopes and applet events.
class State {
    Backend& backend;
    std::array<bool, 3> owned{};
    Rates baseline{}, written{};
    bool blocked = false, pendingFocusRelease = false;
    bool rollback(const std::vector<unsigned>& changed, const Rates& before) {
        bool restored = true;
        for (auto it = changed.rbegin(); it != changed.rend(); ++it) restored = backend.write(*it, before[*it]) && restored;
        if (!restored) {
            Rates current;
            bool readable = backend.read(current);
            // Retain recovery ownership for changed modules rather than
            // forgetting a partially applied clock after a rollback failure.
            for (auto i : changed) {
                if (!owned[i]) baseline[i] = before[i];
                owned[i] = true;
                if (readable) written[i] = current[i];
            }
        }
        return restored;
    }
public:
    Selection desired;
    Environment environment;
    RateLists supported;
    Rates actual{}, effective{};
    std::string status = "System managed";
    explicit State(Backend& backend) : backend(backend) {}
    bool hasOwnership() const { return std::any_of(owned.begin(), owned.end(), [](bool value) { return value; }); }
    bool canControl() const { return environment.available && (environment.manager == Manager::Absent || environment.manager == Manager::Inactive) && environment.focused && !environment.exiting; }
    bool valid(const Selection& selection) const {
        for (unsigned i = 0; i < 3; ++i) if (selection.hz[i] && std::find(supported[i].begin(), supported[i].end(), selection.hz[i]) == supported[i].end()) return false;
        return true;
    }
    bool release(bool profileChanged = false) {
        if (!hasOwnership()) return true;
        Rates current;
        if (!backend.read(current)) { status = "Clock read failed; restoration pending"; return false; }
        // If another owner/system changed a rate, never replace its new value.
        bool unchanged = true;
        for (unsigned i = 0; i < 3; ++i) if (owned[i] && current[i] != written[i]) unchanged = false;
        if (profileChanged) {
            if (unchanged && !backend.resetProfile()) { status = "System profile reset failed"; return false; }
            owned.fill(false);
            return true;
        }
        bool success = true;
        for (unsigned i = 0; i < 3; ++i) if (owned[i]) {
            if (current[i] != written[i] || backend.write(i, baseline[i])) owned[i] = false;
            else success = false;
        }
        if (!success) status = "Clock restoration failed; retry pending";
        if (success && !backend.read(actual)) actual = {};
        return success;
    }
    bool apply() {
        if (!canControl() || blocked) return false;
        if (!desired.custom) {
            bool ok = release();
            if (ok) { effective = {}; status = "System managed"; }
            return ok;
        }
        Rates before;
        if (!backend.read(before)) { actual = {}; status = "Clock read failed"; blocked = true; return false; }
        Rates target = desired.hz;
        if (target[1] > environment.gpuCap()) {
            target[1] = 0;
            for (auto hz : supported[1]) if (hz <= environment.gpuCap()) target[1] = std::max(target[1], hz);
            if (!target[1]) { status = "No supported GPU rate for this power mode"; blocked = true; return false; }
        }
        auto nextOwned = owned;
        Rates nextBaseline = baseline;
        Rates expected = before;
        std::vector<unsigned> changed;
        for (unsigned i = 0; i < 3; ++i) {
            if (target[i] && !owned[i]) nextBaseline[i] = before[i];
            uint32_t rate = target[i] ? target[i] : owned[i] ? baseline[i] : before[i];
            expected[i] = rate;
            if (rate != before[i]) {
                bool ok = backend.write(i, rate);
                // Include even a failed write: a backend error may occur after
                // the request partially changed hardware state.
                changed.push_back(i);
                if (!ok) {
                    bool restored = rollback(changed, before);
                    status = restored ? "Apply failed; previous clocks restored" : "Apply and rollback failed; select System to recover";
                    blocked = true;
                    return false;
                }
            }
            nextOwned[i] = target[i] != 0;
        }
        Rates observed;
        if (!backend.read(observed) || observed != expected) {
            bool restored = rollback(changed, before);
            status = restored ? "Readback mismatch; previous clocks restored" : "Readback and rollback failed; select System to recover";
            blocked = true;
            return false;
        }
        baseline = nextBaseline; owned = nextOwned; written = observed;
        actual = observed; effective = target;
        status = target[1] != desired.hz[1] ? "Applied; GPU capped for current power mode" : "Custom clocks applied";
        return true;
    }
    bool configure(Selection selection) {
        if (!valid(selection)) { status = "Unsupported saved/requested frequency"; return false; }
        desired = selection; blocked = false;
        if (!canControl()) return false;
        return apply();
    }
    void poll(Environment next) {
        bool powerChanged = !environment.samePower(next);
        bool regained = (!environment.focused && next.focused) || (!environment.available && next.available);
        regained = regained || (environment.manager != next.manager && (next.manager == Manager::Absent || next.manager == Manager::Inactive));
        environment = next;
        if (!next.focused || next.exiting) pendingFocusRelease = true;
        if (next.manager != Manager::Absent && next.manager != Manager::Inactive) {
            // A stale/failed manager query is not evidence of a new owner.
            // Preserve matching-rate restoration records until discovery recovers.
            if (next.manager == Manager::Present) { owned.fill(false); pendingFocusRelease = false; }
            effective = {}; blocked = true;
            status = next.manager == Manager::Present ? "Managed by sys-clk" : "Clock ownership unavailable";
            if (!backend.read(actual)) actual = {};
            return;
        }
        if (!next.available) { status = "Clock services unavailable"; return; }
        if (powerChanged && !release(true)) { blocked = true; return; }
        if (pendingFocusRelease || (regained && hasOwnership())) {
            if (!release()) return;
            pendingFocusRelease = false;
        }
        if (!next.focused || next.exiting) {
            if (release()) { effective = {}; status = "System managed while suspended"; }
            return;
        }
        Rates observed;
        if (!backend.read(observed)) { actual = {}; status = "Clock read failed"; blocked = true; return; }
        actual = observed;
        if (hasOwnership() && !powerChanged) {
            for (unsigned i = 0; i < 3; ++i) if (owned[i] && actual[i] != written[i]) {
                // Relinquish remaining unchanged modules too. Do not keep
                // fighting a changed rate in a periodic loop.
                release(); effective = {}; blocked = true;
                status = "Clocks changed externally; reapply to take control";
                return;
            }
        }
        if (regained || powerChanged) blocked = false;
        if (!blocked && (powerChanged || regained || (desired.custom && !hasOwnership()) || (!desired.custom && hasOwnership()))) apply();
    }
};
}
