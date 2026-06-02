// vision_pipeline.cpp
//
// Stage 1: Face detection via ESP-DL HumanFaceDetect (MSR+MNP model).
// Stage 2: If face is present, run skin-blob BFS for gesture detection.
// Drives OLED eyes and pan-tilt servos.

#include "human_face_detect.hpp"

extern "C" {
#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "vision_pipeline.h"
#include "vision_config.h"
#include "vision_types.h"
#include "servo_control.h"
#include "oled_control.h"
#include "training.h"
}

static const char *TAG = "vision";

static HumanFaceDetect  *s_det   = nullptr;
static detection_t       s_state = {};
static SemaphoreHandle_t s_mutex = nullptr;

/* ── Skin-tone classifier (YCbCr – proposal Stage 4) ─────────── */
static inline bool is_skin(int r, int g, int b)
{
    if (r < 95 || g < 40 || b < 20) return false;
    int mx = (r > g ? r : g); if (b > mx) mx = b;
    int mn = (r < g ? r : g); if (b < mn) mn = b;
    if ((mx - mn) <= 15 || r <= g || r <= b || abs(r - g) <= 15) return false;
    int cb = 128 + ((-43 * r - 85 * g + 128 * b) >> 8);
    int cr = 128 + (( 128 * r - 107 * g -  21 * b) >> 8);
    return (cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173);
}

/* ── Hand blob via BFS (proposal Stage 4+5) ──────────────────── */
#define GW (FRAME_WIDTH  / BLOCK_SIZE)
#define GH (FRAME_HEIGHT / BLOCK_SIZE)

static uint8_t s_mask[GW * GH];
static uint8_t s_vis [GW * GH];
static int     s_q   [GW * GH];
/* Last computed blob features – exposed for gesture training capture */
static float s_last_ar   = 1.0f;
static float s_last_fill = 0.5f;
static float s_last_cy   = 0.5f;

/* fx1..fy2 = face bounding box in pixels. Those grid cells are zeroed before
 * BFS so the face skin (always the largest blob) can't win over the hand. */
