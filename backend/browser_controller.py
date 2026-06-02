"""
Browser/Tool Controller
Manages web browsing, research, and visual display with safety gates.

Uses Playwright for browser automation (can be run in headless mode
or displayed on robot screen).
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class BrowserAction(Enum):
    SEARCH = "search"
    OPEN_PAGE = "open_page"
    SCREENSHOT = "screenshot"
    EXTRACT_TEXT = "extract_text"
    SUMMARIZE = "summarize"
    FIND_SOURCES = "find_sources"


@dataclass
class SafetyGate:
    """Web action safety configuration"""
    allow_search: bool = True
    allow_open_public_pages: bool = True
    allow_screenshot: bool = True
    allow_extract_text: bool = True
    
    # Require confirmation for these
    require_confirm_download: bool = True
    require_confirm_login: bool = True
    require_confirm_form_submit: bool = True
    require_confirm_purchase: bool = True
    require_confirm_post: bool = True


class BrowserController:
    """
    Browser automation controller with safety gates.
    
    Responsibilities:
    - Web search
    - Open and display pages
    - Extract information
    - Find and cite sources
    - Screenshot for display
    - Block unsafe actions
    
    Uses Playwright (supports Chrome, Firefox, WebKit)
    """
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.safety = SafetyGate()
        
        logger.info("🌐 Browser Controller initialized")
    
    async def initialize(self):
        """Initialize Playwright browser"""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False  # Show browser for robot display
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="MIRA-Bot/1.0 (Educational Research Robot)"
            )
            self.page = await self.context.new_page()
            
            logger.info("✅ Browser initialized")
        except ImportError:
            logger.warning("⚠️ Playwright not installed. Run: pip install playwright && playwright install")
        except Exception as e:
            logger.error(f"Browser initialization failed: {e}")
    
    async def handle_request(self, request: str) -> Dict[str, Any]:
        """
        Parse and handle a natural language browser request.
        
        Examples:
        - "Search for early writing systems"
        - "Show me sources about fire as technology"
        - "Open this page: https://example.com"
        """
        request_lower = request.lower()
        
        if "search" in request_lower or "find" in request_lower:
            query = self._extract_search_query(request)
            return await self.search(query)
        
        elif "open" in request_lower or "show" in request_lower or "display" in request_lower:
            if "http" in request:
                url = self._extract_url(request)
                return await self.open_page(url, display_on_screen=True)
            else:
                # Search instead
                query = self._extract_search_query(request)
                return await self.search(query, auto_open_first=True)
        
        elif "screenshot" in request_lower:
            return await self.screenshot()
        
        else:
            return await self.search(request)
    
    async def search(
        self,
        query: str,
        auto_open_first: bool = False
    ) -> Dict[str, Any]:
        """
        Search the web and return results.
        
        For academic research, we want credible sources:
        - Wikipedia (as starting point)
        - Educational institutions (.edu)
        - Research databases
        - Museum/library sites
        - Peer-reviewed sources
        """
        if not self.safety.allow_search:
            return {"error": "Search not allowed"}
        
        logger.info(f"🔍 Searching: {query}")
        
        try:
            # Use DuckDuckGo for privacy-respecting search
            search_url = f"https://duckduckgo.com/?q={query}"
            await self.page.goto(search_url, wait_until="networkidle")
            
            # Extract search results
            # (This is simplified - real implementation would parse results)
            results = await self._extract_search_results()
            
            # Filter for credible sources
            credible_results = self._filter_credible_sources(results)
            
            if auto_open_first and credible_results:
                first_result = credible_results[0]
                await self.open_page(first_result["url"], display_on_screen=True)
            
            return {
                "query": query,
                "results": credible_results[:10],
                "count": len(credible_results)
            }
        
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"error": str(e)}
    
    async def open_page(
        self,
        url: str,
        display_on_screen: bool = False
    ) -> Dict[str, Any]:
        """
        Open a webpage with safety checks.
        
        Safety checks:
        - Verify URL is public/safe
        - No login pages without confirmation
        - No payment pages without confirmation
        """
        if not self.safety.allow_open_public_pages:
            return {"error": "Page opening not allowed"}
        
        # Safety check URL
        if not self._is_safe_url(url):
            return {"error": f"URL not allowed: {url}", "requires_confirmation": True}
        
        logger.info(f"🌐 Opening: {url}")
        
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
            
            title = await self.page.title()
            
            # Extract key information
            text_content = await self._extract_main_content()
            
            result = {
                "url": url,
                "title": title,
                "display_on_screen": display_on_screen,
                "content_preview": text_content[:500] + "..." if len(text_content) > 500 else text_content
            }
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to open page: {e}")
            return {"error": str(e)}
    
    async def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Take screenshot of current page"""
        if not self.safety.allow_screenshot:
            return {"error": "Screenshots not allowed"}
        
        try:
            if not path:
                path = "screenshot.png"
            
            await self.page.screenshot(path=path, full_page=True)
            
            return {
                "screenshot": path,
                "success": True
            }
        
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return {"error": str(e)}
    
    async def extract_text(self) -> str:
        """Extract main text content from current page"""
        if not self.safety.allow_extract_text:
            return ""
        
        try:
            return await self._extract_main_content()
        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return ""
    
    async def find_sources_for_topic(
        self,
        topic: str,
        min_sources: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find credible sources for a research topic.
        
        Returns structured source citations.
        """
        logger.info(f"📚 Finding sources for: {topic}")
        
        sources = []
        
        # Search strategies
        search_queries = [
            f"{topic} academic research",
            f"{topic} history",
            f"{topic} anthropology",
            f"{topic} technology history",
        ]
        
        for query in search_queries:
            if len(sources) >= min_sources:
                break
            
            results = await self.search(query)
            
            for result in results.get("results", []):
                if self._is_credible_source(result["url"]):
                    sources.append({
                        "title": result.get("title", ""),
                        "url": result["url"],
                        "query": query,
                        "relevance": "high"  # Could add relevance scoring
                    })
        
        return sources[:min_sources]
    
    # ==================== HELPER METHODS ====================
    
    def _extract_search_query(self, text: str) -> str:
        """Extract search query from natural language"""
        # Remove common prefixes
        for prefix in ["search for", "find", "look up", "show me"]:
            if text.lower().startswith(prefix):
                return text[len(prefix):].strip()
        return text
    
    def _extract_url(self, text: str) -> str:
        """Extract URL from text"""
        import re
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
        return urls[0] if urls else ""
    
    async def _extract_search_results(self) -> List[Dict[str, Any]]:
        """Extract search results from page"""
        try:
            # This is simplified - real implementation would parse DuckDuckGo results
            results = []
            
            # Example structure - would actually parse from page
            # links = await self.page.query_selector_all('a[data-testid="result-title"]')
            # for link in links:
            #     title = await link.text_content()
            #     url = await link.get_attribute('href')
            #     results.append({"title": title, "url": url})
            
            return results
        except Exception as e:
            logger.error(f"Failed to extract results: {e}")
            return []
    
    async def _extract_main_content(self) -> str:
        """Extract main text content, filtering out navigation/ads"""
        try:
            # Try to find main content area
            main_selectors = [
                'main',
                'article',
                '[role="main"]',
                '.content',
                '#content',
            ]
            
            for selector in main_selectors:
                element = await self.page.query_selector(selector)
                if element:
                    return await element.text_content()
            
            # Fallback to body
            body = await self.page.query_selector('body')
            if body:
                return await body.text_content()
            
            return ""
        
        except Exception as e:
            logger.error(f"Content extraction failed: {e}")
            return ""
    
    def _is_safe_url(self, url: str) -> bool:
        """Check if URL is safe to open"""
        # Block obviously unsafe patterns
        unsafe_patterns = [
            "login",
            "signin",
            "checkout",
            "payment",
            "buy",
            "cart"
        ]
        
        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in unsafe_patterns)
    
    def _filter_credible_sources(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter results to prefer credible sources"""
        credible = []
        
        for result in results:
            url = result.get("url", "")
            if self._is_credible_source(url):
                credible.append(result)
        
        # Return credible first, then others
        non_credible = [r for r in results if r not in credible]
        return credible + non_credible
    
    def _is_credible_source(self, url: str) -> bool:
        """
        Check if source is credible for academic content.
        
        Preferred domains:
        - Educational institutions (.edu)
        - Government (.gov)
        - Wikipedia (as starting point)
        - Academic publishers
        - Museums/libraries
        - Peer-reviewed journals
        """
        credible_indicators = [
            ".edu",
            ".gov",
            "wikipedia.org",
            "britannica.com",
            "archive.org",
            "jstor.org",
            "scholar.google",
            "nature.com",
            "science.org",
            "plos.org",
            "arxiv.org",
            "smithsonian",
            "museum",
            "library"
        ]
        
        url_lower = url.lower()
        return any(indicator in url_lower for indicator in credible_indicators)
    
    async def close(self):
        """Close browser"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
