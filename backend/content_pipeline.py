"""
Content Production Pipeline
The heart of "From Stones to AGI" episode creation.

Workflow:
1. Research → 2. Timeline → 3. Outline → 4. Script → 5. Visuals → 6. Recording Plan
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class EpisodeStructure:
    """Standard episode template"""
    cold_open: str
    human_problem: str
    technical_invention: str
    global_lens: Dict[str, str]  # region -> developments
    cultural_angle: str
    social_change: str
    technical_principle: str
    link_to_ai: str
    closing_question: str


@dataclass
class GlobalTimeline:
    """Timeline showing simultaneous developments"""
    period: str
    start_year: int
    end_year: int
    regions: Dict[str, List[Dict[str, Any]]]  # region -> events


class ContentPipeline:
    """
    Content production system for "From Stones to AGI".
    
    This is where the show's intellectual spine lives.
    
    Core thesis:
    Technology is the story of humans externalizing themselves.
    Each invention extends something human into the world.
    """
    
    def __init__(self):
        # Define the show's spine - major technological milestones
        self.technology_spine = [
            {"id": 1, "tech": "stone_tools", "extends": "the hand", "era": "~2.6 million years ago"},
            {"id": 2, "tech": "fire", "extends": "digestion, warmth, protection", "era": "~1 million years ago"},
            {"id": 3, "tech": "language", "extends": "shared memory", "era": "~100,000 years ago"},
            {"id": 4, "tech": "ritual_symbol", "extends": "shared meaning", "era": "~70,000 years ago"},
            {"id": 5, "tech": "agriculture", "extends": "control over food", "era": "~10,000 BCE"},
            {"id": 6, "tech": "writing", "extends": "external memory", "era": "~3,200 BCE"},
            {"id": 7, "tech": "mathematics", "extends": "abstraction", "era": "~3,000 BCE"},
            {"id": 8, "tech": "money", "extends": "trust", "era": "~3,000 BCE"},
            {"id": 9, "tech": "mechanical_machines", "extends": "muscle power", "era": "~1st millennium"},
            {"id": 10, "tech": "printing", "extends": "knowledge distribution", "era": "~1450 CE"},
            {"id": 11, "tech": "electricity", "extends": "nervous systems", "era": "~1800s"},
            {"id": 12, "tech": "computers", "extends": "logic", "era": "~1940s"},
            {"id": 13, "tech": "internet", "extends": "collective nervous system", "era": "~1990s"},
            {"id": 14, "tech": "ai", "extends": "pattern recognition", "era": "~2010s"},
            {"id": 15, "tech": "agi", "extends": "possible agency", "era": "~future"},
        ]
        
        # World regions for global perspective
        self.world_regions = [
            "East Africa",
            "North Africa",
            "West Africa",
            "Middle East",
            "South Asia",
            "East Asia",
            "Southeast Asia",
            "Central Asia",
            "Europe",
            "Mesoamerica",
            "South America",
            "North America",
            "Oceania"
        ]
        
        logger.info("🎬 Content Pipeline initialized")
    
    async def produce_episode(
        self,
        topic: str,
        orchestrator: Any  # Reference to main orchestrator
    ) -> Dict[str, Any]:
        """
        Full episode production workflow.
        
        Input: "Prepare an episode on fire"
        
        Output:
        - Research summary
        - Global timeline
        - Episode outline
        - Script draft
        - Visual suggestions
        - Source citations
        """
        logger.info(f"🎬 Starting episode production: {topic}")
        
        # Step 1: Extract tech from spine
        tech_info = self._find_in_spine(topic)
        if not tech_info:
            tech_info = {"tech": topic, "extends": "unknown", "era": "to be researched"}
        
        # Step 2: Research phase
        logger.info("📚 Phase 1: Research")
        research = await self._research_phase(topic, orchestrator)
        
        # Step 3: Timeline phase
        logger.info("🗺️ Phase 2: Global Timeline")
        timeline = await self._timeline_phase(topic, tech_info, orchestrator)
        
        # Step 4: Outline phase
        logger.info("📝 Phase 3: Episode Outline")
        outline = await self._outline_phase(topic, tech_info, research, timeline, orchestrator)
        
        # Step 5: Script phase
        logger.info("✍️ Phase 4: Script Generation")
        script = await self._script_phase(outline, orchestrator)
        
        # Step 6: Visual phase
        logger.info("🎨 Phase 5: Visual Design")
        visuals = await self._visual_phase(outline, orchestrator)
        
        # Step 7: Save to memory
        from memory_system import EpisodeMemory
        episode_number = len(orchestrator.memory_system.episodes) + 1
        episode = EpisodeMemory(
            episode_number=episode_number,
            title=outline["title"],
            focus=topic,
            regions_covered=timeline.get("regions_covered", []),
            concepts=outline.get("concepts", []),
            open_threads=outline.get("open_threads", []),
            sources_used=[s["url"] for s in research.get("sources", [])],
            status="outlined"
        )
        orchestrator.memory_system.save_episode(episode)
        
        return {
            "episode_number": episode_number,
            "title": outline["title"],
            "tech_info": tech_info,
            "research": research,
            "timeline": timeline,
            "outline": outline,
            "script": script,
            "visuals": visuals,
            "status": "ready_for_review"
        }
    
    async def _research_phase(
        self,
        topic: str,
        orchestrator: Any
    ) -> Dict[str, Any]:
        """
        Research phase: gather information and sources.
        
        Research questions:
        1. What human limitation did this solve?
        2. What was happening globally?
        3. What are the cultural interpretations?
        4. What's the technical principle?
        5. How does it connect to AI?
        """
        # Check memory first
        memory_results = await orchestrator.memory_system.query(topic)
        
        # Web research
        sources = await orchestrator.browser_controller.find_sources_for_topic(
            topic,
            min_sources=5
        )
        
        # Deep AI analysis
        research_prompt = f"""Research for "From Stones to AGI" episode on {topic}.

