/*
 * MIRA ESP32 Web Server - Safe API Endpoints
 * 
 * This header defines the REST API endpoints that the robot hardware
 * exposes to the Python backend orchestrator.
 * 
 * IMPORTANT: AI never sends raw servo values. All commands are high-level
 * and converted to safe movements by this firmware.
 */

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/*
 * ==================== SAFE MOTION ENDPOINTS ====================
 * 
 * POST /api/servo/set
 * Body: {"pan": 90, "tilt": 90, "speed": "slow"}
 * 
 * Response: {"success": true, "pan": 90, "tilt": 90}
 */

/* POST /api/motion/look
 * Body: {"direction": "left|right|center|up|down", "speed": "slow|medium|fast"}
 */

/* POST /api/motion/gesture
 * Body: {"gesture": "nod|shake_head", "intensity": 0.5}
 */

/* POST /api/motion/idle
 * Trigger subtle idle motion
 */

/* POST /api/motion/stop
 * EMERGENCY STOP - disable all motion immediately
 */

/*
 * ==================== DISPLAY ENDPOINTS ====================
 * 
 * POST /api/display/mode
 * Body: {"mode": "face|text|image|webpage"}
 */

/* POST /api/display/text
 * Body: {"title": "string", "body": "string"}
 */

/* POST /api/display/image
 * Body: {"url": "string"}
 */

/* POST /api/display/webpage
 * Body: {"url": "string"}
 */

/*
 * ==================== CAMERA ENDPOINTS ====================
 */

/* GET /api/camera/capture
 * Capture single frame
 */

/* GET /api/camera/stream
 * Video stream endpoint
 */

/*
 * ==================== STATUS ENDPOINTS ====================
 */

/* GET /api/status
 * Response: {
 *   "pan": 90,
 *   "tilt": 90,
 *   "battery": 85,
 *   "wifi_rssi": -45,
 *   "uptime": 12345,
 *   "display_mode": "face"
 * }
 */

/*
 * ==================== IMPLEMENTATION NOTES ====================
 * 
 * Safety Rules:
 * 1. All servo angles clamped to 0-180 degrees
 * 2. Speed limited to prevent mechanical damage
 * 3. Smooth interpolation between positions
 * 4. Emergency stop accessible from any state
 * 5. Watchdog timer for stuck servos
 * 6. Log all motion commands for debugging
 * 
 * Display Modes:
 * - FACE: Robot face animation (idle)
 * - TEXT: Title + body text display
 * - IMAGE: Full-screen image
 * - WEBPAGE: Embedded browser view
 * - TIMELINE: Timeline graphic
 * - EPISODE: Episode structure view
 * 
 * Communication:
 * - HTTP REST API (JSON)
 * - WebSocket for real-time updates
 * - MQTT for pub/sub (optional)
 */

#ifdef __cplusplus
}
#endif
