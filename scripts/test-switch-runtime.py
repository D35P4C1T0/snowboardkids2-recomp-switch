#!/usr/bin/env python3
"""Exercise the patched save worker and ROM importer with synthetic files."""

from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "build/switch/deps/N64ModernRuntime/librecomp"
pi = (RUNTIME / "src/pi.cpp").read_text()
recomp = (RUNTIME / "src/recomp.cpp").read_text()

source = r'''
#include <cassert>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <sys/resource.h>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "librecomp/files.hpp"

#define RDRAM_ARG1 uint8_t*
#define RDRAM_ARG uint8_t* rdram,
#define PASS_RDRAM nullptr
#define PTR(type) uint32_t
#define MEM_B(index, address) rdram[(index) + (address)]
using gpr = uint64_t;

namespace moodycamel {
struct LightweightSemaphore {
    std::mutex mutex;
    std::condition_variable changed;
    unsigned count = 0;
    void signal() {
        std::lock_guard lock(mutex);
        ++count;
        changed.notify_one();
    }
    bool wait(int64_t timeout) {
        std::unique_lock lock(mutex);
        if (!changed.wait_for(lock, std::chrono::microseconds(timeout), [&]{return count > 0;})) return false;
        --count;
        return true;
    }
};
}
namespace recomp {
    enum class SaveType { AllowAll, Flashram, Sram, Eep16k, Eep4k, None };
    SaveType get_save_type() { return SaveType::Eep4k; }
    std::u8string current_game_id() { return u8"game"; }
    enum class RomValidationError { Good, FailedToOpen, NotARom, IncorrectRom, NotYet, IncorrectVersion, OtherError };
    struct GameEntry {
        std::string_view internal_name = "SNOWBOARD KIDS2";
        uint64_t rom_hash = 1;
        std::u8string stored_filename() const { return u8"stored.rom"; }
    };
    RomValidationError select_rom(const std::filesystem::path&, std::u8string&);
    void set_rom_contents(std::vector<uint8_t>&&) {}
    bool is_rom_valid(std::u8string&);
    void check_all_stored_roms();
    bool load_stored_rom(std::u8string&);
}
std::unordered_map<std::u8string, recomp::GameEntry> game_roms{{u8"game", {}}};
std::filesystem::path config_path = ".";
unsigned reported_errors = 0;
namespace ultramodern {
    std::filesystem::path get_save_file_path();
    void change_save_file(const std::u8string&, const std::u8string&);
    void join_saving_thread();
    void init_saving(RDRAM_ARG1);
    namespace error_handling { void message_box(const char*) { ++reported_errors; } }
}
bool check_hash(const std::vector<uint8_t>& rom, uint64_t) {
    return rom.size() == 64;
}
'''
source += pi[pi.index("struct {"):pi.index("void do_dma(")]
source += recomp[recomp.index("static std::vector<uint8_t> read_file("):recomp.index("const recomp::Version& recomp::get_project_version")]
source += recomp[recomp.index("const std::array<uint8_t, 4> first_rom_bytes"):recomp.index('extern "C" void osGetMemSize_recomp')]
source += r'''
void write(const std::filesystem::path& path, std::string_view value) {
    std::ofstream(path, std::ios::binary).write(value.data(), value.size());
}
int main() {
    std::filesystem::create_directory("saves");
    write("saves/game.bin", std::string(512, 'o'));
    set_save_file_path(u8"", u8"game");
    save_context.save_buffer.resize(512, 'n');
    save_context.dirty = true;

    // A short write leaves the old primary intact.
    std::signal(SIGXFSZ, SIG_IGN);
    rlimit original{};
    assert(getrlimit(RLIMIT_FSIZE, &original) == 0);
    rlimit limit{64, original.rlim_max};
    assert(setrlimit(RLIMIT_FSIZE, &limit) == 0);
    update_save_file();
    assert(reported_errors == 1 && save_context.dirty);
    assert(std::filesystem::file_size("saves/game.bin") == 512);
    assert(!std::filesystem::exists("saves/game.bin.bak"));
    assert(setrlimit(RLIMIT_FSIZE, &original) == 0);

    // Recover a previously truncated primary and retain the backup on the next save.
    write("saves/game.bin", "short");
    write("saves/game.bin.bak", std::string(512, 'b'));
    read_save_file();
    assert(save_context.save_buffer == std::vector<char>(512, 'b'));
    update_save_file();
    assert(std::ifstream("saves/game.bin").get() == 'b');
    assert(std::filesystem::file_size("saves/game.bin.bak") == 512);

    // Quit before the worker has consumed the last write.
    const char progress = 'p';
    save_write_ptr(&progress, 0, 1);
    {
        std::lock_guard lock(save_context.save_buffer_mutex);
        save_context.stopping = true;
    }
    saving_thread_func(nullptr);
    assert(std::ifstream("saves/game.bin").get() == 'p');

    std::u8string game_id = u8"game";
    const std::string header("\x80\x37\x12\x40", 4);
    write("dump.z64", header);
    assert(recomp::select_rom("dump.z64", game_id) == recomp::RomValidationError::NotARom);
    write("dump.z64", header + std::string(60, '\0'));
    std::filesystem::create_directory("stored.rom");
    assert(recomp::select_rom("dump.z64", game_id) == recomp::RomValidationError::OtherError);
    assert(!recomp::is_rom_valid(game_id));
    std::filesystem::remove("stored.rom");
    assert(recomp::select_rom("dump.z64", game_id) == recomp::RomValidationError::Good);
    assert(recomp::is_rom_valid(game_id));
    std::filesystem::remove("stored.rom");
    assert(!recomp::load_stored_rom(game_id));
    assert(!recomp::is_rom_valid(game_id));
}
'''
with tempfile.TemporaryDirectory(prefix="sk2-runtime-") as directory:
    folder = Path(directory)
    (folder / "test.cpp").write_text(source)
    subprocess.run(
        [os.environ.get("CXX", "c++"), "-std=c++20", "-D__SWITCH__", "-pthread",
         "-fsanitize=address,undefined", "-I", str(RUNTIME / "include"),
         "-I", str(RUNTIME / "include/librecomp"), str(folder / "test.cpp"),
         str(RUNTIME / "src/files.cpp"), "-o", str(folder / "test")],
        check=True,
    )
    subprocess.run([str(folder / "test")], cwd=folder, check=True)
print("PASS: short save write, backup recovery, shutdown flush, truncated ROM and failed ROM import")
