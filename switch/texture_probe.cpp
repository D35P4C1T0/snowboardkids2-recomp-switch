#include <algorithm>
#include <cstdio>
#include <cstring>
#include <vector>
#include <switch.h>

#include "plume_render_interface.h"
#include "plume_render_interface_builders.h"
#include "shaders/FullScreenVS.hlsl.spirv.h"
#include "shaders/TextureCopyPS.hlsl.spirv.h"

void switch_log_checkpoint(const char*, bool);

namespace {
using namespace plume;

bool test_sampling(RenderDevice* device, uint32_t width, uint32_t height) {
    const auto format = RenderFormat::R8G8B8A8_UNORM;
    const uint32_t row_pitch = (width * 4 + 255U) & ~255U;
    const uint32_t bytes = row_pitch * height;
    std::vector<uint8_t> expected(bytes, 0xCD);
    for (uint32_t y = 0; y < height; y++) {
        for (uint32_t x = 0; x < width * 4; x++) {
            expected[y * row_pitch + x] = uint8_t(x * 17U + y * 131U + (x >> 3));
        }
    }
    auto queue = device->createCommandQueue(RenderCommandListType::DIRECT);
    if (!queue) return false;
    auto list = queue->createCommandList();
    auto fence = device->createCommandFence();
    auto upload = device->createBuffer(RenderBufferDesc::UploadBuffer(bytes));
    auto readback = device->createBuffer(RenderBufferDesc::ReadbackBuffer(bytes));
    auto input = device->createTexture(RenderTextureDesc::Texture2D(width, height, 1, format));
    auto target = device->createTexture(RenderTextureDesc::ColorTarget(width, height, format));
    const RenderTexture* attachment = target.get();
    auto framebuffer = device->createFramebuffer(RenderFramebufferDesc(&attachment, 1));
    auto vertex = device->createShader(FullScreenVSBlobSPIRV, sizeof(FullScreenVSBlobSPIRV), "VSMain", RenderShaderFormat::SPIRV);
    auto pixel = device->createShader(TextureCopyPSBlobSPIRV, sizeof(TextureCopyPSBlobSPIRV), "PSMain", RenderShaderFormat::SPIRV);
    RenderDescriptorSetBuilder descriptors;
    descriptors.begin();
    const uint32_t input_index = descriptors.addTexture(1);
    descriptors.end();
    auto descriptor_set = descriptors.create(device);
    RenderPipelineLayoutBuilder layout_builder;
    layout_builder.begin();
    layout_builder.addPushConstant(0, 0, sizeof(float) * 4, RenderShaderStageFlag::PIXEL);
    layout_builder.addDescriptorSet(descriptors);
    layout_builder.end();
    auto layout = layout_builder.create(device);
    RenderGraphicsPipelineDesc pipeline_desc;
    pipeline_desc.pipelineLayout = layout.get();
    pipeline_desc.vertexShader = vertex.get();
    pipeline_desc.pixelShader = pixel.get();
    pipeline_desc.renderTargetCount = 1;
    pipeline_desc.renderTargetFormat[0] = format;
    pipeline_desc.renderTargetBlend[0] = RenderBlendDesc::Copy();
    auto pipeline = device->createGraphicsPipeline(pipeline_desc);
    if (!list || !fence || !upload || !readback || !input || !target || !framebuffer || !descriptor_set || !layout || !pipeline) {
        switch_log_checkpoint("sampling probe: resource creation FAILED", false);
        return false;
    }
    void* data = upload->map();
    if (!data) return false;
    std::memcpy(data, expected.data(), bytes);
    upload->unmap();
    data = readback->map();
    if (!data) return false;
    std::memset(data, 0xA5, bytes);
    armDCacheFlush(data, bytes);
    const RenderRange no_writes(0, 0);
    readback->unmap(0, &no_writes);
    auto submit = [&](const char* phase) {
        char message[160];
        std::snprintf(message, sizeof(message), "sampling probe: submitting %s %ux%u", phase, width, height);
        switch_log_checkpoint(message, false);
        list->end();
        queue->executeCommandLists(list.get(), fence.get());
        queue->waitForCommandFence(fence.get());
    };
    list->begin();
    list->barriers(RenderBarrierStage::COPY, RenderTextureBarrier(input.get(), RenderTextureLayout::COPY_DEST));
    list->copyTextureRegion(RenderTextureCopyLocation::Subresource(input.get()),
        RenderTextureCopyLocation::PlacedFootprint(upload.get(), format, width, height, 1, row_pitch / 4));
    list->barriers(RenderBarrierStage::GRAPHICS, RenderTextureBarrier(input.get(), RenderTextureLayout::SHADER_READ));
    submit("upload");
    descriptor_set->setTexture(input_index, input.get(), RenderTextureLayout::SHADER_READ);
    list->begin();
    list->barriers(RenderBarrierStage::GRAPHICS, RenderTextureBarrier(target.get(), RenderTextureLayout::COLOR_WRITE));
    list->setFramebuffer(framebuffer.get());
    list->setPipeline(pipeline.get());
    list->setGraphicsPipelineLayout(layout.get());
    list->setViewports(RenderViewport(0, 0, float(width), float(height)));
    list->setScissors(RenderRect(0, 0, width, height));
    list->setGraphicsDescriptorSet(descriptor_set.get(), 0);
    const float constants[] = {0, 0, float(width), float(height)};
    list->setGraphicsPushConstants(0, constants);
    list->drawInstanced(3, 1, 0, 0);
    submit("texture draw");
    list->begin();
    list->barriers(RenderBarrierStage::COPY, RenderTextureBarrier(target.get(), RenderTextureLayout::COPY_SOURCE));
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::WRITE));
    list->copyTextureRegion(RenderTextureCopyLocation::PlacedFootprint(readback.get(), format, width, height, 1, row_pitch / 4),
        RenderTextureCopyLocation::Subresource(target.get()));
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::READ));
    submit("rendered readback");
    const RenderRange range(0, bytes);
    auto* actual = static_cast<uint8_t*>(readback->map(0, &range));
    if (!actual) return false;
    armDCacheFlush(actual, bytes);
    size_t mismatches = 0, first = 0;
    for (uint32_t y = 0; y < height; y++) {
        for (uint32_t x = 0; x < width * 4; x++) {
            const size_t offset = size_t(y) * row_pitch + x;
            if (actual[offset] != expected[offset]) {
                if (!mismatches) first = offset;
                mismatches++;
            }
        }
    }
    char message[256];
    std::snprintf(message, sizeof(message), "sampling probe: rendered %ux%u %s mismatches=%zu first=%zu expected=%02x actual=%02x",
        width, height, mismatches ? "FAIL" : "PASS", mismatches, first, expected[first], actual[first]);
    switch_log_checkpoint(message, false);
    readback->unmap(0, &no_writes);
    return mismatches == 0;
}

