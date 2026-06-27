import re
import urllib.parse
import html as html_mod
import httpx
from jan_sahayak.logger import get_logger

logger = get_logger(__name__)

class WebSearchService:
    """
    Service for performing web searches to fetch real-time and state-specific
    information using DuckDuckGo HTML search. Requires no external API keys.
    """

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """
        Perform a DuckDuckGo HTML search and return a list of parsed results.
        Each result is a dict with 'title', 'url', and 'snippet'.
        """
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self.headers)
                resp.raise_for_status()
                html_content = resp.text
        except Exception as e:
            logger.error(f"DuckDuckGo web search failed for query '{query}': {e}", exc_info=True)
            return []

        # Parse the HTML results
        blocks = html_content.split('class="result results_links')
        results = []
        
        for block in blocks[1:]:
            if len(results) >= limit:
                break
                
            # Locate title and URL anchor tag
            a_match = re.search(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not a_match:
                a_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                
            if not a_match:
                continue
                
            raw_url, raw_title = a_match.groups()
            
            # Clean redirect wrapper from DDG
            clean_url = raw_url
            if "uddg=" in raw_url:
                url_match = re.search(r'uddg=([^&]+)', raw_url)
                if url_match:
                    clean_url = urllib.parse.unquote(url_match.group(1))
            
            if clean_url.startswith("//"):
                clean_url = "https:" + clean_url
                
            title = re.sub(r'<[^>]*>', '', raw_title).strip()
            
            # Extract snippet
            snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet = ""
            if snippet_match:
                snippet = re.sub(r'<[^>]*>', '', snippet_match.group(1)).strip()
                
            title = html_mod.unescape(title)
            snippet = html_mod.unescape(snippet)
            
            results.append({
                "title": title,
                "url": clean_url,
                "snippet": snippet
            })
            
        logger.info(f"Web search for '{query}' returned {len(results)} results")
        return results

    async def search_formatted(self, query: str, limit: int = 4) -> str:
        """
        Run a web search and format the results into a clean markdown string
        suitable for direct inclusion into LLM prompts.
        """
        results = await self.search(query, limit=limit)
        if not results:
            return "No real-time search results found."
            
        formatted_lines = []
        for i, r in enumerate(results, 1):
            formatted_lines.append(
                f"[{i}] Title: {r['title']}\n"
                f"    Source: {r['url']}\n"
                f"    Summary: {r['snippet']}"
            )
        return "\n\n".join(formatted_lines)

# Singleton instance
web_search_service = WebSearchService()
