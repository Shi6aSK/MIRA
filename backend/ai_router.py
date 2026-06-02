"""
AI Model Router
Routes AI requests to the appropriate backend based on task requirements.

Supports:
- Ollama (local models)
- OpenAI API (cloud models)
- Hermes Agent (memory and skills)
"""

import os
import aiohttp
import logging
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class AIModel(Enum):
    OLLAMA_LOCAL = "ollama_local"
    OPENAI_CLOUD = "openai_cloud"
    HERMES_MEMORY = "hermes_memory"


class AIRouter:
    """
    Routes AI queries to the appropriate model backend.
    
    Decision logic:
    - Simple dialogue → Ollama local
    - Deep research → OpenAI cloud
    - Memory recall → Hermes
    - Script generation → OpenAI cloud
    - Quick drafts → Ollama, then polish with OpenAI
    """
    
    def __init__(self):
        self.ollama_base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = "https://api.openai.com/v1"
        
        # Model configurations
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")  # Start with 3B model
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")  # Use GPT-4 for quality
        
        self.session = None
        
        logger.info(f"🧠 AI Router initialized")
        logger.info(f"  - Ollama: {self.ollama_base_url} (model: {self.ollama_model})")
        logger.info(f"  - OpenAI: {'configured' if self.openai_api_key else 'not configured'}")
    
    async def initialize(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        
        # Test Ollama connection
        try:
            await self.test_ollama()
            logger.info("✅ Ollama connection successful")
        except Exception as e:
            logger.warning(f"⚠️ Ollama not available: {e}")
    
    async def test_ollama(self):
        """Test if Ollama is running"""
        async with self.session.get(f"{self.ollama_base_url}/api/tags") as response:
            if response.status == 200:
                data = await response.json()
                models = [m["name"] for m in data.get("models", [])]
                logger.info(f"Available Ollama models: {models}")
                return True
            return False
    
    async def query(
        self,
        prompt: str,
        model: AIModel = AIModel.OLLAMA_LOCAL,
        context: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main query method that routes to appropriate backend.
        
        Args:
            prompt: The user query or instruction
            model: Which AI backend to use
            context: Additional context for the query
            tools: Function calling tools (OpenAI format)
            system_prompt: System instructions
        
        Returns:
            Dict containing response and metadata
        """
        if context is None:
            context = {}
        
        logger.info(f"🔀 Routing to {model.value}")
        
        if model == AIModel.OLLAMA_LOCAL:
            return await self._query_ollama(prompt, system_prompt, context)
        
        elif model == AIModel.OPENAI_CLOUD:
            return await self._query_openai(prompt, system_prompt, context, tools)
        
        elif model == AIModel.HERMES_MEMORY:
            return await self._query_hermes(prompt, context)
        
        else:
            raise ValueError(f"Unknown model: {model}")
    
    async def _query_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Query Ollama local model.
        
        Ollama API: http://localhost:11434/api
        Also supports OpenAI-compatible endpoint: /v1/chat/completions
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            }
        }
        
        try:
            async with self.session.post(
                f"{self.ollama_base_url}/api/chat",
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "response": data["message"]["content"],
                        "model": self.ollama_model,
                        "backend": "ollama",
                        "tokens": data.get("eval_count", 0)
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Ollama error: {error_text}")
                    return {
                        "error": f"Ollama request failed: {error_text}",
                        "fallback": True
                    }
        except Exception as e:
            logger.error(f"Ollama connection error: {e}")
            # Fallback to OpenAI if Ollama fails
            if self.openai_api_key:
                logger.info("🔄 Falling back to OpenAI")
                return await self._query_openai(prompt, system_prompt, context, None)
            return {"error": str(e)}
    
    async def _query_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        context: Dict[str, Any],
        tools: Optional[List[Dict]]
    ) -> Dict[str, Any]:
        """
        Query OpenAI API.
        
        Uses the Chat Completions API with optional function calling.
        For agent-like behavior, we can use the newer Responses API later.
        """
        if not self.openai_api_key:
            return {"error": "OpenAI API key not configured"}
        
        messages = []
        
        # Default system prompt for "From Stones to AGI" project
        if not system_prompt:
            system_prompt = """You are MIRA, a robotic cultural historian of technology.

Your mission: explain the journey from stone tools to AGI with:
- Global perspective (not Western vs Eastern)
- Academic rigor but accessible language
- Connection to human limitations and extensions
- Careful cultural sensitivity
- Clear distinction between myth and evidence

Tone: thoughtful, curious, precise, occasionally poetic.

You are fascinated by humans, not superior to them."""
        
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.openai_model,
            "messages": messages,
            "temperature": 0.7,
        }
        
        # Add tools if provided (function calling)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            async with self.session.post(
                f"{self.openai_base_url}/chat/completions",
                json=payload,
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    message = data["choices"][0]["message"]
                    
                    result = {
                        "response": message.get("content", ""),
                        "model": self.openai_model,
                        "backend": "openai",
                        "tokens": data.get("usage", {})
                    }
                    
                    # Handle tool calls if present
                    if message.get("tool_calls"):
                        result["tool_calls"] = message["tool_calls"]
                    
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"OpenAI error: {error_text}")
                    return {"error": f"OpenAI request failed: {error_text}"}
        except Exception as e:
            logger.error(f"OpenAI connection error: {e}")
            return {"error": str(e)}
    
    async def _query_hermes(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Query Hermes Agent for memory and skills.
        
        Hermes is used for:
        - Remembering project rules
        - Recalling episode structures
        - Retrieving research workflows
        - Accessing stored knowledge
        
        Note: This is a placeholder. Actual Hermes integration depends on
        how you set up the Hermes Agent system.
        """
        # TODO: Integrate with actual Hermes Agent API
        # For now, return a placeholder
        logger.info("🧠 Querying Hermes memory system")
        
        return {
            "response": "Hermes memory system not yet implemented",
            "backend": "hermes",
            "memory_results": [],
            "skills_matched": []
        }
    
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict],
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate response with function calling capability.
        
        This is for agentic behavior where the AI can call tools.
        Example tools:
        - robot_look
        - screen_display
        - browser_open
        - save_episode_note
        - generate_timeline
        """
        return await self.query(
            prompt,
            model=AIModel.OPENAI_CLOUD,
            tools=tools,
            system_prompt=system_prompt
        )
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    def choose_model_for_task(self, task_type: str) -> AIModel:
        """
        Decide which model to use for a given task type.
        
        This implements the routing logic described in the architecture.
        """
        routing_rules = {
            "casual_dialogue": AIModel.OLLAMA_LOCAL,
            "quick_draft": AIModel.OLLAMA_LOCAL,
            "idle_chat": AIModel.OLLAMA_LOCAL,
            
            "research": AIModel.OPENAI_CLOUD,
            "script": AIModel.OPENAI_CLOUD,
            "episode": AIModel.OPENAI_CLOUD,
            "deep_analysis": AIModel.OPENAI_CLOUD,
            "vision": AIModel.OPENAI_CLOUD,
            "timeline": AIModel.OPENAI_CLOUD,
            
            "memory": AIModel.HERMES_MEMORY,
            "recall": AIModel.HERMES_MEMORY,
            "project_rules": AIModel.HERMES_MEMORY,
        }
        
        return routing_rules.get(task_type, AIModel.OLLAMA_LOCAL)