static bool detect_hand(const uint8_t *rgb565, int w, int h, detection_t *out,
                         int fx1, int fy1, int fx2, int fy2)
{
    const int gw = w / BLOCK_SIZE, gh = h / BLOCK_SIZE;
    memset(s_mask, 0, (size_t)(gw * gh));
    memset(s_vis,  0, (size_t)(gw * gh));

    for (int by = 0; by < gh; by++) {
        for (int bx = 0; bx < gw; bx++) {
            int skin = 0, tot = 0;
            for (int dy = 0; dy < BLOCK_SIZE; dy++) {
                const uint8_t *row = rgb565 + (by * BLOCK_SIZE + dy) * w * 2;
                for (int dx = 0; dx < BLOCK_SIZE; dx++) {
                    int pi = (bx * BLOCK_SIZE + dx) * 2;
                    // RGB565 BE: row[pi]=RRRRRGG, row[pi+1]=GGGBBBBB
                    int r  =  row[pi]   & 0xF8;
                    int g  = (((row[pi] & 0x07) << 3) | (row[pi + 1] >> 5)) << 2;
                    int b  =  (row[pi + 1] & 0x1F) << 3;
                    if (is_skin(r, g, b)) skin++;
                    tot++;
                }
            }
            if (tot > 0 && (float)skin / tot >= BLOCK_MIN_SKIN_RATIO)
                s_mask[by * gw + bx] = 1;
        }
    }

    /* Erase the face region from the skin grid. Without this the face is always
     * the largest blob (neck + cheeks >> hand area) and gesture features are
     * computed from the face shape instead of the hand shape. */
    {
        int fbx1 = fx1 / BLOCK_SIZE, fby1 = fy1 / BLOCK_SIZE;
        int fbx2 = fx2 / BLOCK_SIZE, fby2 = fy2 / BLOCK_SIZE;
        /* Expand the face mask by 1 block in each direction to catch
         * neck/chin skin that bleeds outside the tight face bbox. */
        fbx1 = (fbx1 > 0)     ? fbx1 - 1 : 0;
        fby1 = (fby1 > 0)     ? fby1 - 1 : 0;
        fbx2 = (fbx2 < gw-1)  ? fbx2 + 1 : gw - 1;
        fby2 = (fby2 < gh-1)  ? fby2 + 1 : gh - 1;
        for (int mby = fby1; mby <= fby2; mby++)
            for (int mbx = fbx1; mbx <= fbx2; mbx++)
                s_mask[mby * gw + mbx] = 0;
    }

    int best = 0, bx1 = 0, by1 = 0, bx2 = 0, by2 = 0;
    for (int i = 0; i < gw * gh; i++) {
        if (!s_mask[i] || s_vis[i]) continue;
        int head = 0, tail = 0;
        s_q[tail++] = i; s_vis[i] = 1;
        int area = 0, mnx = gw, mny = gh, mxx = -1, mxy = -1;
        while (head < tail) {
            int cur = s_q[head++], cy = cur / gw, cx = cur % gw;
            area++;
            if (cx < mnx) mnx = cx;
            if (cy < mny) mny = cy;
            if (cx > mxx) mxx = cx;
            if (cy > mxy) mxy = cy;
            int nb[4][2] = {{cx+1,cy},{cx-1,cy},{cx,cy+1},{cx,cy-1}};
            for (int n = 0; n < 4; n++) {
                int nx = nb[n][0], ny = nb[n][1];
                if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
                int ni = ny * gw + nx;
                if (s_mask[ni] && !s_vis[ni]) { s_vis[ni] = 1; s_q[tail++] = ni; }
            }
        }
        if (area > best) { best = area; bx1 = mnx; by1 = mny; bx2 = mxx; by2 = mxy; }
    }

    if (best < MIN_BLOB_CELLS) return false;

    out->object_present = true;
    out->x1 = bx1 * BLOCK_SIZE;       out->y1 = by1 * BLOCK_SIZE;
    out->x2 = (bx2 + 1) * BLOCK_SIZE - 1; out->y2 = (by2 + 1) * BLOCK_SIZE - 1;
    strcpy(out->kind, "hand");
    /* Compute normalized geometric features – invariant to position and scale.
     * ar   = aspect ratio (bbox width / height in grid cells)
     * fill = fraction of bbox grid cells that are skin
     * cy_n = normalized vertical centroid of skin mass (0=top, 1=bottom) */
    float ar    = (by2 > by1) ? (float)(bx2 - bx1 + 1) / (float)(by2 - by1 + 1) : 1.0f;
    float denom = (float)((bx2 - bx1 + 1) * (by2 - by1 + 1));
    float fill  = (denom > 0.0f) ? (float)best / denom : 0.5f;
    float sum_y = 0.0f, cnt_f = 0.0f;
    for (int gy = by1; gy <= by2; gy++)
        for (int gx = bx1; gx <= bx2; gx++)
            if (s_mask[gy * gw + gx]) { sum_y += (float)(gy - by1); cnt_f += 1.0f; }
    float cy_n = (cnt_f > 0.0f && by2 > by1) ? sum_y / cnt_f / (float)(by2 - by1) : 0.5f;
    s_last_ar = ar; s_last_fill = fill; s_last_cy = cy_n;
    /* Use KNN on feature vector when templates are loaded; reliable geometric
     * heuristic otherwise – both are position/scale invariant.
     * Thresholds measured with face region masked out:
     *   open_palm : spread fingers → wide blob, high fill.  ar≥0.75, fill≥0.45
     *   point     : single upright finger → tall narrow blob, low fill.  ar<0.65
     *   hand      : fist / ambiguous – no action, but still captured in training */
    const char *knn_label = gesture_knn_classify(ar, fill, cy_n);
    if (knn_label) {
        strncpy(out->gesture, knn_label, sizeof(out->gesture) - 1);
        out->gesture[sizeof(out->gesture) - 1] = '\0';
    } else {
        if      (ar >= 0.75f && fill >= 0.45f) strcpy(out->gesture, "open_palm");
        else if (ar <  0.65f && fill <  0.55f) strcpy(out->gesture, "point");
        else                                   strcpy(out->gesture, "hand");
    }
    int cx = (out->x1 + out->x2) / 2;
    if      (cx < w / 3)      strcpy(out->side, "left");
    else if (cx > 2 * w / 3)  strcpy(out->side, "right");
    else                      strcpy(out->side, "center");
    return true;
}

