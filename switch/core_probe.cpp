#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

#include <switch.h>

#include "plume_render_interface.h"

bool switch_run_texture_probe(plume::RenderDevice* device, bool include_inline);

namespace plume {
std::unique_ptr<RenderInterface> CreateVulkanInterface(RenderWindow window);
}

extern "C" {
// switch-nvk exposes this optional sink so applications can retain driver
// diagnostics even when no debugger is attached.
extern void (*g_drm_shim_log_sink)(const char* message);
}

namespace {
std::FILE* probe_log = nullptr;
bool console_active = false;
int log_socket = -1;

void network_log(const char* message) {
    if (log_socket >= 0) {
        // Diagnostics must never block the probe if the receiver disappears.
        send(log_socket, message, std::strlen(message), MSG_DONTWAIT | MSG_NOSIGNAL);
        send(log_socket, "\n", 1, MSG_DONTWAIT | MSG_NOSIGNAL);
    }
}

void write_debug_string(const char* message) {
    svcOutputDebugString(message, std::strlen(message));
}

void checkpoint(const char* message) {
    network_log(message);
    // Persist the checkpoint before touching the display so a console-side
    // fault cannot hide the actual last boundary reached.
    if (probe_log != nullptr) {
        std::fprintf(probe_log, "%s\n", message);
        std::fflush(probe_log);
    }

    write_debug_string(message);
    write_debug_string("\n");

    if (console_active) {
        std::printf("%s\n", message);
        consoleUpdate(nullptr);
    }
}

void driver_log_sink(const char* message) {
    if (message == nullptr) {
        return;
    }
    network_log(message);

    if (probe_log != nullptr) {
        std::fprintf(probe_log, "[nvk] %s", message);
        const size_t length = std::strlen(message);
        if ((length == 0) || (message[length - 1] != '\n')) {
            std::fputc('\n', probe_log);
        }
        std::fflush(probe_log);
    }

    write_debug_string("[nvk] ");
    write_debug_string(message);
}
}

void switch_log_checkpoint(const char* message, bool) {
    if (message != nullptr) {
        checkpoint(message);
    }
}

extern "C" void dusk_switch_log(const char* message) {
    if (message == nullptr) {
        return;
    }

    if (probe_log != nullptr) {
        std::fputs(message, probe_log);
        const size_t length = std::strlen(message);
        if ((length == 0) || (message[length - 1] != '\n')) {
            std::fputc('\n', probe_log);
        }
        std::fflush(probe_log);
    }

    write_debug_string(message);
}

