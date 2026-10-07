#!/usr/bin/env python3
"""Exercise the production loading boost against unavailable/failing services."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
tree = root / 'build-switch-deps/rt64/src'
stub = r'''
#pragma once
#include <cstdint>
using Result=uint32_t;
using Handle=uint32_t;
constexpr Handle INVALID_HANDLE=0;
#define R_FAILED(r) ((r)!=0)
#define R_SUCCEEDED(r) ((r)==0)
enum ApmCpuBoostMode { ApmCpuBoostMode_Normal, ApmCpuBoostMode_FastLoad };
struct SmServiceName {};
extern unsigned firmware, registrations, unregisters, closes, boosts, resets, cancels;
extern Result probeResult, cleanupResult, boostResult, resetResult, cancelResult;
inline bool hosversionBefore(unsigned major,unsigned,unsigned) { return firmware<major; }
inline bool hosversionAtLeast(unsigned major,unsigned,unsigned) { return firmware>=major; }
inline SmServiceName smEncodeName(const char*) { return {}; }
inline Result smRegisterService(Handle* handle,SmServiceName,bool,int) { registrations++;*handle=42;return probeResult; }
inline Result smUnregisterService(SmServiceName) { unregisters++;return cleanupResult; }
inline Result svcCloseHandle(Handle) { closes++;return 0; }
inline Result appletSetCpuBoostMode(ApmCpuBoostMode mode) {
    if (mode==ApmCpuBoostMode_FastLoad) { boosts++;return boostResult; }
    resets++;return resetResult;
}
inline Result appletCancelCpuBoostMode() { cancels++;return cancelResult; }
'''
test = r'''
#include <cassert>
#include <future>
#include <stdexcept>
#include "common/rt64_switch_fast_load.h"
unsigned firmware=20,registrations=0,unregisters=0,closes=0,boosts=0,resets=0,cancels=0;
Result probeResult=0,cleanupResult=0,boostResult=0,resetResult=0,cancelResult=0;
void switch_log_checkpoint(const char*,bool) {}
unsigned delegatedBegins=0,delegatedEnds=0;
bool beginDelegate() { delegatedBegins++;return true; }
bool endDelegate() { delegatedEnds++;return delegatedEnds>1; }
void clear() {
    firmware=20;registrations=unregisters=closes=boosts=resets=cancels=0;
    probeResult=cleanupResult=boostResult=resetResult=cancelResult=0;
}
int main() {
    { RT64::SwitchFastLoad load;assert(boosts==1 && closes==1 && unregisters==1);
      load.finish();assert(resets==1);load.finish();assert(resets==1); }
    assert(resets==1);
    clear();try { RT64::SwitchFastLoad load;throw std::runtime_error("load failed"); }
    catch (const std::runtime_error&) {} assert(resets==1);
    clear();probeResult=1;{ RT64::SwitchFastLoad load; }assert(boosts==0 && closes==0 && unregisters==0);
    clear();cleanupResult=1;{ RT64::SwitchFastLoad load; }assert(boosts==0 && closes==1);
    clear();boostResult=1;{ RT64::SwitchFastLoad load; }assert(boosts==1 && resets==0);
    clear();firmware=6;{ RT64::SwitchFastLoad load; }assert(registrations==0 && boosts==0);
    clear();resetResult=1;{ RT64::SwitchFastLoad load;load.finish(); }assert(resets==1 && cancels==1);
    clear();resetResult=cancelResult=1;
    { RT64::SwitchFastLoad load;load.finish();assert(resets==1 && cancels==1);
      resetResult=0; }assert(resets==2);
    clear();firmware=9;resetResult=1;
    { RT64::SwitchFastLoad load;load.finish();resetResult=0; }assert(resets==2 && cancels==0);
    clear();{ RT64::SwitchFastLoad first;
      std::async(std::launch::async, [] { RT64::SwitchFastLoad overlapping; }).get();
      assert(boosts==1 && resets==0); }assert(resets==1);
    clear();RT64::SwitchFastLoad::setCallbacks(beginDelegate,endDelegate);
    { RT64::SwitchFastLoad load;load.finish();assert(delegatedEnds==1); }
    assert(delegatedBegins==1 && delegatedEnds==2 && boosts==0 && registrations==0);
    RT64::SwitchFastLoad::setCallbacks(nullptr,nullptr);
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-fast-load-') as folder:
    folder = Path(folder)
    (folder / 'switch.h').write_text(stub)
    (folder / 'test.cpp').write_text(test)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra',
                    '-Werror', '-fsanitize=address,undefined', '-I', str(folder),
                    '-I', str(tree), str(folder / 'test.cpp'), '-o', str(folder / 'test')], check=True)
    subprocess.run([str(folder / 'test')], check=True)
print('PASS: FastLoad scope, restoration, service failures, sys-clk guard and overlapping ownership')
