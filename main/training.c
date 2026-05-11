/*
 * training.c
 *
 * Manages face and gesture training sessions.
 * Face training: saves labeled JPEG frames to /sdcard/faces/<label>/<NNNN>.jpg
 * Gesture training: saves skin-blob binary masks to /sdcard/gestures/<label>/<NNNN>.bin
 *
 * Binary gesture file layout (44 + GW*GH bytes):
 *   [0..3]   magic  = 0x47455354 ('GEST')
 *   [4..7]   gw     (uint32_t)
 *   [8..11]  gh     (uint32_t)
 *   [12..43] label  (32-byte null-padded string)
 *   [44..]   mask   (gw*gh uint8_t cells, 1=skin 0=not)
 */
#include "training.h"
#include "sd_card.h"
#include "vision_pipeline.h"   /* vision_get_blob_mask, VISION_GW, VISION_GH */
#include "img_converters.h"    /* fmt2jpg  */
#include "esp_camera.h"
#include "esp_log.h"
#include <dirent.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

static const char *TAG = "train";

static train_mode_t s_mode  = TRAIN_IDLE;
static char         s_label[32] = "unknown";
static int          s_count = 0;

void training_init(void)
{
    s_mode  = TRAIN_IDLE;
    s_count = 0;
}

void training_start_face(const char *label)
{
    if (!label || !label[0]) label = "unknown";
    strncpy(s_label, label, sizeof(s_label) - 1);
    s_label[sizeof(s_label) - 1] = '\0';
    s_count = 0;

    char dir[64];
    sd_mkdir("/faces");
    snprintf(dir, sizeof(dir), "/faces/%s", s_label);
    sd_mkdir(dir);

    s_mode = TRAIN_FACE;
    ESP_LOGI(TAG, "Face training started  label='%s'", s_label);
}

void training_start_gesture(const char *label)
{
    if (!label || !label[0]) label = "unknown";
    strncpy(s_label, label, sizeof(s_label) - 1);
    s_label[sizeof(s_label) - 1] = '\0';
    s_count = 0;

    char dir[64];
    sd_mkdir("/gestures");
    snprintf(dir, sizeof(dir), "/gestures/%s", s_label);
    sd_mkdir(dir);

    s_mode = TRAIN_GESTURE;
    ESP_LOGI(TAG, "Gesture training started  label='%s'", s_label);
}

void training_stop(void)
{
    if (s_mode != TRAIN_IDLE)
        ESP_LOGI(TAG, "Training stopped  label='%s'  samples=%d", s_label, s_count);
    s_mode = TRAIN_IDLE;
}

train_mode_t training_get_mode(void)  { return s_mode; }
const char  *training_get_label(void) { return s_label; }
int          training_get_count(void) { return s_count; }

bool training_maybe_capture_face(const camera_fb_t *fb, const detection_t *det)
{
    if (s_mode != TRAIN_FACE)                             return false;
    if (!det->object_present)                             return false;
    if (strcmp(det->kind, "face") != 0)                   return false;
    if (!fb || !fb->buf)                                  return false;
    if (!sd_is_mounted())                                 return false;

    /* Encode full frame as JPEG */
    uint8_t *jpg = NULL;
    size_t   jpg_len = 0;
    bool ok = fmt2jpg(fb->buf, fb->len,
                      (uint16_t)fb->width, (uint16_t)fb->height,
                      PIXFORMAT_RGB565, 15, &jpg, &jpg_len);
    if (!ok || !jpg) return false;

    char path[80];
    snprintf(path, sizeof(path), "/faces/%s/%04d.jpg", s_label, s_count);
    ok = sd_save_bytes(path, jpg, jpg_len);
    free(jpg);

    if (ok) {
        s_count++;
        ESP_LOGI(TAG, "Face sample %d  → %s  (%u B)", s_count, path, (unsigned)jpg_len);
    }
    return ok;
}

