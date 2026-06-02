#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// Initialise SSD1306 128x32 OLED on I2C_NUM_0 (GPIO SDA=4, SCL=5).
// Safe to call if OLED is absent – subsequent calls become no-ops.
void oled_init(void);

// Draw animated eyes.  pupil_dx/dy are pixel offsets from centre (-20..20, -6..6).
// face_seen=true draws alert open eyes; face_seen=false draws half-closed eyes.
void oled_draw_eyes(int pupil_dx, int pupil_dy, bool face_seen);

// Draw closed/sleep eyes (no face present).
void oled_draw_sleep(void);

// Draw happy-squint "UwU" face with sound-wave arcs: shown while mic is recording.
// Suppresses oled_draw_eyes/sleep for ~2.5 s so the sign stays visible.
void oled_draw_recording(void);

// Draw thinking face (pupils up-left, dots below): shown while Gemma is processing.
// Also suppresses normal eye drawing for ~2.5 s.
void oled_draw_thinking(void);

#ifdef __cplusplus
}
#endif
