"""
Memory System
Multi-layered memory for MIRA.

Memory Types:
1. Project Memory - rules, mission, tone
2. Episode Memory - what's been covered
3. Source Memory - citations and references
4. Persona Memory - robot character
5. Skill Memory - reusable procedures
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProjectMemory:
    """Core project information"""
    project_name: str = "From Stones to AGI"
    mission: str = "Explain the journey from stone tools to AGI with global perspective"
    tone: str = "non-technical but rigorous, academically grounded but accessible"
    lens: str = "global, not Western-only or Eastern-only"
    host: str = "MIRA - robotic narrator"
    audience: str = "curious general audience"
    core_rule: str = "every episode compares simultaneous developments across regions"


@dataclass
class EpisodeMemory:
    """Memory of an episode"""
    episode_number: int
    title: str
    focus: str
    regions_covered: List[str]
    concepts: List[str]
    open_threads: List[str]
    sources_used: List[str]
    script_path: Optional[str] = None
    status: str = "planned"  # planned, researched, scripted, recorded, published


@dataclass
class SourceMemory:
    """Source citation"""
    source_id: str
    title: str
    author: Optional[str]
    url: Optional[str]
    date_accessed: str
    region: Optional[str]
    topic: List[str]
    reliability: str  # high, medium, low
    notes: str
    used_in_episodes: List[int]


@dataclass
class PersonaMemory:
    """Robot character definition"""
    name: str = "MIRA"
    voice: str = "thoughtful, curious, slightly poetic, academically grounded"
    avoid: List[str] = None
    style: str = "global, culturally literate, careful with religion"
    core_question: str = "Why do humans build things that eventually reshape them?"
    
    def __post_init__(self):
        if self.avoid is None:
            self.avoid = [
                "tech-bro futurism",
                "civilization ranking",
                "oversimplified East vs West framing",
                "claiming one culture invented everything"
            ]


@dataclass
class SkillMemory:
    """Reusable procedure/workflow"""
    skill_id: str
    name: str
    description: str
    steps: List[str]
    example_usage: str


class MemorySystem:
    """
    Persistent memory system for MIRA.
    
    Uses:
    - JSON files for structured data (episodes, sources)
    - SQLite for queryable data later
    - Vector database for semantic search (ChromaDB/Qdrant)
    
    For now, starts with simple JSON storage.
    """
    
    def __init__(self, memory_dir: str = "memory"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        
        # Sub-directories
        self.project_dir = self.memory_dir / "project"
        self.episodes_dir = self.memory_dir / "episodes"
        self.sources_dir = self.memory_dir / "sources"
        self.persona_dir = self.memory_dir / "persona"
        self.skills_dir = self.memory_dir / "skills"
        self.interactions_dir = self.memory_dir / "interactions"
        
        for dir in [self.project_dir, self.episodes_dir, self.sources_dir,
                    self.persona_dir, self.skills_dir, self.interactions_dir]:
            dir.mkdir(exist_ok=True)
        
        # Loaded memories
        self.project = None
        self.persona = None
        self.episodes: Dict[int, EpisodeMemory] = {}
        self.sources: Dict[str, SourceMemory] = {}
        self.skills: Dict[str, SkillMemory] = {}
        
        logger.info(f"🧠 Memory System initialized at {self.memory_dir}")
    
    async def initialize(self):
        """Load memories from disk"""
        self._load_project_memory()
        self._load_persona_memory()
        self._load_episodes()
        self._load_skills()
        
        # Initialize project if not exists
        if not self.project:
            self.project = ProjectMemory()
            self._save_project_memory()
        
        if not self.persona:
            self.persona = PersonaMemory()
            self._save_persona_memory()
        
        logger.info(f"✅ Loaded {len(self.episodes)} episodes, {len(self.skills)} skills")
    
    # ==================== PROJECT MEMORY ====================
    
    def _load_project_memory(self):
        """Load project configuration"""
        path = self.project_dir / "config.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                self.project = ProjectMemory(**data)
    
    def _save_project_memory(self):
        """Save project configuration"""
        path = self.project_dir / "config.json"
        with open(path, 'w') as f:
            json.dump(asdict(self.project), f, indent=2)
    
    # ==================== PERSONA MEMORY ====================
    
    def _load_persona_memory(self):
        """Load robot persona"""
        path = self.persona_dir / "persona.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                self.persona = PersonaMemory(**data)
    
    def _save_persona_memory(self):
        """Save robot persona"""
        path = self.persona_dir / "persona.json"
        with open(path, 'w') as f:
            json.dump(asdict(self.persona), f, indent=2)
    
    # ==================== EPISODE MEMORY ====================
    
    def _load_episodes(self):
        """Load all episodes"""
        for ep_file in self.episodes_dir.glob("episode_*.json"):
            with open(ep_file) as f:
                data = json.load(f)
                ep = EpisodeMemory(**data)
                self.episodes[ep.episode_number] = ep
    
    def save_episode(self, episode: EpisodeMemory):
        """Save episode memory"""
        self.episodes[episode.episode_number] = episode
        path = self.episodes_dir / f"episode_{episode.episode_number:03d}.json"
        with open(path, 'w') as f:
            json.dump(asdict(episode), f, indent=2)
        logger.info(f"💾 Saved episode {episode.episode_number}")
    
    def get_episode(self, episode_number: int) -> Optional[EpisodeMemory]:
        """Retrieve episode"""
        return self.episodes.get(episode_number)
    
    def list_episodes(self) -> List[EpisodeMemory]:
        """List all episodes"""
        return sorted(self.episodes.values(), key=lambda e: e.episode_number)
    
    # ==================== SOURCE MEMORY ====================
    
    def save_source(self, source: SourceMemory):
        """Save source citation"""
        self.sources[source.source_id] = source
        path = self.sources_dir / f"{source.source_id}.json"
        with open(path, 'w') as f:
            json.dump(asdict(source), f, indent=2)
    
    def get_sources_for_topic(self, topic: str) -> List[SourceMemory]:
        """Find sources related to topic"""
        results = []
        for source in self.sources.values():
            if topic.lower() in ' '.join(source.topic).lower():
                results.append(source)
        return results
    
    # ==================== SKILL MEMORY ====================
    
    def _load_skills(self):
        """Load reusable skills"""
        for skill_file in self.skills_dir.glob("skill_*.json"):
            with open(skill_file) as f:
                data = json.load(f)
                skill = SkillMemory(**data)
                self.skills[skill.skill_id] = skill
    
    def save_skill(self, skill: SkillMemory):
        """Save reusable skill"""
        self.skills[skill.skill_id] = skill
        path = self.skills_dir / f"skill_{skill.skill_id}.json"
        with open(path, 'w') as f:
            json.dump(asdict(skill), f, indent=2)
    
    def get_skill(self, skill_id: str) -> Optional[SkillMemory]:
        """Retrieve skill"""
        return self.skills.get(skill_id)
    
    # ==================== QUERY INTERFACE ====================
    
    async def query(self, query: str) -> Dict[str, Any]:
        """
        Query memory system.
        
        Returns relevant memories based on query.
        For now uses simple keyword matching.
        Later: use vector embeddings for semantic search.
        """
        query_lower = query.lower()
        
        results = {
            "episodes": [],
            "sources": [],
            "skills": []
        }
        
        # Search episodes
        for episode in self.episodes.values():
            if any(word in episode.title.lower() or word in episode.focus.lower()
                   for word in query_lower.split()):
                results["episodes"].append(asdict(episode))
        
        # Search sources
        for source in self.sources.values():
            if any(word in source.title.lower() or word in ' '.join(source.topic).lower()
                   for word in query_lower.split()):
                results["sources"].append(asdict(source))
        
        # Search skills
        for skill in self.skills.values():
            if any(word in skill.name.lower() or word in skill.description.lower()
                   for word in query_lower.split()):
                results["skills"].append(asdict(skill))
        
        return results
    
    async def log_interaction(self, user_input: str, result: Dict[str, Any]):
        """
        Log significant interactions for later analysis.
        Useful for understanding usage patterns.
        """
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "input": user_input,
            "result_summary": str(result)[:200]  # Truncate
        }
        
        log_file = self.interactions_dir / f"log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def get_context_for_ai(self) -> str:
        """
        Get memory context to include in AI prompts.
        
        Returns a text summary of key memories.
        """
        context_parts = []
        
        if self.project:
            context_parts.append(f"Project: {self.project.project_name}")
            context_parts.append(f"Mission: {self.project.mission}")
            context_parts.append(f"Tone: {self.project.tone}")
            context_parts.append(f"Rule: {self.project.core_rule}")
        
        if self.persona:
            context_parts.append(f"\nPersona: {self.persona.name}")
            context_parts.append(f"Voice: {self.persona.voice}")
            context_parts.append(f"Core question: {self.persona.core_question}")
        
        if self.episodes:
            context_parts.append(f"\nEpisodes created: {len(self.episodes)}")
            recent = list(self.episodes.values())[-3:]  # Last 3
            for ep in recent:
                context_parts.append(f"  - Episode {ep.episode_number}: {ep.title}")
        
        return '\n'.join(context_parts)