bool training_maybe_capture_gesture(const detection_t *det)
{
    if (s_mode != TRAIN_GESTURE)                          return false;
    if (!det->object_present)                             return false;
    if (strcmp(det->gesture, "none") == 0)                return false;
    if (!sd_is_mounted())                                 return false;

    const int gw = VISION_GW, gh = VISION_GH;
    uint8_t mask[VISION_GW * VISION_GH];
    vision_get_blob_mask(mask);

    /* Build binary file */
    const size_t HDR = 44;
    size_t total = HDR + (size_t)(gw * gh);
    uint8_t *buf = malloc(total);
    if (!buf) return false;

    uint32_t magic = 0x47455354U;
    uint32_t ugw   = (uint32_t)gw;
    uint32_t ugh   = (uint32_t)gh;
    memcpy(buf +  0, &magic, 4);
    memcpy(buf +  4, &ugw,   4);
    memcpy(buf +  8, &ugh,   4);
    memset(buf + 12, 0, 32);
    strncpy((char *)(buf + 12), s_label, 31);
    memcpy(buf + HDR, mask, (size_t)(gw * gh));

    char path[80];
    snprintf(path, sizeof(path), "/gestures/%s/%04d.bin", s_label, s_count);
    bool ok = sd_save_bytes(path, buf, total);
    free(buf);

    if (ok) {
        s_count++;
        ESP_LOGI(TAG, "Gesture sample %d  → %s", s_count, path);
    }
    return ok;
}

void training_load_gesture_templates(void)
{
    if (!sd_is_mounted()) {
        ESP_LOGI(TAG, "Gesture templates: SD not mounted, skipping scan");
        return;
    }

    const char *root = "/sdcard/gestures";
    DIR *root_dir = opendir(root);
    if (!root_dir) {
        ESP_LOGI(TAG, "Gesture templates: no directory at %s", root);
        return;
    }

    int labels = 0;
    int files = 0;
    int valid = 0;
    int invalid = 0;

    struct dirent *label_ent = NULL;
    while ((label_ent = readdir(root_dir)) != NULL) {
        if (label_ent->d_name[0] == '.') continue;

        char label_path[128];
        int lp = snprintf(label_path, sizeof(label_path), "%s/%s", root, label_ent->d_name);
        if (lp <= 0 || lp >= (int)sizeof(label_path)) continue;

        DIR *label_dir = opendir(label_path);
        if (!label_dir) continue;
        labels++;

        struct dirent *file_ent = NULL;
        while ((file_ent = readdir(label_dir)) != NULL) {
            if (file_ent->d_name[0] == '.') continue;

            const char *dot = strrchr(file_ent->d_name, '.');
            if (!dot || strcmp(dot, ".bin") != 0) continue;

            files++;

            char file_path[160];
            int fp = snprintf(file_path, sizeof(file_path), "%s/%s", label_path, file_ent->d_name);
            if (fp <= 0 || fp >= (int)sizeof(file_path)) {
                invalid++;
                continue;
            }

            FILE *f = fopen(file_path, "rb");
            if (!f) {
                invalid++;
                continue;
            }

            uint32_t magic = 0;
            uint32_t gw = 0;
            uint32_t gh = 0;
            size_t n1 = fread(&magic, 1, sizeof(magic), f);
            size_t n2 = fread(&gw, 1, sizeof(gw), f);
            size_t n3 = fread(&gh, 1, sizeof(gh), f);
            fclose(f);

            bool ok = (n1 == sizeof(magic)) &&
                      (n2 == sizeof(gw)) &&
                      (n3 == sizeof(gh)) &&
                      (magic == 0x47455354U) &&
                      ((int)gw == VISION_GW) &&
                      ((int)gh == VISION_GH);

            if (ok) valid++;
            else    invalid++;
        }

        closedir(label_dir);
    }

    closedir(root_dir);

    ESP_LOGI(TAG,
             "Gesture templates indexed: labels=%d files=%d valid=%d invalid=%d",
             labels, files, valid, invalid);
}
