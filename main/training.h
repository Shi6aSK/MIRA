#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_camera.h"
#include "vision_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TRAIN_IDLE    = 0,
    TRAIN_FACE    = 1,
    TRAIN_GESTURE = 2,
} train_mode_t;

// Initialize training subsystem (call once from app_main).
void training_init(void);

// Start collecting labeled face samples.
void training_start_face(const char *label);

// Start collecting labeled gesture templates.
void training_start_gesture(const char *label);

// Stop training and finalize.
void training_stop(void);

// Queries
train_mode_t training_get_mode(void);
const char  *training_get_label(void);
int          training_get_count(void);

// Call from vision_task after vision_process_frame().
// Saves a face JPEG to SD if in face-training mode and a face is detected.
bool training_maybe_capture_face(const camera_fb_t *fb, const detection_t *det);

// Call from vision_task after vision_process_frame().
// Saves a feature-vector .bin to SD if in gesture-training mode and a named
// gesture (not "hand"/"none") is detected. Calls vision_get_blob_features().
bool training_maybe_capture_gesture(const detection_t *det);

// Load all feature-vector gesture templates from SD (FEAT format) into RAM.
// Call once after sd_init().
void training_load_gesture_templates(void);

// 1-NN classify a blob by its geometric features against loaded templates.
// Returns the gesture label (e.g. "point", "open_palm") or NULL when no
// templates are loaded (caller falls back to geometric heuristic).
const char *gesture_knn_classify(float ar, float fill, float cy_norm);

// Number of templates currently loaded into the KNN index.
int gesture_knn_count(void);

// Delete all gesture template files from SD and clear the in-memory KNN index.
void training_clear_gesture_templates(void);

#ifdef __cplusplus
}
#endif
