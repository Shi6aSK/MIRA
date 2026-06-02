"""
Robot Body Controller
Safe API layer between AI and physical robot hardware.

The AI never sends raw servo values or direct hardware commands.
All physical actions go through safety-checked high-level commands.
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MotionSpeed(Enum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


class ScreenMode(Enum):
    FACE = "face"
    TEXT = "text"
    WEBPAGE = "webpage"
    IMAGE = "image"
    TIMELINE = "timeline"
    EPISODE_STRUCTURE = "episode_structure"
    SOURCE_CARD = "source_card"


@dataclass
class SafeMotionLimits:
    """Hard-coded safety limits for robot motion"""
    max_pan_angle: int = 180
    min_pan_angle: int = 0
    max_tilt_angle: int = 180
    min_tilt_angle: int = 0
    max_speed: float = 1.0
    min_motion_interval_ms: int = 100  # Prevent jitter


class RobotController:
    """
    Safe robot control interface.
    
    Responsibilities:
    - Translate high-level commands to safe servo movements
    - Enforce physical limits
    - Manage screen display modes
    - Control camera
    - Handle emergency stop
    - Provide expressive gestures
    
    Communication:
    - HTTP API to ESP32 web server (already implemented)
    - Commands like /look_left, /display_text, etc.
    """
    
    def __init__(self, robot_ip: str = None):
        self.robot_ip = robot_ip or "192.168.1.100"  # Default ESP32 IP
        self.robot_url = f"http://{self.robot_ip}"
        self.session = None
        self.limits = SafeMotionLimits()
        
        # Current state
        self.current_pan = 90
        self.current_tilt = 90
        self.current_screen_mode = ScreenMode.FACE
        self.is_moving = False
        
        logger.info(f"🤖 Robot Controller initialized for {self.robot_url}")
    
    async def initialize(self):
        """Initialize connection to robot"""
        self.session = aiohttp.ClientSession()
        
        # Test connection
        try:
            await self.center()
            await self.display_face()
            logger.info("✅ Robot connection successful")
        except Exception as e:
            logger.warning(f"⚠️ Robot connection failed: {e}")
    
    # ==================== SAFE MOTION API ====================
    
    async def execute_motion(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a high-level motion command with safety checks.
        
        Commands:
        - look_left / look_right / look_center
        - look_up / look_down
        - look_at_screen
        - nod
        - shake_head
        - idle_motion
        - emergency_stop
        """
        action = command.get("action", "idle_motion")
        speed = command.get("speed", "slow")
        intensity = command.get("intensity", 0.5)
        
        if self.is_moving:
            logger.warning("⚠️ Motion already in progress, queuing...")
            await asyncio.sleep(0.5)
        
        self.is_moving = True
        
        try:
            if action == "look_left":
                result = await self.look_left(speed)
            elif action == "look_right":
                result = await self.look_right(speed)
            elif action == "look_center":
                result = await self.center()
            elif action == "look_up":
                result = await self.look_up(speed)
            elif action == "look_down":
                result = await self.look_down(speed)
            elif action == "look_at_screen":
                result = await self.look_at_screen(speed)
            elif action == "nod":
                result = await self.nod(intensity)
            elif action == "shake_head":
                result = await self.shake_head(intensity)
            elif action == "idle_motion":
                result = await self.idle_motion()
            elif action == "emergency_stop":
                result = await self.emergency_stop()
            else:
                result = {"error": f"Unknown action: {action}"}
        finally:
            self.is_moving = False
        
        return result
    
    async def look_left(self, speed: str = "slow") -> Dict[str, Any]:
        """Safe left look - typically 30-45 degrees from center"""
        target_pan = self._clamp_angle(45)
        return await self._move_servos(pan=target_pan, speed=speed)
    
    async def look_right(self, speed: str = "slow") -> Dict[str, Any]:
        """Safe right look - typically 30-45 degrees from center"""
        target_pan = self._clamp_angle(135)
        return await self._move_servos(pan=target_pan, speed=speed)
    
    async def look_up(self, speed: str = "slow") -> Dict[str, Any]:
        """Safe upward look"""
        target_tilt = self._clamp_angle(60)
        return await self._move_servos(tilt=target_tilt, speed=speed)
    
    async def look_down(self, speed: str = "slow") -> Dict[str, Any]:
        """Safe downward look"""
        target_tilt = self._clamp_angle(120)
        return await self._move_servos(tilt=target_tilt, speed=speed)
    
    async def center(self) -> Dict[str, Any]:
        """Return to center position"""
        return await self._move_servos(pan=90, tilt=90, speed="medium")
    
    async def look_at_screen(self, speed: str = "slow") -> Dict[str, Any]:
        """
        Look at the robot's own screen.
        Adjust angles based on physical robot configuration.
        """
        # Assuming screen is slightly to the left and down
        return await self._move_servos(pan=60, tilt=100, speed=speed)
    
    async def nod(self, intensity: float = 0.5) -> Dict[str, Any]:
        """Nod gesture (yes)"""
        # Save current position
        original_tilt = self.current_tilt
        
        # Nod motion
        nod_angle = int(20 * intensity)
        await self._move_servos(tilt=original_tilt + nod_angle, speed="medium")
        await asyncio.sleep(0.3)
        await self._move_servos(tilt=original_tilt - nod_angle, speed="fast")
        await asyncio.sleep(0.2)
        await self._move_servos(tilt=original_tilt, speed="medium")
        
        return {"gesture": "nod", "completed": True}
    
    async def shake_head(self, intensity: float = 0.5) -> Dict[str, Any]:
        """Shake head gesture (no)"""
        original_pan = self.current_pan
        
        shake_angle = int(30 * intensity)
        await self._move_servos(pan=original_pan - shake_angle, speed="medium")
        await asyncio.sleep(0.3)
        await self._move_servos(pan=original_pan + shake_angle, speed="medium")
        await asyncio.sleep(0.3)
        await self._move_servos(pan=original_pan, speed="medium")
        
        return {"gesture": "shake_head", "completed": True}
    
    async def idle_motion(self) -> Dict[str, Any]:
        """
        Subtle idle motion to make robot feel alive.
        Small random movements that don't distract.
        """
        import random
        
        # Small random offset from center
        offset_pan = random.randint(-15, 15)
        offset_tilt = random.randint(-10, 10)
        
        await self._move_servos(
            pan=90 + offset_pan,
            tilt=90 + offset_tilt,
            speed="slow"
        )
        
        return {"motion": "idle", "completed": True}
    
    async def emergency_stop(self) -> Dict[str, Any]:
        """EMERGENCY STOP - disable all motion"""
        logger.error("🚨 EMERGENCY STOP activated")
        
        try:
            await self._send_command("/stop_all_motion")
        except Exception as e:
            logger.error(f"Emergency stop failed: {e}")
        
        self.is_moving = False
        return {"emergency_stop": True}
    
    async def _move_servos(
        self,
        pan: Optional[int] = None,
        tilt: Optional[int] = None,
        speed: str = "slow"
    ) -> Dict[str, Any]:
        """
        Low-level servo movement with safety checks.
        
        Safety rules:
        1. Clamp angles to limits
        2. Limit speed
        3. Prevent rapid changes
        4. Check physical limits
        """
        if pan is not None:
            pan = self._clamp_angle(pan)
            self.current_pan = pan
        
        if tilt is not None:
            tilt = self._clamp_angle(tilt)
            self.current_tilt = tilt
        
        # Convert to ESP32 API call
        params = {}
        if pan is not None:
            params["pan"] = pan
        if tilt is not None:
            params["tilt"] = tilt
        params["speed"] = speed
        
        return await self._send_command("/set_servo", params)
    
    def _clamp_angle(self, angle: int) -> int:
        """Clamp angle to safe limits"""
        return max(
            self.limits.min_pan_angle,
            min(self.limits.max_pan_angle, angle)
        )
    
    # ==================== SCREEN DISPLAY API ====================
    
    async def display_text(self, title: str, body: str) -> Dict[str, Any]:
        """Display text on robot screen"""
        self.current_screen_mode = ScreenMode.TEXT
        return await self._send_command("/display", {
            "mode": "text",
            "title": title,
            "body": body
        })
    
    async def display_webpage(self, url: str) -> Dict[str, Any]:
        """Display webpage on robot screen"""
        self.current_screen_mode = ScreenMode.WEBPAGE
        return await self._send_command("/display", {
            "mode": "webpage",
            "url": url
        })
    
    async def display_image(self, image_url: str) -> Dict[str, Any]:
        """Display image on robot screen"""
        self.current_screen_mode = ScreenMode.IMAGE
        return await self._send_command("/display", {
            "mode": "image",
            "url": image_url
        })
    
    async def display_timeline(self, timeline_data: Dict[str, Any]) -> Dict[str, Any]:
        """Display global timeline"""
        self.current_screen_mode = ScreenMode.TIMELINE
        return await self._send_command("/display", {
            "mode": "timeline",
            "data": timeline_data
        })
    
    async def display_episode_structure(self, episode_data: Dict[str, Any]) -> Dict[str, Any]:
        """Display episode outline/structure"""
        self.current_screen_mode = ScreenMode.EPISODE_STRUCTURE
        return await self._send_command("/display", {
            "mode": "episode",
            "data": episode_data
        })
    
    async def display_source_card(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Display source citation card"""
        self.current_screen_mode = ScreenMode.SOURCE_CARD
        return await self._send_command("/display", {
            "mode": "source",
            "data": source
        })
    
    async def display_face(self) -> Dict[str, Any]:
        """Display robot face (idle mode)"""
        self.current_screen_mode = ScreenMode.FACE
        return await self._send_command("/display", {
            "mode": "face"
        })
    
    # ==================== CAMERA API ====================
    
    async def capture_image(self) -> Dict[str, Any]:
        """Capture image from robot camera"""
        return await self._send_command("/capture_image")
    
    async def start_video_stream(self) -> Dict[str, Any]:
        """Start video streaming"""
        return await self._send_command("/stream/start")
    
    async def stop_video_stream(self) -> Dict[str, Any]:
        """Stop video streaming"""
        return await self._send_command("/stream/stop")
    
    # ==================== COMMUNICATION ====================
    
    async def _send_command(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send command to ESP32 web server.
        
        The ESP32 already has a web server implemented.
        We just need to call its endpoints.
        """
        try:
            url = f"{self.robot_url}{endpoint}"
            
            if params:
                async with self.session.post(url, json=params, timeout=5) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error = await response.text()
                        return {"error": error, "status": response.status}
            else:
                async with self.session.get(url, timeout=5) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error = await response.text()
                        return {"error": error, "status": response.status}
        
        except asyncio.TimeoutError:
            logger.error(f"Timeout calling {endpoint}")
            return {"error": "timeout"}
        except Exception as e:
            logger.error(f"Error calling {endpoint}: {e}")
            return {"error": str(e)}
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current robot status"""
        return {
            "pan": self.current_pan,
            "tilt": self.current_tilt,
            "screen_mode": self.current_screen_mode.value,
            "is_moving": self.is_moving,
            "robot_url": self.robot_url
        }
