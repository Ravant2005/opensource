"""
Phase 1: Intelligence Gatherer — orchestrates GitHub + community scraping + LLM synthesis.
"""
from __future__ import annotations
import json
from ocis.intelligence.github_client import GitHubIntelligence
from ocis.intelligence.community import CommunityIntelligence
from ocis.intelligence.goal_scraper import get_goal_scraper
from ocis.core.llm.client import get_llm

_SYNTHESIS_PROMPT = """You are an expert open-source analyst. Analyse the following data about
the project "{project_name}" and extract structured intelligence.

DATA (truncated for brevity):
{raw_data}

Return ONLY a JSON object with this exact schema:
{{
  "project_summary": "2-3 sentence description",
  "mission": "core mission in 1 sentence",
  "tech_stack": ["lang1", "framework2"],
  "maturity": "experimental|alpha|beta|stable|mature",
  "community_size": "tiny|small|medium|large|massive",
  "activity_level": "dormant|low|moderate|active|very_active",
  "top_pain_points": [
    {{"title": "...", "source": "github_issue|reddit|hn|stackoverflow",
      "evidence": "direct quote", "frequency": 5}}
  ],
  "missing_features": [
    {{"feature": "...", "requested_by": "N mentions", "priority": "high|medium|low"}}
  ],
  "roadmap_items": ["item1", "item2"],
  "contribution_style": "strict|moderate|welcoming",
  "getting_started": "How to set up dev env in 2-3 sentences",
  "key_maintainers": ["username1"],
  "related_projects": ["project1"]
}}"""


class IntelligenceGatherer:
    def __init__(self):
        self.github = GitHubIntelligence()
        self.community = CommunityIntelligence()
        self.llm = get_llm()

    def gather(self, repo_slug: str, log=None) -> dict:
        def emit(msg):
            if log:
                log(msg)

        emit(f"Fetching GitHub data for {repo_slug}...")
        gh_data = self.github.gather(repo_slug)

        project_name = gh_data.get("metadata", {}).get("name", repo_slug.split("/")[-1])
        emit(f"Fetching community signals for {project_name}...")
        community_data = self.community.gather_all(project_name)

        emit(f"Discovering strategic goals and maintainer sentiment for {project_name}...")
        goals_data = get_goal_scraper().discover_goals(repo_slug, project_name)

        emit("Synthesising intelligence with LLM...")
        # Truncate raw data to fit context window
        raw_summary = {
            "github_metadata": gh_data.get("metadata", {}),
            "top_issues": gh_data.get("issues", [])[:15],
            "good_first_issues": gh_data.get("good_first_issues", [])[:10],
            "help_wanted": gh_data.get("help_wanted", [])[:10],
            "readme_excerpt": (gh_data.get("readme") or "")[:2000],
            "contributing_excerpt": (gh_data.get("contributing") or "")[:1000],
            "roadmap_excerpt": (gh_data.get("roadmap") or "")[:1000],
            "discussions": gh_data.get("discussions", [])[:10],
            "hn_top": community_data.get("hackernews", [])[:8],
            "reddit_top": community_data.get("reddit", [])[:8],
            "so_top": community_data.get("stackoverflow", [])[:8],
            "strategic_goals": goals_data,
        }

        synthesis = self.llm.chat_json(
            [{"role": "user", "content": _SYNTHESIS_PROMPT.format(
                project_name=project_name,
                raw_data=json.dumps(raw_summary, ensure_ascii=False)[:12000],
            )}]
        )

        return {
            "repo_slug": repo_slug,
            "project_name": project_name,
            "github": gh_data,
            "community": community_data,
            "synthesis": synthesis,
        }
