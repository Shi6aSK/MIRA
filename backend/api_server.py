"""
MIRA FastAPI Server
Main API server for the robotic AI system.

Endpoints:
- /api/chat - conversational interface
- /api/research - research tasks
- /api/episode - episode production
- /api/robot/motion - robot control
- /api/robot/display - screen control
- /api/browser - web actions
- /api/memory - memory queries
"""

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import asyncio

from orchestrator import Orchestrator, TaskType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="MIRA API",
    description="Multi-Intelligence Robotic Agent for 'From Stones to AGI'",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global orchestrator instance
orchestrator: Optional[Orchestrator] = None


# ==================== REQUEST MODELS ====================

class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


class ResearchRequest(BaseModel):
    topic: str
    depth: Optional[str] = "standard"  # quick, standard, deep


class EpisodeRequest(BaseModel):
    topic: str
    episode_number: Optional[int] = None


class RobotMotionRequest(BaseModel):
    action: str  # look_left, look_right, nod, etc.
    speed: Optional[str] = "slow"
    intensity: Optional[float] = 0.5


class DisplayRequest(BaseModel):
    mode: str  # text, webpage, image, timeline, face
    content: Dict[str, Any]


class BrowserRequest(BaseModel):
    action: str  # search, open, screenshot
    query: Optional[str] = None
    url: Optional[str] = None


# ==================== STARTUP/SHUTDOWN ====================

@app.on_event("startup")
async def startup_event():
    """Initialize orchestrator and all subsystems"""
    global orchestrator
    logger.info("🚀 Starting MIRA system...")
    
    orchestrator = Orchestrator()
    await orchestrator.initialize()
    
    logger.info("✅ MIRA system ready")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down MIRA system...")
    
    if orchestrator:
        if orchestrator.ai_router:
            await orchestrator.ai_router.close()
        if orchestrator.robot_controller:
            await orchestrator.robot_controller.close()
        if orchestrator.browser_controller:
            await orchestrator.browser_controller.close()


# ==================== MAIN ENDPOINTS ====================

@app.get("/")
async def root():
    """API root"""
    return {
        "name": "MIRA API",
        "version": "1.0.0",
        "project": "From Stones to AGI",
        "status": "operational",
        "endpoints": {
            "chat": "/api/chat",
            "research": "/api/research",
            "episode": "/api/episode/produce",
            "robot_status": "/api/robot/status",
            "memory": "/api/memory/query"
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "orchestrator": orchestrator is not None,
        "subsystems": {
            "ai_router": orchestrator.ai_router is not None if orchestrator else False,
            "robot": orchestrator.robot_controller is not None if orchestrator else False,
            "browser": orchestrator.browser_controller is not None if orchestrator else False,
            "memory": orchestrator.memory_system is not None if orchestrator else False
        }
    }


# ==================== CONVERSATION ====================

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Main conversational interface.
    Handles any type of request.
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        result = await orchestrator.process_request(
            request.message,
            request.context or {}
        )
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RESEARCH ====================

@app.post("/api/research")
async def research(request: ResearchRequest):
    """
    Dedicated research endpoint.
    Deep research with source finding.
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        from orchestrator import Task, TaskType, AIModel
        
        task = Task(
            task_type=TaskType.RESEARCH,
            content=request.topic,
            context={"depth": request.depth}
        )
        
        result = await orchestrator.execute_task(task)
        return {
            "success": True,
            "research": result
        }
    except Exception as e:
        logger.error(f"Research error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== EPISODE PRODUCTION ====================

@app.post("/api/episode/produce")
async def produce_episode(request: EpisodeRequest):
    """
    Full episode production workflow.
    This is the main content creation pipeline.
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        result = await orchestrator.content_pipeline.produce_episode(
            request.topic,
            orchestrator
        )
        return {
            "success": True,
            "episode": result
        }
    except Exception as e:
        logger.error(f"Episode production error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/episode/list")
async def list_episodes():
    """List all episodes"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        episodes = orchestrator.memory_system.list_episodes()
        return {
            "success": True,
            "episodes": [vars(ep) for ep in episodes],
            "count": len(episodes)
        }
    except Exception as e:
        logger.error(f"Episode list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/episode/{episode_number}")
async def get_episode(episode_number: int):
    """Get specific episode"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        episode = orchestrator.memory_system.get_episode(episode_number)
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        
        return {
            "success": True,
            "episode": vars(episode)
        }
    except Exception as e:
        logger.error(f"Episode retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ROBOT CONTROL ====================

@app.post("/api/robot/motion")
async def robot_motion(request: RobotMotionRequest):
    """
    Control robot motion (safely).
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        command = {
            "action": request.action,
            "speed": request.speed,
            "intensity": request.intensity
        }
        
        result = await orchestrator.robot_controller.execute_motion(command)
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Robot motion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/robot/display")
async def robot_display(request: DisplayRequest):
    """
    Control robot screen display.
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        mode = request.mode
        content = request.content
        
        if mode == "text":
            result = await orchestrator.robot_controller.display_text(
                content.get("title", ""),
                content.get("body", "")
            )
        elif mode == "webpage":
            result = await orchestrator.robot_controller.display_webpage(
                content.get("url", "")
            )
        elif mode == "face":
            result = await orchestrator.robot_controller.display_face()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown display mode: {mode}")
        
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Display error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/robot/status")
async def robot_status():
    """Get robot status"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        status = orchestrator.robot_controller.get_status()
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/robot/emergency_stop")
async def emergency_stop():
    """EMERGENCY STOP"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        result = await orchestrator.robot_controller.emergency_stop()
        return {
            "success": True,
            "emergency_stop": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Emergency stop error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== BROWSER CONTROL ====================

@app.post("/api/browser")
async def browser_action(request: BrowserRequest):
    """
    Browser control with safety gates.
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        action = request.action
        
        if action == "search":
            result = await orchestrator.browser_controller.search(request.query or "")
        elif action == "open":
            result = await orchestrator.browser_controller.open_page(request.url or "", display_on_screen=True)
        elif action == "screenshot":
            result = await orchestrator.browser_controller.screenshot()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown browser action: {action}")
        
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Browser error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== MEMORY ====================

@app.get("/api/memory/query")
async def memory_query(q: str):
    """Query memory system"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        results = await orchestrator.memory_system.query(q)
        return {
            "success": True,
            "query": q,
            "results": results
        }
    except Exception as e:
        logger.error(f"Memory query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/memory/context")
async def memory_context():
    """Get memory context for AI"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        context = orchestrator.memory_system.get_context_for_ai()
        return {
            "success": True,
            "context": context
        }
    except Exception as e:
        logger.error(f"Memory context error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WEBSOCKET ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket for real-time interaction.
    Useful for streaming responses, robot status updates, etc.
    """
    await websocket.accept()
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            
            # Process with orchestrator
            result = await orchestrator.process_request(data, {})
            
            # Send response
            await websocket.send_json(result)
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# ==================== RUN SERVER ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Development mode
        log_level="info"
    )
