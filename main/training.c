/*
 * training.c
 *
 * Manages face and gesture training sessions.
 * Face training:    saves labeled JPEG frames to /sdcard/faces/<label>/<NNNN>.jpg
 * Gesture training: saves feature-vector files  to /sdcard/gestures/<label>/<NNNN>.bin
 *
 * Feature-vector gesture file layout (52 bytes, 'FEAT' format):
 *   [0..3]   magic   = 0x46454154 ('FEAT')
 *   [4..7]   version = 1  (uint32_t)
 *   [8..39]  label   (32-byte null-padded string)
 *   [40..43] ar      (float32 – aspect ratio: bbox_w / bbox_h)
 *   [44..47] fill    (float32 – fill ratio: skin_cells / bbox_cells)
 *   [48..51] cy      (float32 – vertical centroid 0=top 1=bottom)
 */
#include "training.h"
#include "sd_card.h"
#include "vision_pipeline.h"   /* vision_get_blob_features */
#include "img_converters.h"    /* fmt2jpg  */
#include "esp_camera.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include <dirent.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

static const char *TAG = "train";

static train_mode_t s_mode  = TRAIN_IDLE;
static char         s_label[32] = "unknown";
static int          s_count = 0;

/* ── Feature-vector KNN storage (forward-declared for use in capture fn) ── */

#define KNN_MAX_TEMPLATES 256

typedef struct {
    char  label[32];
    float ar;     /* aspect ratio  (bbox_w / bbox_h) */
    float fill;   /* fill ratio    (skin cells / bbox cells) */
    float cy;     /* vert centroid (0=top, 1=bottom within bbox) */
} feat_tpl_t;

static feat_tpl_t *s_knn_tpl   = NULL;
static int         s_knn_count = 0;

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
    /* Accept "hand" too – user has set the label via training_start_gesture().
     * The measured ar/fill/cy are valid (face region is masked before BFS). */
    if (!sd_is_mounted())                                 return false;

    float ar = 1.0f, fill = 0.5f, cy = 0.5f;
    vision_get_blob_features(&ar, &fill, &cy);

    /* FEAT file: 52 bytes */
    uint8_t buf[52];
    memset(buf, 0, sizeof(buf));
    uint32_t magic = 0x46454154U;  /* 'FEAT' */
    uint32_t ver   = 1U;
    memcpy(buf +  0, &magic, 4);
    memcpy(buf +  4, &ver,   4);
    strncpy((char *)(buf + 8), s_label, 31);
    memcpy(buf + 40, &ar,   4);
    memcpy(buf + 44, &fill, 4);
    memcpy(buf + 48, &cy,   4);

    char path[80];
    snprintf(path, sizeof(path), "/gestures/%s/%04d.bin", s_label, s_count);
    bool ok = sd_save_bytes(path, buf, sizeof(buf));

    if (ok) {
        /* Also add to in-memory KNN immediately so it is usable before reboot */
        if (s_knn_tpl && s_knn_count < KNN_MAX_TEMPLATES) {
            strncpy(s_knn_tpl[s_knn_count].label, s_label, 31);
            s_knn_tpl[s_knn_count].label[31] = '\0';
            s_knn_tpl[s_knn_count].ar   = ar;
            s_knn_tpl[s_knn_count].fill = fill;
            s_knn_tpl[s_knn_count].cy   = cy;
            s_knn_count++;
        }
        s_count++;
        ESP_LOGI(TAG, "Gesture sample %d \u2192 %s  ar=%.2f fill=%.2f cy=%.2f",
                 s_count, path, ar, fill, cy);
    }
    return ok;
}

/* ── Feature-vector KNN gesture classifier ───────────────────────────── */