/* ── Public C API ────────────────────────────────────────────── */
extern "C" {

void vision_init(void)
{
    s_mutex = xSemaphoreCreateMutex();
    strcpy(s_state.kind, "none"); strcpy(s_state.gesture, "none"); strcpy(s_state.side, "none");

    s_det = new HumanFaceDetect(HumanFaceDetect::MSRMNP_S8_V1, /*lazy_load=*/false);
    if (s_det) {
        s_det->set_score_thr(FACE_SCORE_MSR, 0);
        s_det->set_score_thr(FACE_SCORE_MNP, 1);
        ESP_LOGW(TAG, "HumanFaceDetect ready (thr=%.2f/%.2f)", FACE_SCORE_MSR, FACE_SCORE_MNP);
    } else {
        ESP_LOGE(TAG, "HumanFaceDetect alloc failed – PSRAM enabled?");
    }
}

void vision_process_frame(camera_fb_t *fb)
{
    if (!fb || fb->format != PIXFORMAT_RGB565) return;

    detection_t d = {};
    d.frame_id = s_state.frame_id + 1;
    strcpy(d.kind, "none"); strcpy(d.gesture, "none"); strcpy(d.side, "none");

    bool face_found = false;

    if (s_det) {
        dl::image::img_t img = {};
        img.data     = fb->buf;
        img.width    = (int)fb->width;
        img.height   = (int)fb->height;
        img.pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565BE;

        auto &results = s_det->run(img);
        if (!results.empty()) {
            const auto &r = results.front();
            d.object_present = true; d.score = r.score;
            d.x1 = r.box[0]; d.y1 = r.box[1];
            d.x2 = r.box[2]; d.y2 = r.box[3];
            if (d.x1 < 0)              d.x1 = 0;
            if (d.y1 < 0)              d.y1 = 0;
            if (d.x2 >= (int)fb->width)  d.x2 = fb->width  - 1;
            if (d.y2 >= (int)fb->height) d.y2 = fb->height - 1;

            strcpy(d.kind, "face"); strcpy(d.gesture, "none");
            int cx = (d.x1 + d.x2) / 2, cy = (d.y1 + d.y2) / 2;
            if      (cx < (int)fb->width / 3)      strcpy(d.side, "left");
            else if (cx > 2 * (int)fb->width / 3)  strcpy(d.side, "right");
            else                                    strcpy(d.side, "center");

            /* pdx: positive = pupils right on display. Face right-of-centre → pupils right.
             * pdy: positive = pupils down. Face below centre → pupils down. */
            int pdx =  (int)((float)(cx - (int)fb->width  / 2) / (fb->width  / 2) * 20.0f);
            int pdy =  (int)((float)(cy - (int)fb->height / 2) / (fb->height / 2) *  6.0f);
            oled_draw_eyes(pdx, pdy, true);
            servo_update_tracking(&d, (int)fb->width, (int)fb->height);
            face_found = true;
        }
    }

    if (face_found) {
        detection_t hand = {};
        strcpy(hand.kind, "none");
        strcpy(hand.gesture, "none");
        strcpy(hand.side, "none");
        if (detect_hand(fb->buf, (int)fb->width, (int)fb->height, &hand,
                         d.x1, d.y1, d.x2, d.y2)) {
            strncpy(d.gesture, hand.gesture, sizeof(d.gesture) - 1);
            d.gesture[sizeof(d.gesture) - 1] = '\0';
            d.hx1 = hand.x1; d.hy1 = hand.y1;
            d.hx2 = hand.x2; d.hy2 = hand.y2;
        }
    } else {
        oled_draw_sleep();
    }

    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_state = d;
    xSemaphoreGive(s_mutex);
}

detection_t vision_get_detection(void)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    detection_t d = s_state;
    xSemaphoreGive(s_mutex);
    return d;
}

void vision_get_blob_features(float *ar, float *fill, float *cy_norm)
{
    if (ar)      *ar      = s_last_ar;
    if (fill)    *fill    = s_last_fill;
    if (cy_norm) *cy_norm = s_last_cy;
}

} // extern "C"

