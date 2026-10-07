#!/usr/bin/env python3
"""Execute production encoded-copy binding and resource retirement paths."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parent.parent
source=(root/'build-switch-deps/rt64/src/render/rt64_render_target.cpp').read_text()
def method(signature):
    start=source.index(signature)
    return source[start:source.index('\n    }',start)+6].replace('RenderTarget::','')
encode=method('    bool RenderTarget::encodeColorToNativeBytes')
release=method('    void RenderTarget::releaseTextures')
cb=(root/'build-switch-deps/rt64/src/shared/rt64_switch_framebuffer_copy.h').read_text()
cb=cb[cb.index('    struct SwitchFramebufferColorCopyCB'):cb.index('#ifdef HLSL_CPU', cb.index('    struct SwitchFramebufferColorCopyCB'))]
stub=r'''
#include <cassert>
#include <cstdint>
#include <memory>
using uint=uint32_t;
namespace interop {
'''+cb+r'''
}
struct RenderTexture { int id; };
struct RenderTextureView { int id; };
struct RenderTargetCopyDescriptorSet {
    static constexpr unsigned gInput=0;
    RenderTexture* texture=nullptr; RenderTextureView* view=nullptr;
    explicit RenderTargetCopyDescriptorSet(void*) {}
    RenderTargetCopyDescriptorSet* get() { return this; }
    void setTexture(unsigned,RenderTexture* t,int,RenderTextureView* v) { texture=t; view=v; }
};
struct RenderTextureLayout { static constexpr int SHADER_READ=1,COLOR_WRITE=2; };
struct RenderTextureBarrier {
    RenderTexture* texture; int layout;
    RenderTextureBarrier(RenderTexture* t,int l):texture(t),layout(l) {}
};
struct RenderBarrierStage { static constexpr int GRAPHICS=1; };
struct RenderViewport { RenderViewport(float,float,float,float) {} };
struct RenderRect { RenderRect(unsigned,unsigned,unsigned,unsigned) {} };
struct ShaderRecord { std::unique_ptr<int> pipeline,pipelineLayout; explicit ShaderRecord(int id):pipeline(new int(id)),pipelineLayout(new int(id+100)) {} };
struct ShaderLibrary {
    ShaderRecord switchFramebufferColorCopy{11},switchFramebufferPackedCopy{12},switchFramebufferDepthMSCopy{13};
};
struct CommandList {
    RenderTargetCopyDescriptorSet* descriptor=nullptr;
    int pipeline=0,layout=0,draws=0;
    interop::SwitchFramebufferColorCopyCB constants{};
    void barriers(int,const RenderTextureBarrier* barriers,unsigned count) {
        assert(count==2 && barriers[0].layout==RenderTextureLayout::COLOR_WRITE && barriers[1].layout==RenderTextureLayout::SHADER_READ);
    }
    void setFramebuffer(int*) {}
    void setViewports(RenderViewport) {} void setScissors(RenderRect) {}
    void setPipeline(int* p) { pipeline=*p; }
    void setGraphicsPipelineLayout(int* p) { layout=*p; }
    void setGraphicsDescriptorSet(RenderTargetCopyDescriptorSet* d,unsigned) { descriptor=d; }
    void setGraphicsPushConstants(unsigned,const interop::SwitchFramebufferColorCopyCB* cb) { constants=*cb; }
    void setVertexBuffers(unsigned,void*,unsigned,void*) {}
    void drawInstanced(unsigned vertices,unsigned instances,unsigned,unsigned) { assert(vertices==3 && instances==1); draws++; }
};
struct RenderWorker { void* device=nullptr; CommandList* commandList; };
enum class RenderFormat { R8G8_UNORM,R8G8B8A8_UNORM,D32_FLOAT,UNKNOWN };
struct RenderTarget {
    unsigned width=320,height=240;
    bool usesHDR=false,marked=false;
    RenderFormat format=RenderFormat::R8G8B8A8_UNORM;
    struct { unsigned sampleCount=1; } multisampling;
    std::unique_ptr<RenderTexture> texture, resolvedTexture, downsampledTexture, dummyTexture;
    std::unique_ptr<RenderTextureView> textureView, resolvedTextureView;
    std::unique_ptr<int> textureFramebuffer,resolveFramebuffer,textureCopyDescSet,textureResolveDescSet,filterDescSet,fbWriteDescSet;
    std::unique_ptr<RenderTargetCopyDescriptorSet> targetCopyDescSet,switchNativeCopyDescSet;
    unsigned resolved=0;
    void setupColorFramebuffer(RenderWorker*) { if(!textureFramebuffer) textureFramebuffer=std::make_unique<int>(1); }
    void resolveTarget(RenderWorker*,const ShaderLibrary*) { if(multisampling.sampleCount>1) { assert(format!=RenderFormat::D32_FLOAT); resolved++; } }
    RenderTexture* getResolvedTexture() { return multisampling.sampleCount>1?resolvedTexture.get():texture.get(); }
    RenderTextureView* getResolvedTextureView() { return multisampling.sampleCount>1?resolvedTextureView.get():textureView.get(); }
    void markForResolve() { marked=true; }
'''+encode+release+r'''
};
int main() {
    ShaderLibrary shaders; CommandList list; RenderWorker worker{nullptr,&list};
    for(bool packed:{false,true}) for(bool depth:{false,true}) for(unsigned samples:{1,2,4,8}) {
        RenderTarget input,output;
        input.format=depth?RenderFormat::D32_FLOAT:RenderFormat::R8G8B8A8_UNORM;
        input.multisampling.sampleCount=samples;
        input.texture=std::make_unique<RenderTexture>(RenderTexture{1}); input.textureView=std::make_unique<RenderTextureView>(RenderTextureView{1});
        if(!depth && samples>1) {
            input.resolvedTexture=std::make_unique<RenderTexture>(RenderTexture{2});
            input.resolvedTextureView=std::make_unique<RenderTextureView>(RenderTextureView{2});
        }
        input.targetCopyDescSet=std::make_unique<RenderTargetCopyDescriptorSet>(nullptr);
        input.targetCopyDescSet->setTexture(0,input.texture.get(),1,input.textureView.get());
        output.format=packed?RenderFormat::R8G8_UNORM:RenderFormat::R8G8B8A8_UNORM;
        output.texture=std::make_unique<RenderTexture>(RenderTexture{3});
        assert(output.encodeColorToNativeBytes(&worker,&input,285,7,52,2,123,&shaders));
        assert(input.resolved==unsigned(!depth && samples>1));
        int expectedTexture=(!depth && samples>1)?2:1;
        assert(list.descriptor==input.switchNativeCopyDescSet.get());
        assert(list.descriptor->texture->id==expectedTexture && list.descriptor->view->id==expectedTexture);
        assert(input.targetCopyDescSet->texture->id==1); // raw MSAA copy binding untouched
        assert(list.pipeline==((depth && samples>1)?13:packed?12:11));
        assert(list.layout==111 && list.constants.sampleCount==samples && list.constants.depth==unsigned(depth));
        assert(list.constants.rowWidth==285 && list.constants.ditherRandomSeed==123 && output.marked);
        auto descriptors=input.switchNativeCopyDescSet.get();
        assert(output.encodeColorToNativeBytes(&worker,&input,285,7,52,3,1,&shaders));
        assert(input.switchNativeCopyDescSet.get()==descriptors); // reuse safe
        input.releaseTextures();
        assert(!input.switchNativeCopyDescSet && !input.targetCopyDescSet && !input.texture && !input.resolvedTexture);
    }
    RenderTarget input,output;
    output.format=RenderFormat::UNKNOWN;
    assert(!output.encodeColorToNativeBytes(&worker,&input,320,0,240,3,0,&shaders));
    output.format=RenderFormat::R8G8_UNORM;
    assert(!output.encodeColorToNativeBytes(&worker,&input,321,0,240,3,0,&shaders));
    assert(!output.encodeColorToNativeBytes(&worker,&input,320,7,7,3,0,&shaders));
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-msaa-copyback-') as temp:
    path=Path(temp)/'test.cpp';exe=Path(temp)/'test';path.write_text(stub)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-D__SWITCH__','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-fno-omit-frame-pointer',str(path),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production MSAA copyback, resolved color/raw depth binding, pipeline/count selection, separate descriptors and retirement; ASan/UBSan')
