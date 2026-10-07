#!/usr/bin/env python3
"""Test production frequency policy, ownership and transactions without hardware."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
test = r'''
#include <cassert>
#include <set>
#include "switch/clock_state.h"
using namespace sk2::clocks;
struct Fake : Backend {
    Rates rates{1020000000,307200000,1331200000};
    unsigned writes=0,resets=0;
    std::set<unsigned> failures;
    bool readable=true,mismatch=false;
    bool read(Rates& out) override { if (!readable) return false;out=rates;return true; }
    bool write(unsigned i,uint32_t hz) override {
        assert(hz);++writes;
        if (failures.count(writes)) return false;
        rates[i]=mismatch && writes==1 ? hz-1 : hz;return true;
    }
    bool resetProfile() override { resets++;rates={1020000000,768000000,1600000000};return true; }
};
Environment available() { Environment e;e.available=true;e.manager=Manager::Absent;return e; }
void setup(State& state) {
    state.supported={policyRates(0,{1020000000,1785000000,2397000000}),
        policyRates(1,{307200000,460800000,614400000,768000000,921600000}),
        policyRates(2,{1331200000,1600000000,1862400000})};
    state.poll(available());
}
Selection custom() { return {true,true,{1785000000,768000000,1600000000}}; }
int main() {
    assert(policyRates(0,{2397000000}).empty());
    assert(policyRates(2,{1862400000}).empty());
    assert(available().gpuCap()==460800000);
    auto mode=available();mode.mariko=true;assert(mode.gpuCap()==614400000);
    mode.charger=2;assert(mode.gpuCap()==768000000);
    mode.charger=3;assert(mode.gpuCap()==614400000);
    { Fake b;State s(b);setup(s);assert(b.writes==0);
      auto invalid=custom();invalid.hz[0]=2397000000;
      assert(!s.configure(invalid) && b.writes==0);
      assert(s.configure(custom()));assert(b.rates[1]==460800000 && s.effective[1]==460800000);
      assert(s.desired.hz[1]==768000000);
      auto before=b.writes;s.poll(available());s.poll(available());assert(b.writes==before);
      assert(s.configure({false,true,{}}));assert((b.rates==Rates{1020000000,307200000,1331200000})); }
    { Fake b;State s(b);setup(s);auto before=b.rates;b.failures={2};
      assert(!s.configure(custom()));assert(b.rates==before && !s.hasOwnership());
      auto writes=b.writes;s.poll(available());assert(b.writes==writes); }
    { Fake b;State s(b);setup(s);auto before=b.rates;b.failures={2,4};
      assert(!s.configure(custom()));assert(s.hasOwnership());b.failures.clear();
      assert(s.configure({}));assert(b.rates==before && !s.hasOwnership()); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto inactive=available();inactive.focused=false;s.poll(inactive);assert(!s.hasOwnership());
      s.poll(available());assert(s.hasOwnership() && b.rates[0]==1785000000); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto docked=available();docked.docked=true;docked.configuration=42;s.poll(docked);
      assert(b.resets==1 && b.rates[1]==768000000);
      s.configure({});assert(b.rates[1]==768000000); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto external=available();external.manager=Manager::Present;auto writes=b.writes;
      s.poll(external);assert(b.writes==writes && !s.hasOwnership());
      assert(!s.configure(custom()) && b.writes==writes); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      b.rates[0]=1224000000;s.poll(available());assert(b.rates[0]==1224000000 && !s.hasOwnership());
      auto writes=b.writes;s.poll(available());assert(b.writes==writes); }
    { Fake b;State s(b);setup(s);b.readable=false;
      assert(!s.configure(custom()) && b.writes==0); }
    { Fake b;State s(b);setup(s);auto before=b.rates;b.mismatch=true;
      assert(!s.configure(custom()) && b.rates==before && !s.hasOwnership()); }
    { Fake b;State s(b);setup(s);auto disabled=available();disabled.manager=Manager::Inactive;
      s.poll(disabled);assert(s.configure(custom()));
      auto enabled=disabled;enabled.manager=Manager::Present;auto writes=b.writes;
      s.poll(enabled);assert(!s.hasOwnership() && b.writes==writes); }
    { Fake b;State s(b);setup(s);auto cpu=custom();cpu.hz[1]=cpu.hz[2]=0;
      assert(s.configure(cpu) && b.writes==1);assert(s.configure(custom()));
      assert(s.configure({}));assert((b.rates==Rates{1020000000,307200000,1331200000})); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto exit=available();exit.exiting=true;s.poll(exit);assert(!s.hasOwnership()); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto unknown=available();unknown.manager=Manager::Unknown;unknown.focused=false;
      auto writes=b.writes;s.poll(unknown);assert(s.hasOwnership() && b.writes==writes);
      unknown.focused=true;s.poll(unknown);assert(s.hasOwnership() && b.writes==writes);
      b.rates[0]=1020000000;b.rates[1]=307200000;
      s.poll(available());assert(s.hasOwnership() && b.rates[2]==1600000000);
      assert(s.configure({}));assert((b.rates==Rates{1020000000,307200000,1331200000})); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto unknown=available();unknown.manager=Manager::Unknown;auto writes=b.writes;
      s.poll(unknown);assert(s.hasOwnership() && b.writes==writes);
      b.rates[0]=1020000000;b.rates[1]=307200000;
      s.poll(available());assert(s.hasOwnership() && b.rates[2]==1600000000);
      assert(s.configure({}));assert((b.rates==Rates{1020000000,307200000,1331200000})); }
    { Fake b;State s(b);setup(s);assert(s.configure(custom()));
      auto unknown=available();unknown.manager=Manager::Unknown;auto writes=b.writes;
      s.poll(unknown);assert(s.hasOwnership() && b.writes==writes);
      assert(!s.configure({}) && b.writes==writes);
      s.poll(available());assert(!s.hasOwnership());
      assert((b.rates==Rates{1020000000,307200000,1331200000})); }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-clock-control-') as folder:
    folder = Path(folder)
    (folder / 'test.cpp').write_text(test)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra',
                    '-Werror', '-fsanitize=address,undefined', '-I', str(root),
                    str(folder / 'test.cpp'), '-o', str(folder / 'test')], check=True)
    subprocess.run([str(folder / 'test')], check=True)
print('PASS: clock policy/caps, invalid requests, transactions/rollback recovery, System restoration, focus/power transitions, external ownership and read errors')
