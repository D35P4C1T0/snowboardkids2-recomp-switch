// Compile the generated integer audio microcode with a separate optimization
// level so the reference path remains available for hardware comparisons.
// Give variant inline methods distinct symbols so linker COMDAT folding cannot
// silently select reference implementations for the optimized translation.
#define RSP SwitchOptimizedRSP
#define RspContext SwitchOptimizedRspContext
#define SK2_SWITCH_RSP_VECTOR_MEMORY 1
#define aspMain switchAspMainOptimized
#include "../rsp/aspMain.cpp"