int main(int argc, char** argv) {
    bool include_inline = false;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--msaa-probe") == 0)
            setenv("SK2_SWITCH_MSAA_PROBE", "1", 1);
        if (std::strcmp(argv[i], "--packed-framebuffer-copyback") == 0)
            setenv("SK2_SWITCH_PACKED_COPYBACK", "1", 1);
        include_inline |= std::strcmp(argv[i], "--inline-transfers") == 0;
        if (std::strcmp(argv[i], "--async-submissions") == 0)
            setenv("NVK_SWITCH_ASYNC", "1", 1);
    }
    const bool sockets_ready = R_SUCCEEDED(socketInitializeDefault());
    if (sockets_ready && __nxlink_host.s_addr != 0) {
        log_socket = nxlinkConnectToHost(false, false);
    }
    consoleInit(nullptr);
    console_active = true;
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    checkpoint("[01] main entered");

    checkpoint("[02] opening SD log");
    probe_log = std::fopen("sdmc:/switch/snowboardkids2-recompiled/core-probe.log", "w");
    if (probe_log == nullptr) {
        probe_log = std::fopen("sdmc:/sk2-core-probe.log", "w");
    }
    if (probe_log != nullptr) {
        std::setvbuf(probe_log, nullptr, _IONBF, 0);
    }
    checkpoint(probe_log != nullptr ? "[03] SD log open" : "[03] SD log unavailable");

    // Tegra X1's GM20B is intentionally outside NVK's conformance list. The
    // Switch driver requires an explicit opt-in before it exposes the device.
    checkpoint("[04] setting NVK environment");
    setenv("NVK_I_WANT_A_BROKEN_VULKAN_DRIVER", "1", 1);
    setenv("NVK_TRACE", "1", 1);
    setenv("NVK_SWITCH_WSI_CPU_COPY", "1", 1);
    g_drm_shim_log_sink = driver_log_sink;
    checkpoint("[05] NVK environment ready");

    PadState pad;
    padConfigureInput(1, HidNpadStyleSet_NpadStandard);
    padInitializeDefault(&pad);
    checkpoint("[06] input ready");

    std::unique_ptr<plume::RenderInterface> render_interface;
    std::unique_ptr<plume::RenderDevice> render_device;
    std::unique_ptr<plume::RenderCommandQueue> command_queue;
    std::unique_ptr<plume::RenderSwapChain> swap_chain;
    bool surface_ready = false;
    bool presentation_ready = false;
    bool transfers_ready = false;

    checkpoint("[07] creating Vulkan interface");
    render_interface = plume::CreateVulkanInterface(nullptr);
    checkpoint(render_interface != nullptr
        ? "[08] Vulkan interface ready"
        : "[08] Vulkan interface FAILED");

    if (render_interface != nullptr) {
        checkpoint("[09] creating Vulkan device");
        render_device = render_interface->createDevice();
        checkpoint(render_device != nullptr
            ? "[10] Vulkan device ready"
            : "[10] Vulkan device FAILED");
    }

    if (render_device != nullptr) {
        checkpoint("[10a] verifying buffer and image transfers");
        transfers_ready = switch_run_texture_probe(render_device.get(), include_inline);
        checkpoint("[11] creating graphics queue");
        command_queue = render_device->createCommandQueue(plume::RenderCommandListType::DIRECT);
        checkpoint(command_queue != nullptr
            ? "[12] graphics queue ready"
            : "[12] graphics queue FAILED");
    }

    if (command_queue != nullptr) {
        // The libnx console owns buffers on the default NWindow. Release those
        // buffers before asking Vulkan WSI to register its swapchain buffers.
        checkpoint("[13] releasing console for native surface");
        consoleExit(nullptr);
        console_active = false;

        checkpoint("[14] creating native Switch surface");
        swap_chain = command_queue->createSwapChain(plume::RenderSwapChainDesc(
            nullptr, plume::RenderFormat::B8G8R8A8_UNORM, 3));
        checkpoint(swap_chain != nullptr
            ? "[15] native surface object ready"
            : "[15] native surface object FAILED");

        if (swap_chain != nullptr) {
            checkpoint("[16] creating 1280x720 swapchain");
            surface_ready = swap_chain->resize();
            if (surface_ready) {
                char dimensions[128];
                std::snprintf(dimensions, sizeof(dimensions),
                    "[17] swapchain ready: %ux%u, %u images",
                    swap_chain->getWidth(), swap_chain->getHeight(), swap_chain->getTextureCount());
                checkpoint(dimensions);
            }
            else {
                checkpoint("[17] swapchain FAILED");
            }
        }

        std::unique_ptr<plume::RenderCommandList> command_list;
        std::unique_ptr<plume::RenderCommandFence> command_fence;
        std::unique_ptr<plume::RenderCommandSemaphore> acquire_semaphore;
        std::unique_ptr<plume::RenderCommandSemaphore> release_semaphore;
        std::vector<std::unique_ptr<plume::RenderFramebuffer>> framebuffers;

        if (surface_ready) {
            checkpoint("[18] creating presentation resources");
            command_list = command_queue->createCommandList();
            command_fence = render_device->createCommandFence();
            acquire_semaphore = render_device->createCommandSemaphore();
            release_semaphore = render_device->createCommandSemaphore();

            for (uint32_t i = 0; i < swap_chain->getTextureCount(); i++) {
                const plume::RenderTexture* color_attachment = swap_chain->getTexture(i);
                framebuffers.emplace_back(render_device->createFramebuffer(
                    plume::RenderFramebufferDesc(&color_attachment, 1)));
            }

            bool resources_ready = command_list != nullptr && command_fence != nullptr &&
                acquire_semaphore != nullptr && release_semaphore != nullptr &&
                framebuffers.size() == swap_chain->getTextureCount();
            for (const auto& framebuffer : framebuffers) {
                resources_ready = resources_ready && framebuffer != nullptr;
            }
            checkpoint(resources_ready
                ? "[19] presentation resources ready"
                : "[19] presentation resources FAILED");

            if (resources_ready) {
                uint32_t image_index = 0;
                checkpoint("[20] acquiring swapchain image");
                const bool acquired = swap_chain->acquireTexture(acquire_semaphore.get(), &image_index);
                checkpoint(acquired
                    ? "[21] swapchain image acquired"
                    : "[21] swapchain image acquire FAILED");

                if (acquired) {
                    checkpoint("[22] recording green clear");
                    command_list->begin();
                    plume::RenderTexture* texture = swap_chain->getTexture(image_index);
                    command_list->barriers(plume::RenderBarrierStage::GRAPHICS,
                        plume::RenderTextureBarrier(texture, plume::RenderTextureLayout::COLOR_WRITE));
                    command_list->setFramebuffer(framebuffers[image_index].get());
                    command_list->setViewports(plume::RenderViewport(
                        0.0f, 0.0f, float(swap_chain->getWidth()), float(swap_chain->getHeight())));
                    command_list->setScissors(plume::RenderRect(
                        0, 0, swap_chain->getWidth(), swap_chain->getHeight()));
                    command_list->clearColor(0, plume::RenderColor(0.05f, 0.55f, 0.15f, 1.0f));
                    command_list->barriers(plume::RenderBarrierStage::NONE,
                        plume::RenderTextureBarrier(texture, plume::RenderTextureLayout::PRESENT));
                    command_list->end();
                    checkpoint("[23] green clear recorded");

                    const plume::RenderCommandList* submitted_list = command_list.get();
                    plume::RenderCommandSemaphore* wait_semaphore = acquire_semaphore.get();
                    plume::RenderCommandSemaphore* signal_semaphore = release_semaphore.get();
                    checkpoint("[24] submitting green frame");
                    command_queue->executeCommandLists(
                        &submitted_list, 1,
                        &wait_semaphore, 1,
                        &signal_semaphore, 1,
                        command_fence.get());
                    checkpoint("[25] green frame submitted");

                    checkpoint("[26] presenting green frame");
                    presentation_ready = swap_chain->present(image_index, &signal_semaphore, 1);
                    checkpoint(presentation_ready
                        ? "[27] green frame presented"
                        : "[27] green frame present FAILED");
                    command_queue->waitForCommandFence(command_fence.get());
                    checkpoint("[28] GPU fence complete");

                    // Leave the test frame visible briefly before returning the
                    // default NWindow to the libnx text console.
                    svcSleepThread(2000000000L);
                }
            }
        }

        checkpoint("[29] destroying presentation resources");
        framebuffers.clear();
        release_semaphore.reset();
        acquire_semaphore.reset();
        command_fence.reset();
        command_list.reset();
        checkpoint("[30] presentation resources destroyed");

        checkpoint("[31] destroying native swapchain");
        swap_chain.reset();
        checkpoint("[32] native swapchain destroyed");
        command_queue.reset();
        checkpoint("[33] graphics queue destroyed");

        checkpoint(presentation_ready
            ? "[34] NVK PRESENTATION PASS"
            : "[34] NVK PRESENTATION FAILED (see log)");
    }

    checkpoint("[35] destroying Vulkan device");
    render_device.reset();
    checkpoint("[36] Vulkan device destroyed");
    render_interface.reset();
    checkpoint("[37] Vulkan interface destroyed");

    g_drm_shim_log_sink = nullptr;
    if (log_socket >= 0) {
        close(log_socket);
        log_socket = -1;
    }
    if (sockets_ready) socketExit();
    if (probe_log != nullptr) {
        std::fclose(probe_log);
        probe_log = nullptr;
    }

    // Only restore the libnx framebuffer after NVK has released its nvmap,
    // nvhost, fence, and address-space services. Recreating the console while
    // the driver was still alive made device teardown invalidate the console's
    // graphics state and caused a hard crash on exit.
    consoleInit(nullptr);
    console_active = true;
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::printf("%s\n", presentation_ready
        ? "[38] NVK PRESENTATION + CLEAN SHUTDOWN PASS"
        : "[38] NVK PRESENTATION FAILED (see core-probe.log)");
    std::printf("\nPress + to exit.\n");
    std::printf("Texture transfers: %s\n", transfers_ready ? "PASS" : "FAIL (see core-probe.log)");
    consoleUpdate(nullptr);

    while (appletMainLoop()) {
        padUpdate(&pad);
        if ((padGetButtonsDown(&pad) & HidNpadButton_Plus) != 0) {
            break;
        }
        consoleUpdate(nullptr);
    }

    consoleExit(nullptr);
    console_active = false;
    return presentation_ready && transfers_ready ? 0 : 2;
}
