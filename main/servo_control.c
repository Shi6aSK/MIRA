#include <stdlib.h>
#include <string.h>

#include "driver/ledc.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "vision_config.h"
#include "servo_control.h"

static const char *TAG = "servo";

static bool s_pan_invert  = SERVO_PAN_INVERT  ? true : false;
static bool s_tilt_invert = SERVO_TILT_INVERT ? true : false;
static bool s_inited      = false;

void servo_set_invert(bool pan_invert, bool tilt_invert)
{
    s_pan_invert  = pan_invert;
    s_tilt_invert = tilt_invert;
}

void servo_get_invert(bool *pan_invert, bool *tilt_invert)
{
    if (pan_invert)  *pan_invert  = s_pan_invert;
    if (tilt_invert) *tilt_invert = s_tilt_invert;
}
static bool s_tracking = false;
static int s_pan_deg = SERVO_CENTER_DEG;
static int s_tilt_deg = SERVO_CENTER_DEG;
static uint64_t s_last_track_us = 0;

static int clamp_deg(int deg)
{
    if (deg < SERVO_MIN_DEG) return SERVO_MIN_DEG;
    if (deg > SERVO_MAX_DEG) return SERVO_MAX_DEG;
    return deg;
}

static uint32_t deg_to_duty(int deg)
{
    int clamped = clamp_deg(deg);
    int span = SERVO_MAX_DEG - SERVO_MIN_DEG;
    int pulse_span = SERVO_PULSE_MAX_US - SERVO_PULSE_MIN_US;
    int pulse_us = SERVO_PULSE_MIN_US + ((clamped - SERVO_MIN_DEG) * pulse_span) / (span > 0 ? span : 1);
    const int period_us = 20000;
    const int duty_max = (1 << LEDC_TIMER_14_BIT) - 1;
    return (uint32_t)((pulse_us * duty_max) / period_us);
}

static void servo_apply(ledc_channel_t channel, int deg)
{
    uint32_t duty = deg_to_duty(deg);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, channel, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, channel);
}

void servo_init(void)
{
    if (s_inited) {
        return;
    }
    if (SERVO_PAN_GPIO < 0 || SERVO_TILT_GPIO < 0) {
        ESP_LOGW(TAG, "Servo GPIOs not configured");
        return;
    }

    ledc_timer_config_t timer_cfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .timer_num = LEDC_TIMER_1,
        .duty_resolution = LEDC_TIMER_14_BIT,
        .freq_hz = 50,
        .clk_cfg = LEDC_AUTO_CLK
    };
    if (ledc_timer_config(&timer_cfg) != ESP_OK) {
        ESP_LOGE(TAG, "LEDC timer config failed");
        return;
    }

    ledc_channel_config_t pan_cfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_1,
        .timer_sel = LEDC_TIMER_1,
        .intr_type = LEDC_INTR_DISABLE,
        .gpio_num = SERVO_PAN_GPIO,
        .duty = deg_to_duty(SERVO_CENTER_DEG),
        .hpoint = 0
    };
    ledc_channel_config_t tilt_cfg = pan_cfg;
    tilt_cfg.gpio_num = SERVO_TILT_GPIO;
    tilt_cfg.channel = LEDC_CHANNEL_2;

    if (ledc_channel_config(&pan_cfg) != ESP_OK || ledc_channel_config(&tilt_cfg) != ESP_OK) {
        ESP_LOGE(TAG, "LEDC channel config failed");
        return;
    }

    s_pan_deg = SERVO_CENTER_DEG;
    s_tilt_deg = SERVO_CENTER_DEG;
    s_inited = true;
    ESP_LOGI(TAG, "Servo initialized (pan=%d tilt=%d)", s_pan_deg, s_tilt_deg);
}

void servo_set_pan(int deg)
{
    if (!s_inited) {
        servo_init();
    }
    if (!s_inited) {
        return;
    }
    s_pan_deg = clamp_deg(deg);
    servo_apply(LEDC_CHANNEL_1, s_pan_deg);
}

void servo_set_tilt(int deg)
{
    if (!s_inited) {
        servo_init();
    }
    if (!s_inited) {
        return;
    }
    s_tilt_deg = clamp_deg(deg);
    servo_apply(LEDC_CHANNEL_2, s_tilt_deg);
}

void servo_center(void)
{
    servo_set_pan(SERVO_CENTER_DEG);
    servo_set_tilt(SERVO_CENTER_DEG);
}

void servo_set_tracking(bool enable)
{
    s_tracking = enable;
}

bool servo_is_tracking(void)
{
    return s_tracking;
}

void servo_update_tracking(const detection_t *det, int frame_w, int frame_h)
{
    if (!s_tracking || !det || !det->object_present || frame_w <= 0 || frame_h <= 0) {
        return;
    }
    if (strcmp(det->kind, "face") != 0) {
        return;
    }

    uint64_t now_us = esp_timer_get_time();
    if ((now_us - s_last_track_us) < (uint64_t)SERVO_TRACK_INTERVAL_MS * 1000ULL) {
        return;
    }
    s_last_track_us = now_us;

    int cx = (det->x1 + det->x2) / 2;
    /* Target nose (~62% down from bbox top) not geometric centre */
    int cy = det->y1 + (det->y2 - det->y1) * 62 / 100;
    int dx = cx - (frame_w / 2);
    int dy = cy - (frame_h / 2);

    if (s_pan_invert)  { dx = -dx; }
    if (s_tilt_invert) { dy = -dy; }

    /* Proportional tracking: step scales with distance from centre.
       Max step = SERVO_TRACK_STEP_DEG * 5 when face is at frame edge. */
    if (abs(dx) > SERVO_TRACK_DEADBAND_PX) {
        int step = (dx * (SERVO_TRACK_STEP_DEG * 5)) / (frame_w / 2);
        if (step == 0) step = (dx > 0) ? 1 : -1;
        servo_set_pan(s_pan_deg + step);
    }
    if (abs(dy) > SERVO_TRACK_DEADBAND_PX) {
        int step = (dy * (SERVO_TRACK_STEP_DEG * 5)) / (frame_h / 2);
        if (step == 0) step = (dy > 0) ? 1 : -1;
        servo_set_tilt(s_tilt_deg + step);
    }
}
