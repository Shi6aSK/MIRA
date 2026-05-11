#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "img_converters.h"
#include <string.h>

#include "esp_camera.h"
#include "vision_config.h"
#include "camera_control.h"
#include "vision_pipeline.h"
#include "web_server.h"
#include "wifi_manager.h"
#include "servo_control.h"
#include "oled_control.h"
#include "sd_card.h"
#include "training.h"
#include "mic_capture.h"

static const char *TAG = "app";

// PSRAM scratch buffer – camera fb is copied here then returned immediately
// so the 2 camera buffers are free again before slow ESP-DL inference.
static uint8_t *s_frame_copy = NULL;

static int s_null_streak = 0;

/* ── Gesture auto-trigger state ────────────────────────────────── */
static char     s_prev_gesture[16]    = "none";
static int      s_gesture_count       = 0;
static uint32_t s_last_trigger_ms     = 0;

static void vision_task(void *arg)
{
    for (;;) {
        camera_fb_t *fb = camera_capture();
        if (!fb) {
            /* Camera timed out – restart DMA if it happens repeatedly */
            if (++s_null_streak >= 3) {  /* reinit after 3×4 s DMA timeouts = 12 s */
                ESP_LOGW(TAG, "Camera stalled – reinitialising");
                esp_camera_deinit();
                vTaskDelay(pdMS_TO_TICKS(200));
                camera_init();
                s_null_streak = 0;
            }
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        s_null_streak = 0;
        if (fb && s_frame_copy) {
            // Skip truncated frames – FB-SIZE mismatch crashes fmt2jpg
            if (fb->len != (size_t)(FRAME_WIDTH * FRAME_HEIGHT * 2)) {
                camera_return(fb);
                vTaskDelay(pdMS_TO_TICKS(10));
                continue;
            }
            // Copy pixels and release the camera buffer BEFORE detection
            size_t len = fb->len;
            int w = (int)fb->width, h = (int)fb->height;
            memcpy(s_frame_copy, fb->buf, len);
            camera_return(fb);          // return ASAP – frees the DMA buffer

            // Encode JPEG from PSRAM copy and push to HTTP shared buffer.
            // This happens before inference so /frame is always fresh.
            {
                uint8_t *jpg = NULL; size_t jpg_len = 0;
                if (fmt2jpg(s_frame_copy, len, (uint16_t)w, (uint16_t)h,
                            PIXFORMAT_RGB565, JPEG_QUALITY, &jpg, &jpg_len)) {
                    web_server_update_frame(jpg, jpg_len);
                    free(jpg);
                }
            }

            // Run (slow) inference on the PSRAM copy
            camera_fb_t fake;
            memset(&fake, 0, sizeof(fake));
            fake.buf    = s_frame_copy;
            fake.len    = len;
            fake.width  = (size_t)w;
            fake.height = (size_t)h;
            fake.format = PIXFORMAT_RGB565;
            vision_process_frame(&fake);

            // Training hooks (no-ops when TRAIN_IDLE)
            detection_t det = vision_get_detection();
            training_maybe_capture_face(&fake, &det);
            training_maybe_capture_gesture(&det);

            /* ── Gesture auto-trigger ──────────────────────────── */
            if (strcmp(det.gesture, s_prev_gesture) == 0) {
                s_gesture_count++;
            } else {
                strncpy(s_prev_gesture, det.gesture, sizeof(s_prev_gesture) - 1);
                s_gesture_count = 1;
            }
            uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            if (s_gesture_count == GESTURE_CONFIRM_FRAMES &&
                (now_ms - s_last_trigger_ms) >= GESTURE_COOLDOWN_MS) {

                if (strcmp(det.gesture, "point") == 0) {
                    ESP_LOGI(TAG, "point gesture → Gemma snap");
                    web_server_auto_trigger_gemma("point");
                    s_last_trigger_ms = now_ms;
                } else if (strcmp(det.gesture, "open_palm") == 0) {
                    ESP_LOGI(TAG, "open_palm gesture → mic record");
                    mic_capture_async(MIC_DURATION_MS);
                    s_last_trigger_ms = now_ms;
                }
            }

        } else if (fb) {
            camera_return(fb);
        }
        vTaskDelay(pdMS_TO_TICKS(20));  // yield to IDLE – prevents task WDT trigger
    }
}

void app_main(void)
{
    ESP_LOGW(TAG, "Booting...");

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    oled_init();
    servo_init();
    servo_set_tracking(true);

    /* SD card – non-fatal if absent */
    sd_init();
    training_init();
    training_load_gesture_templates();

    /* PDM microphone – non-fatal if absent */
    mic_init();

    // Allocate the PSRAM frame copy buffer (240x240 RGB565 = 115200 bytes)
    s_frame_copy = heap_caps_malloc(FRAME_WIDTH * FRAME_HEIGHT * 2,
                                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_frame_copy) {
        ESP_LOGE(TAG, "Failed to allocate frame copy buffer");
    }

    vision_init();

    /* Connect WiFi FIRST – avoids ESP32-S3 GDMA freeze when WiFi DMA
       starts while the camera DMA is already running (issue #620). */
    if (wifi_init_sta() != ESP_OK) {
        ESP_LOGE(TAG, "WiFi failed – HTTP server unavailable");
    } else {
        ESP_ERROR_CHECK(web_server_start());
        ESP_LOGW(TAG, "Open http://%s/ in a browser", wifi_get_ip());
    }

    /* Camera init AFTER WiFi is fully up.
       Extra 3 s pause: WiFi TCP handshakes fire GDMA bursts that can
       collide with camera DMA during the first few frames. */
    vTaskDelay(pdMS_TO_TICKS(3000));
    ESP_ERROR_CHECK(camera_init());

    xTaskCreatePinnedToCore(vision_task, "vision", 32768, NULL, 5, NULL, 1);
}
