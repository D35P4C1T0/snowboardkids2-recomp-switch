#!/usr/bin/env python3
"""Execute production graphics mapping and live updates with real config types."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parent.parent
src=root/'build-switch-deps'
frontend=(src/'RecompFrontend/recompui/src/renderer/rt64_render_context.cpp').read_text()
user=(src/'rt64/src/common/rt64_user_configuration.cpp').read_text()
conversions=frontend[frontend.index('RT64::UserConfiguration::AspectRatio to_rt64'):frontend.index('RT64::EnhancementConfiguration::Presentation::Mode to_rt64')]
mapping=frontend[frontend.index('void set_application_user_config'):frontend.index('ultramodern::renderer::SetupResult map_setup_result')]
def method(signature):
    start=frontend.index(signature)
    return frontend[start:frontend.index('\n}',start)+2].replace('renderer::RT64Context::','Context::')
constructor=user[user.index('    const int UserConfiguration::ResolutionMultiplierLimit'):user.index('    void UserConfiguration::validate')]
counts=user[user.index('    uint32_t UserConfiguration::msaaSampleCount()'):user.index('    bool UserConfiguration::isGraphicsAPISupported')]
stub=r'''
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include "ultramodern/config.hpp"
#include "common/rt64_user_configuration.h"
namespace RT64 {
struct Application {
    UserConfiguration userConfig;
    struct Shared { unsigned swapChainHeight=720; } shared;
    Shared* sharedQueueResources=&shared;
    int changed=0, discarded=0, multisampling=0, fullscreen=0;
    void updateUserConfig(bool discard) { changed++; discarded+=discard; }
    void updateMultisampling() { multisampling++; changed++; discarded++; }
    void setFullScreen(bool) { fullscreen++; }
};
}
std::vector<std::string> messages;
void switch_log_checkpoint(const char* message,bool) { messages.emplace_back(message); }
struct Context {
    std::unique_ptr<RT64::Application> app=std::make_unique<RT64::Application>();
    bool update_config(const ultramodern::renderer::GraphicsConfig&,const ultramodern::renderer::GraphicsConfig&);
    float get_resolution_scale() const;
};
'''
test=r'''
int main() {
    namespace R=ultramodern::renderer;
    using U=RT64::UserConfiguration;
    for(auto resolution:{R::Resolution::Original,R::Resolution::Original2x,R::Resolution::Auto})
    for(int downsample:{0,2,4}) for(auto aa:{R::Antialiasing::None,R::Antialiasing::MSAA2X,R::Antialiasing::MSAA4X}) {
        Context context; R::GraphicsConfig config{};
        config.res_option=resolution; config.ds_option=downsample; config.msaa_option=aa;
        config.ar_option=R::AspectRatio::Expand; config.hr_option=R::HUDRatioMode::Clamp16x9;
        config.rr_option=R::RefreshRate::Manual; config.rr_manual_value=60;
        set_application_user_config(context.app.get(),config);
        auto& applied=context.app->userConfig;
        unsigned samples=aa==R::Antialiasing::None?1:aa==R::Antialiasing::MSAA2X?2:4;
        assert(applied.msaaSampleCount()==samples);
        float base=resolution==R::Resolution::Original?1:resolution==R::Resolution::Original2x?2:3;
        unsigned ds=resolution==R::Resolution::Auto?1:std::max(downsample,1);
        assert(applied.downsampleMultiplier==int(ds));
        assert(context.get_resolution_scale()==base*ds);
        assert(applied.resolution==(resolution==R::Resolution::Auto?U::Resolution::WindowIntegerScale:U::Resolution::Manual));
        assert(applied.aspectRatio==U::AspectRatio::Expand && applied.extAspectTarget==16.0/9.0);
        assert(applied.refreshRateTarget==60 && applied.displayBuffering==U::DisplayBuffering::Double);
        // No-op changes do not rebuild. Resolution/DS/MSAA changes discard
        // old images, but only sample-count changes recreate MSAA resources.
        assert(!context.update_config(config,config));
        assert(context.app->changed==0);
        R::GraphicsConfig next=config; next.res_option=resolution==R::Resolution::Auto?R::Resolution::Original:R::Resolution::Auto;
        assert(context.update_config(config,next));
        assert(context.app->changed==1 && context.app->discarded==1 && context.app->multisampling==0);
        auto previous=next; next.msaa_option=aa==R::Antialiasing::None?R::Antialiasing::MSAA4X:R::Antialiasing::None;
        assert(context.update_config(previous,next));
        assert(context.app->changed==2 && context.app->discarded==2 && context.app->multisampling==1);
        previous=next; next.ds_option=next.ds_option==4?2:4;
        assert(context.update_config(previous,next));
        assert(context.app->discarded==3 && context.app->multisampling==1);
        previous=next; next.rr_manual_value=30;
        assert(context.update_config(previous,next));
        assert(context.app->changed==4 && context.app->discarded==3);
    }
    assert(!messages.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-graphics-settings-') as temp:
    path=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    path.write_text(stub+'namespace RT64 {\n'+constructor+counts+'}\n'+conversions+mapping+
                    method('bool renderer::RT64Context::update_config')+'\n'+method('float renderer::RT64Context::get_resolution_scale')+test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++20','-D__SWITCH__','-Wall','-Wextra','-Werror','-Wno-return-type',
                    '-I',str(src/'rt64/src'),'-I',str(root/'lib/rt64/src/contrib'),
                    '-I',str(src/'N64ModernRuntime/ultramodern/include'),str(path),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: real config types, production mapping/live updates, all 27 resolution/downsampling/MSAA combinations, invalidation and rebuild rules')
