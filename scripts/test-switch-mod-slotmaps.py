#!/usr/bin/env python3
"""Exercise the production mod slot-map exports and their emulated pointers."""

from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "lib/N64ModernRuntime"
source = r'''
#include "src/game/recomp_data_api.cpp"

namespace recompui { void message_box(const char*) { std::abort(); } }
namespace ultramodern::error_handling {
void quick_exit(const char*, int, const char*) { std::abort(); }
}
namespace recomp::overlays { void register_base_export(const std::string&, recomp_func_t*) {} }

static size_t allocated_size;
static unsigned frees;
void* recomp::alloc(uint8_t* rdram, size_t size) {
    allocated_size = size;
    return size == 16 ? rdram + 64 : nullptr;
}
void recomp::free(uint8_t* rdram, void* pointer) {
    assert(pointer == rdram + 64);
    ++frees;
}

int main() {
    alignas(4) uint8_t ram[128];
    std::memset(ram, 0xFF, sizeof(ram));

    recomp_context ctx{};
    auto call = [&](recomp_func_t* function, gpr a0 = 0, gpr a1 = 0, gpr a2 = 0) {
        ctx.r4 = a0;
        ctx.r5 = a1;
        ctx.r6 = a2;
        function(ram, &ctx);
        return ctx.r2;
    };

    constexpr gpr base = 0xFFFFFFFF80000000ULL;
    const gpr int_map = call(recomputil_create_u32_slotmap);
    assert(call(recomputil_u32_slotmap_get, int_map, 0, base) == 0);
    assert(ram[0] == 0xFF);
    assert(call(recomputil_u32_slotmap_set, int_map, 0, 123) == 0);
    assert(call(recomputil_u32_slotmap_erase, int_map, 0) == 0);
    const gpr int_key = call(recomputil_u32_slotmap_create, int_map);
    assert(call(recomputil_u32_slotmap_set, int_map, int_key, 456) == 1);
    assert(call(recomputil_u32_slotmap_get, int_map, int_key, base) == 1);
    assert(call(recomputil_u32_slotmap_erase, int_map, int_key) == 1);
    assert(call(recomputil_u32_slotmap_erase, int_map, int_key) == 0);
    call(recomputil_destroy_u32_slotmap, int_map);
    std::memset(ram, 0xFF, sizeof(ram));

    const gpr mem_hashmap = call(recomputil_create_u32_memory_hashmap, 200);
    assert(call(recomputil_u32_memory_hashmap_create, mem_hashmap, 7) == 0);
    assert(call(recomputil_u32_memory_hashmap_size, mem_hashmap) == 0);
    call(recomputil_destroy_u32_memory_hashmap, mem_hashmap);

    const gpr mem_map = call(recomputil_create_memory_slotmap, 16);
    const gpr key = call(recomputil_memory_slotmap_create, mem_map);
    assert(key != 0 && allocated_size == 16);
    assert(std::all_of(ram + 64, ram + 80, [](uint8_t value) { return value == 0; }));
    assert(ram[63] == 0xFF && ram[80] == 0xFF);
    call(recomputil_memory_slotmap_get, mem_map, key, base);
    uint32_t address;
    std::memcpy(&address, ram, sizeof(address));
    assert(address == uint32_t(base + 64));
    assert(call(recomputil_memory_slotmap_erase, mem_map, key) == 1);
    assert(call(recomputil_memory_slotmap_erase, mem_map, key) == 0 && frees == 1);
    call(recomputil_memory_slotmap_create, mem_map);
    call(recomputil_destroy_memory_slotmap, mem_map);
    assert(frees == 2);

    const gpr oversized = call(recomputil_create_memory_slotmap, 200);
    assert(call(recomputil_memory_slotmap_create, oversized) == 0);
    assert(call(recomputil_memory_slotmap_size, oversized) == 0);
    call(recomputil_destroy_memory_slotmap, oversized);
}
'''
with tempfile.TemporaryDirectory(prefix="sk2-mod-slotmaps-") as directory:
    folder = Path(directory)
    (folder / "recompui").mkdir()
    (folder / "recompui/recompui.h").write_text("namespace recompui { void message_box(const char*); }\n")
    (folder / "test.cpp").write_text(source)
    includes = [
        folder, ROOT, ROOT / "include", ROOT / "lib/RecompFrontend/lib/SlotMap",
        RUNTIME / "librecomp/include", RUNTIME / "ultramodern/include",
        RUNTIME / "N64Recomp/include",
    ]
    subprocess.run(
        [os.environ.get("CXX", "c++"), "-std=c++20", "-fsanitize=address,undefined",
         *[f"-I{path}" for path in includes], str(folder / "test.cpp"), "-o", str(folder / "test")],
        check=True,
    )
    subprocess.run([str(folder / "test")], check=True)
print("PASS: slot-map miss, allocation size, emulated pointer, erase and destroy")