void training_load_gesture_templates(void)
{
    if (!sd_is_mounted()) {
        ESP_LOGI(TAG, "KNN: SD not mounted, skipping");
        return;
    }

    s_knn_tpl = (feat_tpl_t *)heap_caps_malloc(
                    KNN_MAX_TEMPLATES * sizeof(feat_tpl_t),
                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_knn_tpl)
        s_knn_tpl = (feat_tpl_t *)malloc(KNN_MAX_TEMPLATES * sizeof(feat_tpl_t));
    if (!s_knn_tpl) {
        ESP_LOGE(TAG, "KNN: allocation failed");
        return;
    }
    s_knn_count = 0;

    DIR *root_dir = opendir("/sdcard/gestures");
    if (!root_dir) {
        ESP_LOGI(TAG, "KNN: /sdcard/gestures not found – no templates loaded");
        return;
    }

    struct dirent *label_ent;
    while ((label_ent = readdir(root_dir)) != NULL) {
        if (label_ent->d_name[0] == '.') continue;
        if (s_knn_count >= KNN_MAX_TEMPLATES) break;

        char label_path[320];
        snprintf(label_path, sizeof(label_path),
                 "/sdcard/gestures/%s", label_ent->d_name);
        DIR *label_dir = opendir(label_path);
        if (!label_dir) continue;

        struct dirent *file_ent;
        while ((file_ent = readdir(label_dir)) != NULL) {
            if (file_ent->d_name[0] == '.') continue;
            if (s_knn_count >= KNN_MAX_TEMPLATES) break;

            const char *dot = strrchr(file_ent->d_name, '.');
            if (!dot || strcmp(dot, ".bin") != 0) continue;

            char file_path[600];
            snprintf(file_path, sizeof(file_path), "%s/%s",
                     label_path, file_ent->d_name);
            FILE *f = fopen(file_path, "rb");
            if (!f) continue;

            uint32_t magic = 0, ver = 0;
            char     lbl[32] = {0};
            float    ar = 0, fill = 0, cy = 0;
            bool ok = (fread(&magic, 1, 4,  f) == 4) &&
                      (fread(&ver,   1, 4,  f) == 4) &&
                      (fread(lbl,    1, 32, f) == 32) &&
                      (fread(&ar,    1, 4,  f) == 4) &&
                      (fread(&fill,  1, 4,  f) == 4) &&
                      (fread(&cy,    1, 4,  f) == 4) &&
                      (magic == 0x46454154U);  /* 'FEAT' */

            if (ok) {
                strncpy(s_knn_tpl[s_knn_count].label, label_ent->d_name, 31);
                s_knn_tpl[s_knn_count].label[31] = '\0';
                s_knn_tpl[s_knn_count].ar   = ar;
                s_knn_tpl[s_knn_count].fill = fill;
                s_knn_tpl[s_knn_count].cy   = cy;
                s_knn_count++;
            }
            fclose(f);
        }
        closedir(label_dir);
    }
    closedir(root_dir);

    ESP_LOGI(TAG, "KNN: loaded %d gesture feature templates", s_knn_count);
}

const char *gesture_knn_classify(float ar, float fill, float cy_norm)
{
    if (!s_knn_tpl || s_knn_count == 0) return NULL;

    float best_d = 1e9f;
    int   best_i = 0;
    for (int i = 0; i < s_knn_count; i++) {
        /* Weighted Euclidean distance – ar weighted 2x (most discriminative) */
        float da = ar      - s_knn_tpl[i].ar;
        float df = fill    - s_knn_tpl[i].fill;
        float dc = cy_norm - s_knn_tpl[i].cy;
        float d  = da*da*2.0f + df*df + dc*dc*0.5f;
        if (d < best_d) { best_d = d; best_i = i; }
    }
    return s_knn_tpl[best_i].label;
}

int gesture_knn_count(void) { return s_knn_count; }

/* Delete all gesture template files from SD and clear the in-memory index. */
static void delete_dir_contents(const char *path)
{
    DIR *d = opendir(path);
    if (!d) return;
    struct dirent *e;
    char buf[512];
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        snprintf(buf, sizeof(buf), "%s/%s", path, e->d_name);
        if (e->d_type == DT_DIR) {
            delete_dir_contents(buf);
            rmdir(buf);
        } else {
            remove(buf);
        }
    }
    closedir(d);
}

void training_clear_gesture_templates(void)
{
    s_knn_count = 0;
    if (sd_is_mounted())
        delete_dir_contents("/sdcard/gestures");
    ESP_LOGI(TAG, "All gesture templates cleared (RAM + SD)");
}
