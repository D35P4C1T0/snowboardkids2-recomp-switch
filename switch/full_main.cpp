#include <switch.h>

// Request the full application memory profile. The NRO must still be launched
// through Homebrew Menu title takeover; Album/applet mode is unsupported.
extern "C" {
    u32 __nx_applet_type = AppletType_Application;
    size_t __nx_heap_size = 0;
}
