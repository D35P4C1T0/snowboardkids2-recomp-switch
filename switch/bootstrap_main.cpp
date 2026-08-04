#include <SDL.h>
#include <switch.h>

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string_view>

namespace {
constexpr int screen_width = 1280;
constexpr int screen_height = 720;
constexpr std::string_view app_directory = "sdmc:/switch/snowboardkids2-recompiled";

struct SdlState {
    SDL_Window* window = nullptr;
    SDL_Renderer* renderer = nullptr;
    SDL_GameController* controller = nullptr;

    ~SdlState() {
        if (controller != nullptr) {
            SDL_GameControllerClose(controller);
        }
        if (renderer != nullptr) {
            SDL_DestroyRenderer(renderer);
        }
        if (window != nullptr) {
            SDL_DestroyWindow(window);
        }
        SDL_Quit();
    }
};

bool prepare_storage() {
    std::error_code error;
    std::filesystem::create_directories(app_directory, error);
    if (error) {
        return false;
    }

    std::ofstream log(std::filesystem::path(app_directory) / "bootstrap.log", std::ios::app);
    if (!log) {
        return false;
    }

    const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    log << "Switch bootstrap started at " << now << '\n';
    log << "Applet type: " << static_cast<int>(appletGetAppletType()) << '\n';
    return true;
}

SDL_GameController* open_first_controller() {
    for (int index = 0; index < SDL_NumJoysticks(); ++index) {
        if (SDL_IsGameController(index) == SDL_TRUE) {
            return SDL_GameControllerOpen(index);
        }
    }
    return nullptr;
}

void fill_rect(SDL_Renderer* renderer, int x, int y, int width, int height) {
    const SDL_Rect rect{ x, y, width, height };
    SDL_RenderFillRect(renderer, &rect);
}

void draw_bootstrap_mark(SDL_Renderer* renderer) {
    // Compact block-letter "SK2". This deliberately avoids a font dependency,
    // making the bootstrap useful even when only the base Switch portlibs exist.
    SDL_SetRenderDrawColor(renderer, 245, 250, 255, 255);

    // S
    fill_rect(renderer, 360, 250, 130, 24);
    fill_rect(renderer, 360, 250, 24, 105);
    fill_rect(renderer, 360, 340, 130, 24);
    fill_rect(renderer, 466, 340, 24, 105);
    fill_rect(renderer, 360, 430, 130, 24);

    // K
    fill_rect(renderer, 540, 250, 24, 204);
    fill_rect(renderer, 564, 340, 24, 24);
    fill_rect(renderer, 588, 316, 24, 24);
    fill_rect(renderer, 612, 292, 24, 24);
    fill_rect(renderer, 636, 268, 24, 24);
    fill_rect(renderer, 588, 364, 24, 24);
    fill_rect(renderer, 612, 388, 24, 24);
    fill_rect(renderer, 636, 412, 24, 24);

    // 2
    fill_rect(renderer, 710, 250, 130, 24);
    fill_rect(renderer, 816, 250, 24, 105);
    fill_rect(renderer, 710, 340, 130, 24);
    fill_rect(renderer, 710, 340, 24, 105);
    fill_rect(renderer, 710, 430, 130, 24);
}

void render_frame(SDL_Renderer* renderer, bool storage_ready, bool application_mode, Uint32 ticks) {
    const Uint8 pulse = static_cast<Uint8>(24 + ((ticks / 12) % 32));
    SDL_SetRenderDrawColor(renderer, 13, pulse, 70, 255);
    SDL_RenderClear(renderer);

    draw_bootstrap_mark(renderer);

    SDL_SetRenderDrawColor(renderer, storage_ready ? 56 : 210, storage_ready ? 190 : 48, 72, 255);
    fill_rect(renderer, 360, 510, 220, 14);

    SDL_SetRenderDrawColor(renderer, application_mode ? 56 : 230, application_mode ? 190 : 165, 72, 255);
    fill_rect(renderer, 620, 510, 220, 14);

    SDL_RenderPresent(renderer);
}
} // namespace

int main(int, char**) {
    const bool storage_ready = prepare_storage();
    const bool application_mode = appletGetAppletType() == AppletType_Application;

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMECONTROLLER) < 0) {
        return EXIT_FAILURE;
    }

    SdlState sdl;
    sdl.window = SDL_CreateWindow(
        "Snowboard Kids 2: Recompiled - Switch bootstrap",
        SDL_WINDOWPOS_CENTERED,
        SDL_WINDOWPOS_CENTERED,
        screen_width,
        screen_height,
        SDL_WINDOW_SHOWN
    );
    if (sdl.window == nullptr) {
        return EXIT_FAILURE;
    }

    sdl.renderer = SDL_CreateRenderer(sdl.window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (sdl.renderer == nullptr) {
        return EXIT_FAILURE;
    }

    sdl.controller = open_first_controller();

    bool running = true;
    while (running && appletMainLoop()) {
        SDL_Event event{};
        while (SDL_PollEvent(&event) != 0) {
            if (event.type == SDL_QUIT) {
                running = false;
            } else if (event.type == SDL_CONTROLLERDEVICEADDED && sdl.controller == nullptr) {
                sdl.controller = SDL_GameControllerOpen(event.cdevice.which);
            } else if (event.type == SDL_CONTROLLERBUTTONDOWN &&
                       event.cbutton.button == SDL_CONTROLLER_BUTTON_START) {
                running = false;
            }
        }

        render_frame(sdl.renderer, storage_ready, application_mode, SDL_GetTicks());
    }

    return storage_ready ? EXIT_SUCCESS : EXIT_FAILURE;
}