Memory results: {memory_results}

Answer these questions:
1. What human limitation did {topic} solve?
2. When and where did {topic} develop globally?
3. What were different cultural/religious interpretations?
4. What is the core technical principle?
5. How does {topic} connect to modern AI/AGI?

Focus on global perspective. Check developments across:
- Africa
- Middle East
- South Asia
- East Asia
- Europe
- Americas

Cite specific examples. Distinguish myth from evidence."""
        
        analysis = await orchestrator.ai_router.query(
            research_prompt,
            model=orchestrator.ai_router.choose_model_for_task("research")
        )
        
        return {
            "topic": topic,
            "sources": sources,
            "analysis": analysis.get("response", ""),
            "memory_context": memory_results
        }
    
    async def _timeline_phase(
        self,
        topic: str,
        tech_info: Dict[str, Any],
        orchestrator: Any
    ) -> Dict[str, Any]:
        """
        Timeline phase: create global simultaneity view.
        
        This is key to avoiding Western-centric narrative.
        """
        timeline_prompt = f"""Create a global timeline for {topic} in the era {tech_info['era']}.

For each major region, list:
- Key developments related to {topic}
- Simultaneous innovations
- Cultural context
- Connections between regions

Regions to cover:
{', '.join(self.world_regions)}

Format as structured data showing what was happening simultaneously."""
        
        timeline_result = await orchestrator.ai_router.query(
            timeline_prompt,
            model=orchestrator.ai_router.choose_model_for_task("timeline")
        )
        
        return {
            "period": tech_info['era'],
            "focus": topic,
            "global_view": timeline_result.get("response", ""),
            "regions_covered": self.world_regions
        }
    
    async def _outline_phase(
        self,
        topic: str,
        tech_info: Dict[str, Any],
        research: Dict[str, Any],
        timeline: Dict[str, Any],
        orchestrator: Any
    ) -> Dict[str, Any]:
        """
        Outline phase: structure the episode.
        
        Uses the standard episode template:
        1. Cold open
        2. Human problem
        3. Technical invention
        4. Global lens
        5. Cultural angle
        6. Social change
        7. Technical principle
        8. Link to AI
        9. Closing question
        """
        outline_prompt = f"""Create episode outline for: {topic}

Context:
- What it extends: {tech_info['extends']}
- Era: {tech_info['era']}
- Research: {research['analysis'][:500]}...
- Timeline: {timeline['global_view'][:500]}...

Use this structure:

