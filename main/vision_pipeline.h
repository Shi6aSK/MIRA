#pragma once

#include "esp_camera.h"
#include "vision_types.h"
#include "vision_config.h"

/* Skin-blob grid dimensions (for gesture training) */
#define VISION_GW  (FRAME_WIDTH  / BLOCK_SIZE)
#define VISION_GH  (FRAME_HEIGHT / BLOCK_SIZE)

#ifdef __cplusplus
extern "C" {
#endif

// Load the ESP-DL face detection model.  Call once before vision_process_frame.
void vision_init(void);

// Process one RGB565 frame: runs face detection first, then gesture detection
// only when a face is present in the frame.
// Updates internal detection state readable via vision_get_detection().
void vision_process_frame(camera_fb_t *fb);

// Thread-safe read of the latest detection result.
detection_t vision_get_detection(void);

// Get the normalized geometric features of the last detected skin blob.
// ar      : aspect ratio (blob bbox width / height in grid cells)
// fill    : fill ratio (skin cells / total bbox cells)
// cy_norm : vertical centroid normalized to [0,1] (0=top, 1=bottom of bbox)
void vision_get_blob_features(float *ar, float *fill, float *cy_norm);

#ifdef __cplusplus
}
#endif
