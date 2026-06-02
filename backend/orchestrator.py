"""
MIRA - Multi-Intelligence Robotic Agent
Main Orchestrator for "From Stones to AGI" Project

This is the brain of the system that routes tasks to the appropriate
AI model, robot controller, browser agent, or content pipeline.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Classify incoming requests into task categories"""
    CASUAL_DIALOGUE = "casual_dialogue"
    RESEARCH = "research"
    ROBOT_MOTION = "robot_motion"
    CONTENT_WRITING = "content_writing"
    WEB_BROWSING = "web_browsing"
    EPISODE_PRODUCTION = "episode_production"
    MEMORY_QUERY = "memory_query"
    VISUAL_ANALYSIS = "visual_analysis"
    TIMELINE_GENERATION = "timeline_generation"


class AIModel(Enum):
    """Available AI model backends"""
    OLLAMA_LOCAL = "ollama_local"
    OPENAI_CLOUD = "openai_cloud"
    HERMES_MEMORY = "hermes_memory"
    DETERMINISTIC = "deterministic"


@dataclass
class Task:
    """Structured task representation"""
    task_type: TaskType
    content: str
    context: Dict[str, Any]
    preferred_model: Optional[AIModel] = None
    requires_safety_check: bool = False


class Orchestrator:
    """
    Main orchestrator that manages the entire MIRA system.
    
    Responsibilities:
    - Classify incoming requests
    - Route to appropriate AI model
    - Coordinate between robot, browser, memory, and content systems
    - Enforce safety gates
    - Manage multi-step workflows
    """
    
    def __init__(self):
        self.ai_router = None
        self.robot_controller = None
        self.browser_controller = None
        self.memory_system = None
        self.content_pipeline = None
        self.knowledge_db = None
        
        logger.info("🧠 MIRA Orchestrator initialized")
    
    async def initialize(self):
        """Initialize all subsystems"""
        from ai_router import AIRouter
        from robot_controller import RobotController
        from browser_controller import BrowserController
        from memory_system import MemorySystem
        from content_pipeline import ContentPipeline
        from knowledge_database import KnowledgeDatabase
        
        self.ai_router = AIRouter()
        self.robot_controller = RobotController()
        self.browser_controller = BrowserController()
        self.memory_system = MemorySystem()
        self.content_pipeline = ContentPipeline()
        self.knowledge_db = KnowledgeDatabase()
        
        await self.ai_router.initialize()
        await self.robot_controller.initialize()
        await self.browser_controller.initialize()
        await self.memory_system.initialize()
        
        logger.info("✅ All subsystems initialized")
    
    async def classify_task(self, user_input: str, context: Dict[str, Any]) -> Task:
        """
        Classify user input into appropriate task type.
        Uses lightweight classification (could use local model or rules).
        """
        user_lower = user_input.lower()
        
        # Research indicators
        if any(word in user_lower for word in ["research", "find sources", "investigate", "study"]):
            return Task(TaskType.RESEARCH, user_input, context)
        
        # Robot motion indicators
        if any(word in user_lower for word in ["look", "move", "turn", "nod", "gesture"]):
            return Task(TaskType.ROBOT_MOTION, user_input, context, requires_safety_check=True)
        
        # Content creation indicators
        if any(word in user_lower for word in ["episode", "script", "write", "create content"]):
            return Task(TaskType.EPISODE_PRODUCTION, user_input, context)
        
        # Browser indicators
        if any(word in user_lower for word in ["show me", "display", "open", "browse", "search"]):
            return Task(TaskType.WEB_BROWSING, user_input, context)
        
        # Timeline indicators
        if any(word in user_lower for word in ["timeline", "when", "simultaneous", "global"]):
            return Task(TaskType.TIMELINE_GENERATION, user_input, context)
        
        # Default to casual dialogue
        return Task(TaskType.CASUAL_DIALOGUE, user_input, context)
    
    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """
        Execute a classified task using the appropriate subsystems.
        This is where the magic happens - breaking down complex requests
        into coordinated actions across multiple systems.
        """
        logger.info(f"🎯 Executing task: {task.task_type.value}")
        
        if task.task_type == TaskType.CASUAL_DIALOGUE:
            return await self._handle_casual_dialogue(task)
        
        elif task.task_type == TaskType.RESEARCH:
            return await self._handle_research(task)
        
        elif task.task_type == TaskType.ROBOT_MOTION:
            return await self._handle_robot_motion(task)
        
        elif task.task_type == TaskType.EPISODE_PRODUCTION:
            return await self._handle_episode_production(task)
        
        elif task.task_type == TaskType.WEB_BROWSING:
            return await self._handle_web_browsing(task)
        
        elif task.task_type == TaskType.TIMELINE_GENERATION:
            return await self._handle_timeline_generation(task)
        
        else:
            return {"error": "Unknown task type"}
    
    async def _handle_casual_dialogue(self, task: Task) -> Dict[str, Any]:
        """Handle simple conversation - use local Ollama for speed"""
        response = await self.ai_router.query(
            task.content,
            model=AIModel.OLLAMA_LOCAL,
            context=task.context
        )
        
        # Simple gestures during conversation
        await self.robot_controller.idle_motion()
        
        return {
            "response": response,
            "model_used": "ollama_local"
        }
    
    async def _handle_research(self, task: Task) -> Dict[str, Any]:
        """
        Handle deep research tasks.
        
        Example: "Research fire as a technology and connect it to digestion, 
                 myth, social cooperation, and AI."
        
        Steps:
        1. Check memory for existing knowledge
        2. Search web for sources
        3. Use cloud AI for deep analysis
        4. Save findings to knowledge base
        5. Display key findings on screen
        """
        logger.info("🔍 Starting research workflow")
        
        # Step 1: Check memory
        memory_results = await self.memory_system.query(task.content)
        
        # Step 2: Web search
        search_results = await self.browser_controller.search(task.content)
        
        # Step 3: Cloud AI analysis
        analysis_prompt = f"""
        Research task: {task.content}
        
        Existing knowledge: {memory_results}
        New sources found: {search_results}
        
        Provide:
        1. Key findings
        2. Source citations
        3. Global perspective (check multiple regions/cultures)
        4. Connection to human technology evolution
        5. Potential episode angles
        """
        
        analysis = await self.ai_router.query(
            analysis_prompt,
            model=AIModel.OPENAI_CLOUD,
            context={"task_type": "research"}
        )
        
        # Step 4: Save to knowledge base
        await self.knowledge_db.save_research(task.content, analysis, search_results)
        
        # Step 5: Display on screen
        await self.robot_controller.display_text(
            title="Research Complete",
            body=analysis.get("summary", "")
        )
        
        return {
            "analysis": analysis,
            "sources": search_results,
            "saved_to_kb": True
        }
    
    async def _handle_robot_motion(self, task: Task) -> Dict[str, Any]:
        """
        Handle robot physical movements with SAFETY GATES.
        
        The AI never sends raw servo values.
        It requests high-level actions that are converted to safe movements.
        """
        if task.requires_safety_check:
            logger.warning("⚠️ Motion command requires safety check")
        
        # Extract motion intent (could use AI here too)
        motion_command = await self._parse_motion_intent(task.content)
        
        # Execute safe motion
        result = await self.robot_controller.execute_motion(motion_command)
        
        return {
            "motion_executed": motion_command,
            "result": result
        }
    
    async def _handle_episode_production(self, task: Task) -> Dict[str, Any]:
        """
        Handle full episode production workflow.
        
        Example: "Prepare an episode on fire"
        
        Workflow:
        1. Search memory for existing research
        2. Build global timeline
        3. Research sources
        4. Create episode outline
        5. Display visual structure
        6. Generate script
        7. Create visual suggestions
        8. Save to project memory
        """
        logger.info("🎬 Starting episode production workflow")
        
        episode_data = await self.content_pipeline.produce_episode(
            task.content,
            orchestrator=self  # Pass self for subsystem access
        )
        
        # Display episode structure on screen
        await self.robot_controller.display_episode_structure(episode_data)
        
        # Robot looks at screen while explaining
        await self.robot_controller.look_at_screen()
        
        return episode_data
    
    async def _handle_web_browsing(self, task: Task) -> Dict[str, Any]:
        """
        Handle web browsing and display.
        Includes safety gates for web actions.
        """
        result = await self.browser_controller.handle_request(task.content)
        
        # Display webpage on robot screen if requested
        if result.get("display_on_screen"):
            await self.robot_controller.display_webpage(result["url"])
            await self.robot_controller.look_at_screen()
        
        return result
    
    async def _handle_timeline_generation(self, task: Task) -> Dict[str, Any]:
        """
        Generate global timeline showing simultaneous developments.
        
        This is key to the "global perspective" requirement.
        """
        logger.info("🗺️ Generating global timeline")
        
        timeline_request = await self._parse_timeline_request(task.content)
        
        # Use cloud AI for deep historical reasoning
        timeline = await self.content_pipeline.generate_global_timeline(
            period=timeline_request.get("period"),
            regions=timeline_request.get("regions", "all"),
            focus=timeline_request.get("focus")
        )
        
        # Display timeline on screen
        await self.robot_controller.display_timeline(timeline)
        
        return {
            "timeline": timeline,
            "display": "shown_on_screen"
        }
    
    async def _parse_motion_intent(self, text: str) -> Dict[str, Any]:
        """Parse natural language motion request into structured command"""
        text_lower = text.lower()
        
        if "left" in text_lower:
            return {"action": "look_left", "speed": "slow"}
        elif "right" in text_lower:
            return {"action": "look_right", "speed": "slow"}
        elif "center" in text_lower or "centre" in text_lower:
            return {"action": "look_center", "speed": "medium"}
        elif "nod" in text_lower:
            return {"action": "nod", "intensity": 0.5}
        elif "screen" in text_lower:
            return {"action": "look_at_screen", "speed": "slow"}
        else:
            return {"action": "idle_motion"}
    
    async def _parse_timeline_request(self, text: str) -> Dict[str, Any]:
        """Parse timeline request"""
        # This could use AI, but for now use simple extraction
        return {
            "period": "unknown",  # Extract from text
            "regions": "all",
            "focus": text
        }
    
    async def process_request(self, user_input: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Main entry point for processing any user request.
        
        This is what the API endpoint calls.
        """
        if context is None:
            context = {}
        
        # Step 1: Classify task
        task = await self.classify_task(user_input, context)
        
        # Step 2: Execute task
        result = await self.execute_task(task)
        
        # Step 3: Log to memory if significant
        if task.task_type in [TaskType.RESEARCH, TaskType.EPISODE_PRODUCTION]:
            await self.memory_system.log_interaction(user_input, result)
        
        return result


# Example usage
async def main():
    orchestrator = Orchestrator()
    await orchestrator.initialize()
    
    # Example: Research task
    result = await orchestrator.process_request(
        "Research fire as a technology and connect it to digestion, myth, and AI"
    )
    print(result)
    
    # Example: Episode production
    result = await orchestrator.process_request(
        "Prepare an episode on stone tools"
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
