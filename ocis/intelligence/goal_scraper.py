"""
Phase 1 Upgrade: AdvancedGoalScraper.
Uses LLM-powered search to discover project missions, roadmaps, and maintainer priorities.
"""
from __future__ import annotations
import httpx
from typing import List, Dict, Any
from ocis.core.llm.client import get_llm
from ocis.config import OPENROUTER_API_KEY

class AdvancedGoalScraper:
    def __init__(self):
        self.llm = get_llm()

    def discover_goals(self, repo_slug: str, project_name: str) -> dict:
        """
        Perform a deep dive into the project's 'soul' by searching beyond the code.
        """
        # We'll use the LLM to 'simulate' a search/browse process or use its internal knowledge 
        # combined with targeted queries if we had a search tool. 
        # Since we have the LLM, we'll ask it to synthesize a 'Strategic Mission Report'.
        
        prompt = f"""You are a top-tier open-source intelligence analyst. 
Deeply analyze the project '{project_name}' ({repo_slug}).
Your goal is to identify the 'North Star' goals of this project for the current year.

Think about:
1. What are the maintainers currently obsessed with? (e.g., Rust migration, performance, security hardening, cloud-native transition).
2. What are the 'unspoken' pain points the community is crying about in forums/HN/Reddit?
3. What is the 12-month roadmap?

Return a 'Strategic Project Intelligence' report in ONLY valid JSON:
{{
  "mission_statement": "A powerful 1-sentence summary of the project's core purpose.",
  "strategic_priorities": [
    {{"goal": "Title", "description": "Context on why this matters now.", "urgency": "high/medium/low"}}
  ],
  "maintainer_sentiment": "What do the lead maintainers value most in contributions? (e.g., minimality, rigorous testing, innovative features).",
  "forbidden_zones": ["What types of PRs are usually rejected or controversial?"],
  "top_doable_upgrades": ["Specifically, what high-impact feature or fix would be a 'gold medal' contribution right now?"]
}}"""
        
        try:
            # Use chat_json for robust extraction
            return self.llm.chat_json([{"role": "user", "content": prompt}])
        except Exception:
            return {}

def get_goal_scraper() -> AdvancedGoalScraper:
    return AdvancedGoalScraper()
