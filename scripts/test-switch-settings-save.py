#!/usr/bin/env python3
"""Exercise production SD replacement and JSON persistence under Horizon semantics."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
runtime = root / 'build-switch-deps/N64ModernRuntime'
files = (runtime / 'librecomp/src/files.cpp').read_text().replace('#include "files.hpp"', '#include "librecomp/files.hpp"').replace('std::filesystem::rename(', 'horizonRename(')
config = (runtime / 'librecomp/src/config.cpp').read_text()
json_methods = config[config.index('static bool read_json('):config.index('static std::filesystem::path get_path_to_config(')]
source = r'''
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include "json/json.hpp"
bool failInstall=false,failBackup=false;
void horizonRename(const std::filesystem::path& from,const std::filesystem::path& to,std::error_code& ec) {
    if (std::filesystem::exists(to)) { ec=std::make_error_code(std::errc::file_exists);return; }
    if ((failInstall && from.extension()==".temp") || (failBackup && to.extension()==".bak")) {
        ec=std::make_error_code(std::errc::io_error);return;
    }
    std::filesystem::rename(from,to,ec);
}
''' + files + json_methods + r'''
int main() {
    using nlohmann::json;
    json actual;
    const json first={{"control","system"}},second={{"control","custom"},{"cpu","1326000000"}},third={{"control","custom"},{"memory","1600000000"}};
    assert(save_json_with_backups("settings.json",first));
    assert(save_json_with_backups("settings.json",second));
    assert(save_json_with_backups("settings.json",third));
    assert(read_json_with_backups("settings.json",actual) && actual==third);
    assert(read_json(recomp::open_input_backup_file("settings.json"),actual) && actual==second);
    failInstall=true;
    assert(!save_json_with_backups("settings.json",first));
    assert(read_json_with_backups("settings.json",actual) && actual==third);
    failInstall=false;assert(save_json_with_backups("settings.json",second));
    failBackup=true;assert(!save_json_with_backups("settings.json",first));
    assert(read_json_with_backups("settings.json",actual) && actual==second);
    failBackup=false;
    // Simulate termination after the old base was promoted to its backup.
    std::filesystem::remove("settings.json.bak");
    std::filesystem::rename("settings.json","settings.json.bak");
    assert(read_json_with_backups("settings.json",actual) && actual==second);
    assert(save_json_with_backups("settings.json",third));
    assert(read_json_with_backups("settings.json",actual) && actual==third);
    assert(!std::filesystem::exists("settings.json.temp"));
    // The same production helper protects binary game saves.
    { auto out=recomp::open_output_file_with_backup("game.bin");out<<"old"; }
    assert(recomp::finalize_output_file_with_backup("game.bin"));
    { auto out=recomp::open_output_file_with_backup("game.bin");out<<"new"; }
    failInstall=true;assert(!recomp::finalize_output_file_with_backup("game.bin"));
    std::string value;recomp::open_input_file_with_backup("game.bin")>>value;assert(value=="old");
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-settings-save-') as folder:
    folder = Path(folder)
    (folder / 'test.cpp').write_text(source)
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++20', '-D__SWITCH__',
                    '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(runtime / 'librecomp/include'), '-I', str(runtime / 'thirdparty'),
                    str(folder / 'test.cpp'), '-o', str(folder / 'test')], check=True)
    subprocess.run([str(folder / 'test')], cwd=folder, check=True)
print('PASS: production repeated JSON saves, verified readback, Horizon replacement/rollback, interrupted-save recovery and binary-save preservation')
