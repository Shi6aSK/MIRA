#pragma once
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Initialise the PDM microphone (call once). */
esp_err_t mic_init(void);

/* Capture ~duration_ms of audio and save as WAV to /sdcard/recordings/NNNN.wav.
 * Runs in a newly spawned task so the call returns immediately.
 * Safe to call from vision_task. */
void mic_capture_async(int duration_ms);

#ifdef __cplusplus
}
#endif
