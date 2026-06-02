"""
Knowledge Database
Structured storage for "From Stones to AGI" knowledge base.

Stores:
- Episodes
- Sources
- Civilizations
- Technologies
- Concepts
- Scripts
- Visuals
- Quotes
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Source:
    """Source/citation entry"""
    id: int
    title: str
    author: Optional[str]
    url: Optional[str]
    source_type: str  # book, article, paper, web
    date_accessed: str
    region: Optional[str]
    topics: str  # JSON array
    reliability: str  # high, medium, low
    notes: str
    used_in_episodes: str  # JSON array


class KnowledgeDatabase:
    """
    SQLite-based knowledge database.
    
    Later can migrate to PostgreSQL + vector DB for semantic search.
    """
    
    def __init__(self, db_path: str = "knowledge_base/mira.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.conn = None
        
        logger.info(f"📚 Knowledge Database at {self.db_path}")
    
    def initialize(self):
        """Initialize database schema"""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
        logger.info("✅ Database schema initialized")
    
    def _create_schema(self):
        """Create database tables"""
        cursor = self.conn.cursor()
        
        # Episodes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            episode_number INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            focus TEXT NOT NULL,
            regions_covered TEXT,  -- JSON array
            concepts TEXT,         -- JSON array
            open_threads TEXT,     -- JSON array
            sources_used TEXT,     -- JSON array
            script_path TEXT,
            status TEXT DEFAULT 'planned',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Sources table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            url TEXT,
            source_type TEXT,  -- book, article, paper, web
            date_accessed TEXT,
            region TEXT,
            topics TEXT,       -- JSON array
            reliability TEXT,  -- high, medium, low
            notes TEXT,
            used_in_episodes TEXT,  -- JSON array
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Technologies table (the spine)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS technologies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            extends TEXT,      -- what human capability it extends
            era TEXT,
            regions TEXT,      -- JSON array
            description TEXT,
            episode_number INTEGER,
            FOREIGN KEY (episode_number) REFERENCES episodes(episode_number)
        )
        """)
        
        # Concepts table (ideas that recur)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            related_concepts TEXT,  -- JSON array
            appeared_in_episodes TEXT  -- JSON array
        )
        """)
        
        # Quotes table (memorable lines)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            source TEXT,
            context TEXT,
            episode_number INTEGER,
            FOREIGN KEY (episode_number) REFERENCES episodes(episode_number)
        )
        """)
        
        # Research notes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS research_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            sources TEXT,  -- JSON array
            tags TEXT,     -- JSON array
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        self.conn.commit()
    
    # ==================== RESEARCH OPERATIONS ====================
    
    async def save_research(
        self,
        topic: str,
        analysis: Dict[str, Any],
        sources: List[Dict[str, Any]]
    ) -> int:
        """Save research results"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
        INSERT INTO research_notes (topic, content, sources, tags)
        VALUES (?, ?, ?, ?)
        """, (
            topic,
            json.dumps(analysis),
            json.dumps(sources),
            json.dumps([topic])
        ))
        
        self.conn.commit()
        
        # Also save individual sources
        for source in sources:
            await self.add_source(
                title=source.get("title", ""),
                url=source.get("url"),
                source_type="web",
                topics=[topic]
            )
        
        return cursor.lastrowid
    
    async def get_research(self, topic: str) -> List[Dict[str, Any]]:
        """Retrieve research on topic"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT * FROM research_notes
        WHERE topic LIKE ?
        ORDER BY created_at DESC
        """, (f"%{topic}%",))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== SOURCE OPERATIONS ====================
    
    async def add_source(
        self,
        title: str,
        url: Optional[str] = None,
        author: Optional[str] = None,
        source_type: str = "web",
        topics: List[str] = None,
        reliability: str = "medium",
        notes: str = ""
    ) -> int:
        """Add source to database"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
        INSERT INTO sources (title, url, author, source_type, date_accessed, topics, reliability, notes, used_in_episodes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            url,
            author,
            source_type,
            datetime.now().isoformat(),
            json.dumps(topics or []),
            reliability,
            notes,
            json.dumps([])
        ))
        
        self.conn.commit()
        return cursor.lastrowid
    
    async def get_sources_for_topic(self, topic: str) -> List[Dict[str, Any]]:
        """Find sources related to topic"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT * FROM sources
        WHERE topics LIKE ?
        ORDER BY reliability DESC, date_accessed DESC
        """, (f"%{topic}%",))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== EPISODE OPERATIONS ====================
    
    async def save_episode_data(self, episode_data: Dict[str, Any]) -> int:
        """Save full episode data"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
        INSERT OR REPLACE INTO episodes 
        (episode_number, title, focus, regions_covered, concepts, open_threads, sources_used, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_data.get("episode_number"),
            episode_data.get("title"),
            episode_data.get("focus"),
            json.dumps(episode_data.get("regions_covered", [])),
            json.dumps(episode_data.get("concepts", [])),
            json.dumps(episode_data.get("open_threads", [])),
            json.dumps(episode_data.get("sources_used", [])),
            episode_data.get("status", "planned")
        ))
        
        self.conn.commit()
        return episode_data.get("episode_number")
    
    async def get_episode(self, episode_number: int) -> Optional[Dict[str, Any]]:
        """Get episode data"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM episodes WHERE episode_number = ?", (episode_number,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    async def list_all_episodes(self) -> List[Dict[str, Any]]:
        """List all episodes"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM episodes ORDER BY episode_number")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== TECHNOLOGY SPINE ====================
    
    async def add_technology(
        self,
        name: str,
        extends: str,
        era: str,
        description: str,
        regions: List[str]
    ) -> int:
        """Add technology to spine"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
        INSERT INTO technologies (name, extends, era, description, regions)
        VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            extends,
            era,
            description,
            json.dumps(regions)
        ))
        
        self.conn.commit()
        return cursor.lastrowid
    
    # ==================== SEARCH ====================
    
    async def search(self, query: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Simple full-text search across database.
        
        Later: add vector embeddings for semantic search.
        """
        cursor = self.conn.cursor()
        
        results = {
            "episodes": [],
            "sources": [],
            "research": []
        }
        
        # Search episodes
        cursor.execute("""
        SELECT * FROM episodes
        WHERE title LIKE ? OR focus LIKE ?
        """, (f"%{query}%", f"%{query}%"))
        results["episodes"] = [dict(row) for row in cursor.fetchall()]
        
        # Search sources
        cursor.execute("""
        SELECT * FROM sources
        WHERE title LIKE ? OR topics LIKE ?
        """, (f"%{query}%", f"%{query}%"))
        results["sources"] = [dict(row) for row in cursor.fetchall()]
        
        # Search research notes
        cursor.execute("""
        SELECT * FROM research_notes
        WHERE topic LIKE ? OR tags LIKE ?
        """, (f"%{query}%", f"%{query}%"))
        results["research"] = [dict(row) for row in cursor.fetchall()]
        
        return results
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