1. COLD OPEN (30 seconds)
   Hook the audience. Poetic, surprising, or provocative opening.
   Example: "A stone in the hand is not just a rock. It is a thought made sharp."

2. HUMAN PROBLEM (1 min)
   What limitation did humans face?

3. TECHNICAL INVENTION (2 min)
   How {topic} solved it. Be specific.

4. GLOBAL LENS (3 min)
   What was happening simultaneously across regions?
   Show parallel developments, not linear progress from one region.

5. CULTURAL ANGLE (2 min)
   How did different cultures interpret {topic}?
   Mythology, religion, philosophy.

6. SOCIAL CHANGE (1.5 min)
   How did {topic} reshape human society?

7. TECHNICAL PRINCIPLE (1 min)
   The core idea behind {topic} that still matters today.

8. LINK TO AI (1 min)
   How does {topic} connect to modern AI/AGI?
   Example: "A tool stores a human decision. AI stores patterns of human language."

9. CLOSING QUESTION (30 seconds)
   Leave audience thinking.

Generate the full outline."""
        
        outline_result = await orchestrator.ai_router.query(
            outline_prompt,
            model=orchestrator.ai_router.choose_model_for_task("episode")
        )
        
        return {
            "title": f"Episode: {topic.title()} - {tech_info['extends'].title()}",
            "topic": topic,
            "structure": outline_result.get("response", ""),
            "concepts": [topic, tech_info['extends'], "human limitation", "externalization"],
            "open_threads": ["symbolic thought", "embodied cognition", "tool use"]
        }
    
    async def _script_phase(
        self,
        outline: Dict[str, Any],
        orchestrator: Any
    ) -> Dict[str, Any]:
        """
        Script phase: turn outline into full narration.
        
        Include:
        - Robot dialogue
        - Screen cues
        - Robot gestures
        - Timing
        """
        script_prompt = f"""Convert this episode outline into a full narration script.

Outline:
{outline['structure']}

Format:
[SCREEN: description]
[ROBOT: gesture]
NARRATION: "spoken text"

Tone: {orchestrator.memory_system.persona.voice}
Avoid: {', '.join(orchestrator.memory_system.persona.avoid)}

Make it conversational but precise. Use "I" (robot narrator).
Include moments where robot looks at screen, gestures, pauses.

Target length: 12 minutes (approximately 1,800 words)."""
        
        script_result = await orchestrator.ai_router.query(
            script_prompt,
            model=orchestrator.ai_router.choose_model_for_task("script")
        )
        
        return {
            "full_script": script_result.get("response", ""),
            "word_count": len(script_result.get("response", "").split()),
            "estimated_duration": "12 minutes"
        }
    
    async def _visual_phase(
        self,
        outline: Dict[str, Any],
        orchestrator: Any
    ) -> Dict[str, Any]:
        """
        Visual phase: suggest what to show on screen.
        
        Types of visuals:
        - Timeline graphics
        - Maps showing global developments
        - Historical images/artifacts
        - Diagrams of technical principles
        - Source cards
        """
        visual_prompt = f"""Suggest visuals for this episode:

{outline['structure']}

For each section, suggest:
- Type of visual (timeline, map, diagram, image, source card)
- What it should show
- Why it helps understanding
- Timing

Be specific about what makes an idea visual."""
        
        visual_result = await orchestrator.ai_router.query(
            visual_prompt,
            model=orchestrator.ai_router.choose_model_for_task("script")
        )
        
        return {
            "visual_plan": visual_result.get("response", ""),
            "types": ["timeline", "map", "diagram", "source_card"]
        }
    
    async def generate_global_timeline(
        self,
        period: str,
        regions: str,
        focus: str
    ) -> Dict[str, Any]:
        """
        Generate standalone global timeline.
        
        Useful for research and display.
        """
        return {
            "period": period,
            "focus": focus,
            "regions": regions,
            "timeline_data": {
                # Would contain structured timeline
                "events": []
            }
        }
    
    def _find_in_spine(self, topic: str) -> Optional[Dict[str, Any]]:
        """Find technology in the show's spine"""
        topic_lower = topic.lower().replace(" ", "_")
        for tech in self.technology_spine:
            if topic_lower in tech["tech"]:
                return tech
        return None
