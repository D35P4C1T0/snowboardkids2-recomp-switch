#pragma once

void switch_log_checkpoint(const char* message, bool reset = false);

#if defined(__SWITCH__)
void switch_initialize_logging();
void switch_shutdown_logging();
void switch_install_driver_log_sink();
#endif