bool test_transfer(RenderDevice* device, RenderCommandQueue* queue,
    uint32_t width, uint32_t height, RenderFormat format, bool dedicated, bool staged, bool fenced) {
    const uint32_t texel_bytes = RenderFormatSize(format);
    const uint32_t row_bytes = width * texel_bytes;
    const uint32_t row_pitch = (row_bytes + 255U) & ~255U;
    const uint32_t byte_count = row_pitch * height;
    std::vector<uint8_t> expected(byte_count, 0xCD);
    for (uint32_t y = 0; y < height; y++) {
        for (uint32_t x = 0; x < row_bytes; x++) {
            // Every channel, including alpha, varies across rows and columns.
            expected[y * row_pitch + x] = uint8_t(x * 17U + y * 131U + (x >> 3));
        }
    }

    auto upload_desc = RenderBufferDesc::UploadBuffer(byte_count);
    upload_desc.committed = dedicated;
    auto upload = device->createBuffer(upload_desc);
    auto staging_desc = RenderBufferDesc::DefaultBuffer(byte_count);
    staging_desc.committed = dedicated;
    auto staging = device->createBuffer(staging_desc);
    auto image_desc = RenderTextureDesc::Texture2D(width, height, 1, format);
    image_desc.committed = dedicated;
    auto texture = device->createTexture(image_desc);

    // Isolate readback cache lines from every other allocation. Initialize and
    // flush BEFORE the GPU writes, and never dirty these lines afterwards.
    auto readback_desc = RenderBufferDesc::ReadbackBuffer(byte_count);
    readback_desc.committed = true;
    auto readback = device->createBuffer(readback_desc);
    auto list = queue->createCommandList();
    auto fence = device->createCommandFence();
    if (!upload || !staging || !texture || !readback || !list || !fence) {
        switch_log_checkpoint("transfer probe: resource creation FAILED", false);
        return false;
    }

    auto* upload_data = static_cast<uint8_t*>(upload->map());
    if (!upload_data) return false;
    std::memcpy(upload_data, expected.data(), byte_count);
    upload->unmap();

    auto prepare_readback = [&]() {
        void* data = readback->map();
        if (!data) return false;
        std::memset(data, 0xA5, byte_count);
        armDCacheFlush(data, byte_count);
        readback->unmap();
        return true;
    };
    auto submit = [&](const char* boundary) {
        char message[256];
        std::snprintf(message, sizeof(message),
            "transfer probe: submitting %s %ux%u bpp=%u dedicated=%u staged=%u fenced=%u",
            boundary, width, height, texel_bytes, dedicated, staged, fenced);
        switch_log_checkpoint(message, false);
        list->end();
        queue->executeCommandLists(list.get(), fence.get());
        queue->waitForCommandFence(fence.get());
    };
    auto verify = [&](const char* boundary, bool include_padding) {
        const RenderRange range(0, byte_count);
        auto* data = static_cast<uint8_t*>(readback->map(0, &range));
        if (!data) return false;
        // libnx's EL0-safe clean+invalidate; no privileged SVC or DC IVAC.
        // The dedicated allocation was flushed before submission, so there
        // are no dirty CPU bytes to overwrite the completed GPU result.
        armDCacheFlush(data, byte_count);
        size_t mismatches = 0, first = 0;
        for (uint32_t y = 0; y < height; y++) {
            for (uint32_t x = 0; x < (include_padding ? row_pitch : row_bytes); x++) {
                const size_t offset = size_t(y) * row_pitch + x;
                if (data[offset] != expected[offset]) {
                    if (mismatches == 0) first = offset;
                    mismatches++;
                }
            }
        }
        char message[384];
        std::snprintf(message, sizeof(message),
            "transfer probe: %s %ux%u bpp=%u dedicated=%u staged=%u fenced=%u %s mismatches=%zu first=%zu expected=%02x actual=%02x",
            boundary, width, height, texel_bytes, dedicated, staged, fenced,
            mismatches ? "FAIL" : "PASS", mismatches, first, expected[first], data[first]);
        switch_log_checkpoint(message, false);
        const RenderRange no_writes(0, 0);
        readback->unmap(0, &no_writes);
        return mismatches == 0;
    };

    if (!prepare_readback()) return false;
    list->begin();
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::WRITE));
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(staging.get(), RenderBufferAccess::WRITE));
    list->copyBufferRegion(staging.get(), upload.get(), byte_count);
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(staging.get(), RenderBufferAccess::READ));
    list->copyBufferRegion(readback.get(), staging.get(), byte_count);
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::READ));
    submit("buffer round trip");
    bool passed = verify("buffer", true);

    if (!prepare_readback()) return false;
    list->begin();
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::WRITE));
    list->barriers(RenderBarrierStage::COPY, RenderTextureBarrier(texture.get(), RenderTextureLayout::COPY_DEST));
    list->copyTextureRegion(RenderTextureCopyLocation::Subresource(texture.get()),
        RenderTextureCopyLocation::PlacedFootprint(staged ? staging.get() : upload.get(),
            format, width, height, 1, row_pitch / texel_bytes));
    list->barriers(RenderBarrierStage::COPY, RenderTextureBarrier(texture.get(), RenderTextureLayout::COPY_SOURCE));
    if (fenced) {
        submit("image upload");
        list->begin();
    }
    list->copyTextureRegion(RenderTextureCopyLocation::PlacedFootprint(readback.get(),
            format, width, height, 1, row_pitch / texel_bytes),
        RenderTextureCopyLocation::Subresource(texture.get()));
    list->barriers(RenderBarrierStage::COPY, RenderBufferBarrier(readback.get(), RenderBufferAccess::READ));
    submit("image readback");
    return verify("image", false) && passed;
}
}

bool switch_run_texture_probe(plume::RenderDevice* device, bool include_inline) {
    switch_log_checkpoint(include_inline
        ? "transfer probe: testing inline and separately fenced image readback"
        : "transfer probe: testing separately fenced image readback (inline requires --inline-transfers)", false);
    auto queue = device->createCommandQueue(plume::RenderCommandListType::COPY);
    if (!queue) return false;
    bool passed = true;
    // Exercise the game's separately fenced staging path before inline copies.
    // A fault in the first inline case used to prevent reaching ANY staged or
    // separately fenced case, hiding the most relevant comparison.
    for (bool fenced : {true, false}) {
        if (!fenced && !include_inline) continue;
        for (bool dedicated : {true, false}) {
            for (bool staged : {true, false}) {
                for (const auto& dimensions : {std::pair{1U, 1U}, std::pair{4U, 2U},
                    std::pair{8U, 4U}, std::pair{16U, 8U}, std::pair{16U, 16U},
                    std::pair{285U, 52U}, std::pair{128U, 256U}}) {
                    passed = test_transfer(device, queue.get(), dimensions.first, dimensions.second,
                        plume::RenderFormat::R8G8B8A8_UNORM, dedicated, staged, fenced) && passed;
                }
                passed = test_transfer(device, queue.get(), 4096, 1,
                    plume::RenderFormat::R8_UINT, dedicated, staged, fenced) && passed;
            }
        }
    }
    switch_log_checkpoint(passed ? "transfer probe: ALL PASS" : "transfer probe: FAILED", false);
    switch_log_checkpoint("sampling probe: testing RT64 texture-copy rendering", false);
    bool sampling_passed = true;
    for (const auto& dimensions : {std::pair{4U, 2U}, std::pair{285U, 52U}, std::pair{128U, 256U}}) {
        sampling_passed = test_sampling(device, dimensions.first, dimensions.second) && sampling_passed;
    }
    switch_log_checkpoint(sampling_passed ? "sampling probe: ALL PASS" : "sampling probe: FAILED", false);
    return passed && sampling_passed;
}
