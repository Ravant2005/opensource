# OCIS — Opensource Contributor Intelligence System
## Complete Build Specification & Implementation Prompt

> **Project:** Transform the existing ASE codebase into OCIS — a world-class autonomous
> intelligence system that discovers, analyses, and contributes to top open-source projects,
> making your GitHub profile stand out for elite engineering roles.
>
> **Stack:** Python · FastAPI · OpenRouter (free models) · GitHub API · Free scraping tools
> · React dashboard · SQLite (dev) / PostgreSQL (prod)

---

## 0. Current Codebase Audit — What We Inherit

```
opensource/
├── ase/
│   ├── config.py              → rename: ocis/config.py (swap Gemini → OpenRouter)
│   ├── run.py                 → keep, update app title
│   ├── demo.py                → replace with ocis_demo.py
│   ├── agents/
│   │   └── orchestrator.py    → REWRITE: new 6-phase OCIS pipeline
│   ├── api/
│   │   └── main.py            → EXTEND: add OCIS endpoints
│   ├── core/
│   │   ├── embeddings/        → KEEP: embed code chunks for RAG
│   │   ├── graph/             → KEEP: knowledge graph of repo structure
│   │   ├── parsers/           → EXTEND: add multi-language parsers
│   │   └── rag/               → EXTEND: query pipeline
│   ├── security/              → REPURPOSE → ocis/analysis/
│   │   ├── static/analyzer    → becomes: CodeQualityAnalyzer
│   │   └── reasoning/agent    → becomes: IntelligenceReasoningAgent (OpenRouter)
│   ├── patch/                 → REPURPOSE → ocis/implementation/
│   │   ├── generator.py       → becomes: FeatureImplementer
│   │   └── scorer.py          → becomes: ContributionQualityScorer
│   ├── contribution/
│   │   └── engine.py          → EXTEND: add fork_repo() before create_pull_request()
│   ├── validation/            → KEEP: run tests after implementation
│   ├── learning/              → KEEP: improve from past contributions
│   └── dashboard/             → REPLACE: full React HiTL review UI
└── linux/                     → sample target repo (Linux kernel scaffold)
```

**Rule:** Never delete existing files. Refactor module by module using the plan below.

---

## 1. Environment & Free Resources

### 1.1 Replace `ase/config.py` with `ocis/config.py`

```python
"""
OCIS Config — single source of truth.
All free-tier resources. No paid APIs required.
"""
import os
from pathlib import Path

_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path, override=False)
    except ImportError:
        pass

# ── OpenRouter (free models) ──────────────────────────────────────────────────
# Sign up free at https://openrouter.ai — no credit card needed for free models
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL  = "https://openrouter.ai/api/v1"

# Free model rotation — fallback chain, use in order
FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",   # Best reasoning, 128k ctx
    "deepseek/deepseek-r1:free",                 # Best for code understanding
    "google/gemma-3-27b-it:free",                # Fast, good for summaries
    "mistralai/mistral-7b-instruct:free",        # Fallback — always available
    "qwen/qwen-2.5-72b-instruct:free",           # Strong multilingual code
]
OPENROUTER_MODEL     = os.environ.get("OPENROUTER_MODEL", FREE_MODELS[0])

# ── GitHub ────────────────────────────────────────────────────────────────────
# Classic PAT with: repo, workflow, read:org, read:user scopes
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

# ── Free Scraping ─────────────────────────────────────────────────────────────
# No key needed — all public APIs / crawlers
HN_BASE_URL          = "https://hacker-news.firebaseio.com/v0"
GITHUB_API_BASE      = "https://api.github.com"
LIBRARIES_IO_KEY     = os.environ.get("LIBRARIES_IO_KEY", "")  # free tier: 60 req/min
STACKOVERFLOW_KEY    = os.environ.get("STACKOVERFLOW_KEY", "")  # optional, public API
REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")   # free Reddit app
REDDIT_SECRET        = os.environ.get("REDDIT_SECRET", "")

# ── Storage — SQLite dev / Postgres prod ─────────────────────────────────────
DATABASE_URL    = os.environ.get("DATABASE_URL", "sqlite:///ocis.db")

# ── Qdrant (free self-hosted vector store) ───────────────────────────────────
QDRANT_HOST     = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT     = int(os.environ.get("QDRANT_PORT", "6333"))
# Run free: docker run -p 6333:6333 qdrant/qdrant

# ── OCIS Behaviour ────────────────────────────────────────────────────────────
OCIS_DRY_RUN                  = os.environ.get("OCIS_DRY_RUN", "true").lower() == "true"
OCIS_MAX_PRS_PER_REPO_PER_WEEK = int(os.environ.get("OCIS_MAX_PRS_PER_REPO_PER_WEEK", "1"))
OCIS_CONTRIBUTION_QUALITY_MIN  = float(os.environ.get("OCIS_CONTRIBUTION_QUALITY_MIN", "0.70"))
OCIS_MAX_CONCURRENT_PIPELINES  = int(os.environ.get("OCIS_MAX_CONCURRENT_PIPELINES", "3"))

# ── API Server ────────────────────────────────────────────────────────────────
OCIS_HOST = os.environ.get("OCIS_HOST", "127.0.0.1")
OCIS_PORT = int(os.environ.get("OCIS_PORT", "8001"))
```

### 1.2 `.env.example`
```dotenv
# OpenRouter — free signup at openrouter.ai
OPENROUTER_API_KEY=sk-or-...

# GitHub — classic PAT
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=your_username

# Optional boosters
LIBRARIES_IO_KEY=
REDDIT_CLIENT_ID=
REDDIT_SECRET=

# DB (default: SQLite, switch to postgres for prod)
DATABASE_URL=sqlite:///ocis.db
```

### 1.3 Free Resources Reference Table

| Purpose | Tool | Free Tier | Notes |
|---|---|---|---|
| LLM reasoning | OpenRouter | ~50 free models | No CC needed |
| Code understanding | deepseek-r1:free | Unlimited | Best for code |
| General intelligence | llama-3.3-70b:free | Rate limited | 128k ctx |
| GitHub data | GitHub REST API | 60 req/hr unauth, 5000 auth | Use your PAT |
| Package ecosystem | Libraries.io API | 60 req/min free | Dep graphs |
| Community signals | HN Firebase API | Unlimited | No key |
| Community signals | Reddit API | 60 req/min | Free app |
| Web scraping | httpx + BeautifulSoup4 | Unlimited | Polite crawl |
| Code search | GitHub Search API | 30 req/min | With PAT |
| Vector DB | Qdrant (self-hosted) | Free | Docker one-liner |
| Embeddings | sentence-transformers | Free | CPU runs fine |
| SQL storage | SQLite → PostgreSQL | Free | Dev → Prod |

---

## 2. Core LLM Client — OpenRouter Wrapper

**File:** `ocis/core/llm/client.py`

Build a drop-in OpenRouter client that:
- Implements `chat(messages, model=None, system=None) → str`
- Auto-rotates through `FREE_MODELS` on rate-limit (429) or error
- Implements exponential backoff: 1s, 2s, 4s, max 3 retries per model
- Logs token usage per call to SQLite `llm_usage` table
- Parses JSON responses safely with `extract_json(text) → dict`

```python
# Interface contract — implement this exactly
class OCISLLMClient:
    def chat(self, messages: list[dict], model: str = None,
             system: str = None, temperature: float = 0.2) -> str:
        """Send messages, return text. Auto-rotate models on failure."""

    def chat_json(self, messages: list[dict], system: str = None,
                  schema_hint: str = "") -> dict:
        """Like chat() but guarantees a parsed dict back.
           Adds 'respond ONLY with valid JSON, no markdown' to system prompt."""

    def embed(self, text: str) -> list[float]:
        """Local embedding via sentence-transformers (no API call)."""
```

**Implementation notes:**
- Use `httpx` (async-capable, better than requests for FastAPI)
- Set `HTTP-Referer: https://github.com/{GITHUB_USERNAME}/ocis` header (OpenRouter requires it)
- Set `X-Title: OCIS` header
- Always include `model` in request body from the free model list
- For `embed()`, use `sentence-transformers/all-MiniLM-L6-v2` loaded once at startup

---

## 3. The 6-Phase OCIS Pipeline

Replace `ase/agents/orchestrator.py` with the new OCIS pipeline:

### Pipeline Overview

```
GitHub URL Input
      │
      ▼
Phase 1: INTELLIGENCE GATHERING
  ├── GitHub API: repo metadata, issues, PRs, labels, milestones
  ├── GitHub Issues: open bugs, feature requests, help-wanted, good-first-issue
  ├── GitHub Discussions: community pain points
  ├── README + CONTRIBUTING.md + ROADMAP scrape
  ├── Hacker News: project mentions, community sentiment
  ├── Reddit: r/programming, r/linux, project subreddits
  ├── Libraries.io: dependency graph, dependents (who uses this)
  └── Web crawl: official docs, blog posts, changelogs
      │
      ▼
Phase 2: REPO DEEP ANALYSIS
  ├── Clone repo locally
  ├── Language detection + file tree map
  ├── Code complexity scoring (cyclomatic, cognitive)
  ├── TODO/FIXME/HACK comment extraction
  ├── Test coverage gap detection
  ├── Documentation gap detection
  ├── Dependency freshness check
  ├── CI/CD pipeline analysis
  └── Embed all code chunks into Qdrant
      │
      ▼
Phase 3: CORRELATION ENGINE
  ├── Map open GitHub issues → code locations (RAG lookup)
  ├── Map community complaints → missing features
  ├── Map roadmap goals → implementation gaps
  ├── Score each opportunity: impact × difficulty × novelty × visibility
  └── Rank top-10 contribution opportunities
      │
      ▼
Phase 4: RECOMMENDATION GENERATION
  ├── For each opportunity: generate detailed spec
  ├── Estimate implementation complexity (LOC, files affected)
  ├── Generate PR title, description template, linked issues
  ├── Classify: bug-fix | feature | docs | test | refactor | perf
  └── Filter by OCIS_CONTRIBUTION_QUALITY_MIN threshold
      │
      ▼
Phase 5: HUMAN-IN-THE-LOOP (Dashboard)
  ├── Show all recommendations with full context
  ├── Human reviews, approves/rejects/edits each
  ├── Human selects priority order
  └── Human clicks "Execute" → triggers Phase 6
      │
      ▼
Phase 6: AUTONOMOUS EXECUTION
  ├── Fork repo to GITHUB_USERNAME account
  ├── Clone fork locally
  ├── Implement approved contributions (LLM code generation)
  ├── Run repo's own test suite
  ├── Quality gate check
  ├── Git commit with conventional commit message
  ├── Push to fork
  └── Create PR to upstream with full description
```

### 3.1 Job State Machine

```python
# ocis/agents/orchestrator.py
class OCISJobStatus(str, Enum):
    SUBMITTED     = "submitted"
    GATHERING     = "gathering"       # Phase 1
    ANALYZING     = "analyzing"       # Phase 2
    CORRELATING   = "correlating"     # Phase 3
    RECOMMENDING  = "recommending"    # Phase 4
    AWAITING_HITL = "awaiting_hitl"   # Phase 5 — paused for human
    EXECUTING     = "executing"       # Phase 6
    DONE          = "done"
    FAILED        = "failed"

@dataclass
class OCISJob:
    job_id: str
    repo_url: str
    repo_slug: str           # "owner/repo"
    repo_path: str = ""      # local clone path
    fork_url: str = ""       # fork URL after Phase 6
    status: OCISJobStatus = OCISJobStatus.SUBMITTED

    # Phase outputs
    intelligence: dict = field(default_factory=dict)   # Phase 1
    analysis: dict = field(default_factory=dict)        # Phase 2
    opportunities: list = field(default_factory=list)   # Phase 3
    recommendations: list = field(default_factory=list) # Phase 4
    approved: list = field(default_factory=list)        # Phase 5 (human approved)
    pr_results: list = field(default_factory=list)      # Phase 6

    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    logs: list = field(default_factory=list)  # live streaming logs

    def log(self, msg: str):
        entry = {"ts": datetime.utcnow().isoformat(), "msg": msg}
        self.logs.append(entry)
        self.updated_at = datetime.utcnow().isoformat()
        print(f"[OCIS:{self.job_id}] {msg}")
```

---

## 4. Phase 1: Intelligence Gathering

**File:** `ocis/intelligence/gatherer.py`

### 4.1 GitHub Intelligence

```python
class GitHubIntelligence:
    """Scrape everything public from a GitHub repo using the free REST API."""

    def gather(self, repo_slug: str) -> dict:
        return {
            "metadata": self._get_repo_metadata(repo_slug),
            "issues": self._get_issues(repo_slug, state="open", max=100),
            "prs": self._get_recent_prs(repo_slug, max=50),
            "labels": self._get_labels(repo_slug),
            "milestones": self._get_milestones(repo_slug),
            "discussions": self._get_discussions_graphql(repo_slug),  # GraphQL
            "releases": self._get_releases(repo_slug, max=5),
            "contributors": self._get_contributors(repo_slug, max=30),
            "readme": self._fetch_file(repo_slug, "README.md"),
            "contributing": self._fetch_file(repo_slug, "CONTRIBUTING.md"),
            "roadmap": self._search_roadmap(repo_slug),  # search common paths
            "good_first_issues": self._get_issues_by_label(repo_slug, "good first issue"),
            "help_wanted": self._get_issues_by_label(repo_slug, "help wanted"),
            "pinned_issues": self._get_issues_by_label(repo_slug, "pinned"),
        }

    def _get_repo_metadata(self, slug: str) -> dict:
        """GET /repos/{slug} — stars, forks, language, description, topics"""

    def _get_issues(self, slug: str, state: str, max: int) -> list:
        """Paginate /repos/{slug}/issues — include comments count, reactions"""

    def _get_discussions_graphql(self, slug: str) -> list:
        """
        Use GitHub GraphQL API (same token, free):
        POST https://api.github.com/graphql
        Query: repository discussions, categories, upvoteCount, comments
        """

    def _search_roadmap(self, slug: str) -> str:
        """Try ROADMAP.md, docs/roadmap.md, .github/ROADMAP.md, wiki"""
```

### 4.2 Community Intelligence

```python
class CommunityIntelligence:
    """Scrape Hacker News, Reddit, and web for project sentiment & requests."""

    def gather_hn(self, project_name: str, repo_slug: str) -> list:
        """
        HN Algolia API (free, no key):
        GET https://hn.algolia.com/api/v1/search?query={project_name}&tags=story
        Parse: title, url, score, num_comments, created_at
        Also fetch top comment threads for feature requests.
        """

    def gather_reddit(self, project_name: str) -> list:
        """
        Reddit JSON API (no key for read):
        GET https://www.reddit.com/search.json?q={project_name}&sort=hot&limit=25
        Also search r/programming, r/opensource, r/linux (if relevant)
        Parse: title, selftext, score, num_comments, url
        """

    def gather_stackoverflow(self, project_name: str) -> list:
        """
        StackOverflow API (free, no key for read):
        GET https://api.stackexchange.com/2.3/search/advanced
            ?q={project_name}&tagged={tag}&site=stackoverflow&filter=withbody
        Focus on: unanswered questions (gap in docs/features), highly voted questions
        """

    def gather_libraries_io(self, repo_slug: str) -> dict:
        """
        Libraries.io API (60 req/min free):
        GET https://libraries.io/api/github/{repo_slug}/dependencies
        GET https://libraries.io/api/github/{repo_slug}/dependents
        Returns: who depends on this project (impact score)
        """

    def web_crawl_docs(self, project_name: str, homepage: str) -> str:
        """
        httpx + BeautifulSoup4 crawl of official docs:
        1. Fetch homepage HTML
        2. Extract links matching docs/changelog/roadmap patterns
        3. Fetch each (max 10 pages, 500ms delay between requests — be polite)
        4. Extract text content, strip HTML
        Returns: concatenated text (max 50k chars)
        """
```

### 4.3 Intelligence Synthesis (LLM step)

After gathering raw data, pass it to the LLM:

```python
INTELLIGENCE_SYNTHESIS_PROMPT = """
You are an expert open-source analyst. Analyse the following data about the project
"{project_name}" and extract structured intelligence.

DATA:
{raw_data_json}

Return ONLY a JSON object with this exact schema:
{{
  "project_summary": "2-3 sentence description of what this project does",
  "mission": "The project's core mission in 1 sentence",
  "tech_stack": ["language1", "framework2"],
  "maturity": "experimental|alpha|beta|stable|mature",
  "community_size": "tiny|small|medium|large|massive",
  "activity_level": "dormant|low|moderate|active|very_active",
  "top_pain_points": [
    {{"title": "...", "source": "github_issue|reddit|hn|stackoverflow",
      "evidence": "direct quote or reference", "frequency": 1-10}}
  ],
  "missing_features": [
    {{"feature": "...", "requested_by": "# of mentions", "priority": "high|medium|low"}}
  ],
  "roadmap_items": ["item1", "item2"],
  "contribution_style": "strict|moderate|welcoming",
  "getting_started": "How to set up the dev environment in 2-3 sentences",
  "key_maintainers": ["github_username1"],
  "related_projects": ["project1"]
}}
"""
```

---

## 5. Phase 2: Repo Deep Analysis

**File:** `ocis/analysis/repo_analyzer.py`

### 5.1 Code Structure Analysis

```python
class RepoAnalyzer:
    """
    Deep structural analysis of the local clone.
    Uses tree-sitter for AST parsing (free, offline).
    """

    def analyze(self, repo_path: str) -> dict:
        return {
            "file_tree": self._build_file_tree(repo_path),
            "languages": self._detect_languages(repo_path),
            "entry_points": self._find_entry_points(repo_path),
            "modules": self._map_module_structure(repo_path),
            "complexity": self._score_complexity(repo_path),
            "todos": self._extract_todos(repo_path),
            "test_coverage_gaps": self._find_untested_modules(repo_path),
            "doc_gaps": self._find_undocumented_functions(repo_path),
            "dependency_audit": self._audit_dependencies(repo_path),
            "ci_analysis": self._parse_ci_config(repo_path),
            "code_style": self._detect_code_style(repo_path),
        }

    def _extract_todos(self, repo_path: str) -> list:
        """
        grep -rn "TODO\|FIXME\|HACK\|XXX\|BUG\|OPTIMIZE" {repo_path}
        Parse file, line, comment text.
        Skip: vendor/, node_modules/, .git/, build/, dist/
        """

    def _find_untested_modules(self, repo_path: str) -> list:
        """
        Map source files → test files.
        Python: src/foo.py → tests/test_foo.py
        JS: src/foo.js → src/foo.test.js or __tests__/foo.test.js
        C: src/foo.c → test/test_foo.c
        Return source files with no corresponding test.
        """

    def _find_undocumented_functions(self, repo_path: str) -> list:
        """
        Use tree-sitter to parse function/class definitions.
        Flag: public functions with no docstring/JSDoc/comment.
        Skip: private (_prefixed) functions.
        """

    def _audit_dependencies(self, repo_path: str) -> dict:
        """
        Read: requirements.txt, package.json, go.mod, Cargo.toml, pom.xml
        Check each dep version against latest using Libraries.io or PyPI/NPM APIs.
        Return: {outdated: [...], vulnerable: [...]} 
        """

    def _parse_ci_config(self, repo_path: str) -> dict:
        """
        Detect: .github/workflows/*.yml, .travis.yml, .circleci/config.yml, Jenkinsfile
        Extract: test commands, lint commands, coverage commands
        Flag: missing lint, missing coverage reporting, no security scan
        """

    def _score_complexity(self, repo_path: str) -> dict:
        """
        Use radon (pip install radon) for Python:
          radon cc {file} -s → cyclomatic complexity per function
          radon mi {file} → maintainability index
        For JS/TS: use escomplex via subprocess
        Return: top 10 most complex files/functions
        """
```

### 5.2 Embed Codebase into Qdrant

```python
class CodebaseEmbedder:
    """
    Chunk and embed all source files for RAG-based issue→code mapping.
    Reuses existing ocis/core/embeddings/pipeline.py.
    """

    CHUNK_SIZE = 500     # tokens per chunk
    CHUNK_OVERLAP = 50   # token overlap between chunks

    def embed_repo(self, repo_path: str, job_id: str):
        """
        1. Walk all source files (skip binary, vendor, build)
        2. Split into chunks with file path + line range metadata
        3. Embed with sentence-transformers/all-MiniLM-L6-v2 (local, free)
        4. Upsert into Qdrant collection: f"ocis_{job_id}"
        5. Store: chunk_text, file_path, start_line, end_line, language
        """

    def search(self, job_id: str, query: str, top_k: int = 5) -> list:
        """
        Vector search: embed query → nearest chunks in Qdrant collection.
        Returns: [{"file": "...", "lines": "10-45", "snippet": "...", "score": 0.87}]
        """
```

---

## 6. Phase 3: Correlation Engine

**File:** `ocis/correlation/engine.py`

```python
class CorrelationEngine:
    """
    The heart of OCIS.
    Maps external intelligence → internal code gaps → ranked opportunities.
    """

    def correlate(self, intelligence: dict, analysis: dict,
                  embedder: CodebaseEmbedder, job_id: str) -> list:
        """
        Returns top-10 ranked contribution opportunities.
        Each opportunity has:
        {
          "id": "opp_001",
          "type": "bug_fix|feature|docs|test|refactor|perf|security|deps",
          "title": "Add async support to the file watcher module",
          "description": "...",
          "evidence": {
            "github_issues": ["#123", "#456"],
            "community_mentions": ["HN comment link", "Reddit thread"],
            "roadmap_item": "Q3 2025: async rewrite",
            "code_location": {"file": "src/watcher.py", "lines": "45-120"}
          },
          "impact_score": 9.2,        # How much the community wants this
          "difficulty_score": 4.5,     # 1=trivial, 10=expert-only
          "novelty_score": 8.0,        # How unique/impressive for your resume
          "visibility_score": 8.5,     # Star project? Many dependents?
          "composite_score": 8.6,      # Weighted: impact×0.35 + novelty×0.30 + visibility×0.20 + (10-difficulty)×0.15
          "estimated_loc": 150,        # Lines of code to implement
          "files_to_touch": ["src/watcher.py", "tests/test_watcher.py"],
          "related_issues_to_close": ["#123"],
          "pr_title_suggestion": "feat(watcher): add async file watching with asyncio",
          "pr_labels": ["enhancement", "async"],
        }
        """

    def _map_issues_to_code(self, issues: list, embedder, job_id: str) -> list:
        """
        For each GitHub issue title+body:
        1. embed it
        2. search Qdrant for nearest code chunks
        3. Return: issue + relevant_files
        """

    def _score_opportunity(self, opp: dict, intelligence: dict) -> float:
        """
        composite = (
            opp["impact"]     * 0.35 +
            opp["novelty"]    * 0.30 +
            opp["visibility"] * 0.20 +
            (10 - opp["difficulty"]) * 0.15
        )
        """

    def _deduplicate(self, opportunities: list) -> list:
        """Remove near-duplicate opportunities using embedding cosine similarity."""
```

### 6.1 LLM Scoring Prompt

```python
OPPORTUNITY_SCORING_PROMPT = """
You are an expert open-source contribution strategist helping a developer build
an impressive GitHub profile. Evaluate this contribution opportunity:

PROJECT: {project_name} ({stars} stars, {maturity} maturity)
OPPORTUNITY: {opportunity_title}
DESCRIPTION: {opportunity_description}
EVIDENCE:
- GitHub issues: {issue_list}
- Community signals: {community_signals}
- Code location: {code_location}

Score this opportunity on these dimensions (1-10 scale, 1 decimal):

1. impact_score: How much does the community need/want this?
   (10=critical blocker for many users, 1=minor cosmetic)

2. difficulty_score: How hard is this to implement correctly?
   (10=requires kernel expertise, 1=fix a typo)

3. novelty_score: How impressive is this for a developer's resume?
   (10=pioneering new approach, 1=routine maintenance)

4. visibility_score: How visible will this contribution be?
   (10=affects all users of a massive project, 1=internal cleanup)

5. feasibility_score: Can an individual contributor realistically do this?
   (10=clearly scoped, well-documented codebase, 1=needs maintainer access)

Return ONLY valid JSON:
{{
  "impact_score": 0.0,
  "difficulty_score": 0.0,
  "novelty_score": 0.0,
  "visibility_score": 0.0,
  "feasibility_score": 0.0,
  "reasoning": "2-3 sentences explaining the scores",
  "suggested_approach": "How to tackle this contribution in 3-5 sentences",
  "estimated_hours": 0,
  "risks": ["risk1", "risk2"]
}}
"""
```

---

## 7. Phase 4: Recommendation Generation

**File:** `ocis/recommendation/generator.py`

```python
class RecommendationGenerator:
    """
    Takes ranked opportunities and generates actionable contribution specs.
    """

    def generate(self, opportunities: list, intelligence: dict,
                 analysis: dict) -> list:
        """Generate top-5 detailed contribution recommendations."""
        recommendations = []
        for opp in opportunities[:5]:
            rec = self._generate_one(opp, intelligence, analysis)
            if rec["quality_score"] >= OCIS_CONTRIBUTION_QUALITY_MIN:
                recommendations.append(rec)
        return recommendations

    def _generate_one(self, opportunity: dict, intelligence: dict,
                      analysis: dict) -> dict:
        """
        LLM call to generate the full contribution spec.
        Returns a recommendation dict (schema below).
        """

RECOMMENDATION_GENERATION_PROMPT = """
You are a world-class open-source contributor. Generate a complete, actionable
contribution plan for this opportunity in the {project_name} project.

OPPORTUNITY: {opportunity_json}
PROJECT CONTEXT: {intelligence_summary}
CODE ANALYSIS: {analysis_summary}
CONTRIBUTING GUIDE: {contributing_md}
CODE STYLE: {code_style}

Generate a complete contribution spec. Return ONLY valid JSON:
{{
  "branch_name": "feat/async-file-watcher",
  "pr_title": "feat(watcher): add async file watching support using asyncio",
  "pr_description": "## Summary\\n...\\n## Changes\\n- ...\\n## Testing\\n...\\n## Related Issues\\nCloses #123",
  "commit_messages": [
    "feat(watcher): add AsyncFileWatcher class with asyncio backend",
    "test(watcher): add async watcher unit tests",
    "docs(watcher): document async watcher API"
  ],
  "files_to_create": [
    {{"path": "src/async_watcher.py", "description": "New async watcher implementation"}}
  ],
  "files_to_modify": [
    {{"path": "src/watcher.py", "changes": "Add backwards-compat async() method"}}
  ],
  "implementation_plan": [
    "Step 1: Create AsyncFileWatcher class in src/async_watcher.py",
    "Step 2: Implement watch() coroutine using asyncio.get_event_loop()",
    "Step 3: Add tests in tests/test_async_watcher.py",
    "Step 4: Update README.md with async usage example"
  ],
  "code_snippets": {{
    "src/async_watcher.py": "import asyncio\\n\\nclass AsyncFileWatcher:\\n    ..."
  }},
  "quality_score": 0.85,
  "resume_talking_point": "Implemented async file watching for {project_name} ({stars} stars), reducing I/O blocking by enabling non-blocking watch loops via asyncio."
}}
"""
```

---

## 8. Phase 5: Human-in-the-Loop Dashboard

**File:** `ocis/dashboard/` — Full React SPA

### 8.1 Dashboard Architecture

Build a **single-page React app** served by FastAPI at `/ui`. Design aesthetic:
**Terminal-meets-intelligence** — dark background (#0d1117), green/cyan accent (#00ff9f, #00b4d8),
monospace font (JetBrains Mono or Fira Code), card-based layout, smooth transitions.

### 8.2 Dashboard Pages / Views

```
/ (Home)
├── "Analyse a Repo" input box (GitHub URL)
├── Recent jobs list with status badges
└── Stats: total PRs opened, total stars across contributed projects

/job/:id (Live Analysis View)
├── Phase progress bar (Phase 1→6, animated)
├── Live log stream (SSE from backend)
├── Intelligence summary cards (project info, community signals)
├── Repo analysis cards (complexity, TODOs, gaps)
└── Loading skeleton while processing

/job/:id/review (Human-in-the-Loop Review — THE KEY PAGE)
├── Header: project info (name, stars, description, avatar)
├── Left panel: Intelligence summary
│   ├── "What the community wants" (top pain points)
│   ├── "Project roadmap" items
│   └── "Key stats" (stars, forks, activity)
├── Right panel: Contribution Recommendations (cards)
│   ├── Each card shows:
│   │   ├── Title + type badge (feature/bug/docs/test)
│   │   ├── Impact/Difficulty/Novelty score bars
│   │   ├── Evidence (linked issues, community quotes)
│   │   ├── Estimated effort (hours, LOC)
│   │   ├── Resume talking point (why this is impressive)
│   │   ├── [Approve] [Edit] [Reject] buttons
│   │   └── Expandable: implementation plan + code snippets
│   └── Drag to reorder priority
├── Bottom bar: "Execute N Approved Contributions →" button
└── Confirmation modal before execution

/job/:id/execution (Phase 6 Live View)
├── Fork created: link to fork
├── Per-recommendation execution status
│   ├── Implementing... (spinner)
│   ├── Tests running... 
│   ├── PR created: [link]
│   └── Failed: [reason]
└── Final summary: N PRs opened to {project_name}
```

### 8.3 API Endpoints for Dashboard

Add to `ocis/api/main.py`:

```python
# Job lifecycle
POST   /api/v1/jobs                    # Submit repo URL → returns job_id
GET    /api/v1/jobs                    # List all jobs
GET    /api/v1/jobs/{job_id}           # Job state + latest data
GET    /api/v1/jobs/{job_id}/logs      # SSE stream of live logs

# Human-in-the-loop
GET    /api/v1/jobs/{job_id}/review    # Get recommendations for review
POST   /api/v1/jobs/{job_id}/approve   # Submit approved list + priority order
POST   /api/v1/jobs/{job_id}/execute   # Trigger Phase 6 (after approval)

# Execution
GET    /api/v1/jobs/{job_id}/results   # Final PR results

# System
GET    /api/v1/health                  # Health check
GET    /api/v1/stats                   # Global stats (total PRs, projects)
```

### 8.4 SSE Live Log Streaming

```python
from fastapi.responses import StreamingResponse
import asyncio

@app.get("/api/v1/jobs/{job_id}/logs")
async def stream_logs(job_id: str, since: int = 0):
    """Server-Sent Events stream of job logs."""
    async def event_generator():
        last_idx = since
        while True:
            job = get_job(job_id)
            if not job:
                yield "data: {\"error\": \"job not found\"}\n\n"
                break
            new_logs = job.logs[last_idx:]
            for log in new_logs:
                yield f"data: {json.dumps(log)}\n\n"
                last_idx += 1
            if job.status in (OCISJobStatus.DONE, OCISJobStatus.FAILED,
                              OCISJobStatus.AWAITING_HITL):
                yield f"data: {{\"status\": \"{job.status}\"}}\n\n"
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## 9. Phase 6: Autonomous Execution

**File:** `ocis/execution/executor.py`

### 9.1 Fork the Repository First

Extend `ocis/contribution/engine.py`:

```python
def fork_repository(self, repo_slug: str) -> dict:
    """
    Fork upstream repo to GITHUB_USERNAME account.
    POST /repos/{repo_slug}/forks
    Returns: {"fork_url": "https://github.com/username/repo", "fork_slug": "username/repo"}

    Handle: repo already forked (check GET /repos/{username}/{repo_name} first).
    Wait for fork to be ready (GitHub takes ~10s): poll GET /repos/{fork_slug} until ready.
    """

def sync_fork(self, fork_slug: str, upstream_slug: str) -> bool:
    """
    Keep fork in sync before implementing:
    POST /repos/{fork_slug}/merge-upstream
    body: {"branch": "main"}
    """
```

### 9.2 Implementation Agent

```python
class ImplementationAgent:
    """
    Given a recommendation spec, implements the code changes in the local clone.
    Uses LLM for code generation, tree-sitter for AST validation.
    """

    def implement(self, recommendation: dict, repo_path: str,
                  intelligence: dict) -> dict:
        """
        1. Read files to modify (full content)
        2. For each file: LLM generates the new version
        3. Write new files / overwrite modified files
        4. Run syntax check (python -m py_compile, eslint --fix, etc.)
        5. Return: {"success": bool, "files_changed": [...], "diff": "..."}
        """

CODE_GENERATION_PROMPT = """
You are an expert {language} developer contributing to {project_name}.

TASK: {implementation_task}

EXISTING FILE ({file_path}):
```{language}
{existing_code}
```

STYLE GUIDE:
{code_style_notes}

CONTRIBUTING REQUIREMENTS:
{contributing_requirements}

Generate the COMPLETE updated file content. Follow the existing code style exactly.
Add only what is needed — do not refactor unrelated code.
Include docstrings/comments following the project's convention.
Return ONLY the raw file content, no markdown fences, no explanation.
"""
```

### 9.3 Quality Gate Before PR

```python
class ContributionQualityScorer:
    """
    Before opening PR, verify the implementation meets quality bar.
    Reuses ocis/patch/scorer.py logic.
    """

    def score(self, recommendation: dict, original_files: dict,
              new_files: dict, repo_path: str) -> dict:
        return {
            "syntax_valid": self._check_syntax(new_files),
            "tests_pass": self._run_tests(repo_path),
            "diff_size_ok": self._check_diff_size(original_files, new_files),
            "style_compliant": self._check_style(repo_path),
            "overall": 0.0,       # weighted composite
            "passes_threshold": False,
        }

    def _run_tests(self, repo_path: str) -> bool:
        """
        Detect test runner: pytest, npm test, go test, cargo test, make test
        Run with 60s timeout. Return True if exit code 0.
        """

    def _check_syntax(self, files: dict) -> bool:
        """Per-language syntax check without running code."""
```

---

## 10. PR Description Template

Every PR opened by OCIS must be impressive and professional:

```python
PR_DESCRIPTION_TEMPLATE = """
## 🎯 Summary

{summary}

## 🔍 Motivation

{motivation_from_community_signals}

> Community signal: "{evidence_quote}" — [Source: {source_link}]

## 📝 Changes

{changes_list}

## 🧪 Testing

{testing_description}

```bash
{test_commands}
```

## 📊 Impact

{impact_description}

## 🔗 Related Issues

{related_issues}

---
*This contribution was identified through analysis of {stars}-star project usage patterns,
{github_issue_count} open issues, and community feedback from {community_sources}.*
"""
```

---

## 11. Project Structure — Final Layout

```
opensource/
├── .env                        # your secrets (gitignored)
├── .env.example                # template (committed)
├── .gitignore
├── requirements.txt            # all deps
├── README.md                   # project overview
├── run.py                      # entry: python run.py
│
├── ocis/                       # main package
│   ├── __init__.py
│   ├── config.py               # ← Section 1.1
│   │
│   ├── core/
│   │   ├── llm/
│   │   │   └── client.py       # ← Section 2 (OpenRouter wrapper)
│   │   ├── embeddings/         # keep existing, update model
│   │   ├── graph/              # keep existing
│   │   ├── parsers/            # keep existing + extend
│   │   └── rag/                # keep existing
│   │
│   ├── intelligence/
│   │   ├── __init__.py
│   │   ├── gatherer.py         # ← Section 4 (Phase 1)
│   │   ├── github_client.py    # GitHub REST + GraphQL
│   │   ├── community.py        # HN, Reddit, SO scraping
│   │   └── web_crawler.py      # httpx + BS4 doc crawling
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── repo_analyzer.py    # ← Section 5 (Phase 2)
│   │   ├── embedder.py         # Qdrant embedding
│   │   └── complexity.py       # radon + escomplex wrappers
│   │
│   ├── correlation/
│   │   ├── __init__.py
│   │   └── engine.py           # ← Section 6 (Phase 3)
│   │
│   ├── recommendation/
│   │   ├── __init__.py
│   │   └── generator.py        # ← Section 7 (Phase 4)
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── executor.py         # ← Section 9 (Phase 6)
│   │   └── impl_agent.py       # LLM code generation
│   │
│   ├── contribution/
│   │   └── engine.py           # extended: fork + PR
│   │
│   ├── validation/
│   │   └── runner.py           # keep existing
│   │
│   ├── agents/
│   │   └── orchestrator.py     # ← Section 3.1 (6-phase pipeline)
│   │
│   ├── api/
│   │   └── main.py             # FastAPI + SSE endpoints
│   │
│   └── dashboard/              # React SPA (built → static files)
│       ├── index.html
│       ├── src/
│       │   ├── App.jsx
│       │   ├── pages/
│       │   │   ├── Home.jsx
│       │   │   ├── JobView.jsx
│       │   │   ├── ReviewPage.jsx   # ← THE HiTL page
│       │   │   └── Execution.jsx
│       │   ├── components/
│       │   │   ├── PhaseProgress.jsx
│       │   │   ├── LogStream.jsx      # SSE consumer
│       │   │   ├── RecommendationCard.jsx
│       │   │   ├── ScoreBar.jsx
│       │   │   └── IntelligencePanel.jsx
│       │   └── hooks/
│       │       ├── useJobSSE.js      # SSE hook
│       │       └── useJob.js
│       └── package.json
│
├── linux/                      # sample target (Linux kernel scaffold)
└── ase/                        # legacy (keep for reference, deprecate)
```

---

## 12. `requirements.txt`

```txt
# Web framework
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-dotenv>=1.0.0
pydantic>=2.7.0

# HTTP & scraping — all free
httpx>=0.27.0                  # async HTTP client
beautifulsoup4>=4.12.0         # HTML parsing
lxml>=5.2.0                    # fast BS4 parser
praw>=7.7.0                    # Reddit API

# GitHub
PyGithub>=2.3.0                # GitHub REST wrapper

# LLM
openai>=1.30.0                 # OpenAI-compatible SDK (works with OpenRouter)

# Embeddings & vector DB — local/free
sentence-transformers>=3.0.0   # local embeddings, no API needed
qdrant-client>=1.9.0           # free self-hosted vector DB
torch>=2.3.0                   # sentence-transformers backend

# Code analysis
radon>=6.0.0                   # Python complexity metrics
tree-sitter>=0.23.0            # AST parsing (multi-language)
gitpython>=3.1.43              # Git operations

# Database
sqlalchemy>=2.0.30             # ORM
aiosqlite>=0.20.0              # async SQLite

# Utils
tenacity>=8.3.0                # retry logic
structlog>=24.1.0              # structured logging
rich>=13.7.0                   # beautiful terminal output
```

---

## 13. Build Order — Implement in This Sequence

Follow this order to always have a working system at each step:

```
Sprint 1 — Foundation (Days 1-2)
  [1] ocis/config.py                        (replace ase/config.py)
  [2] ocis/core/llm/client.py               (OpenRouter wrapper, test with curl)
  [3] ocis/agents/orchestrator.py           (new state machine, stubs for phases)
  [4] ocis/api/main.py                      (update endpoints, remove security imports)
  [5] python run.py → API boots, /docs works

Sprint 2 — Intelligence (Days 3-4)
  [6] ocis/intelligence/github_client.py    (GitHub REST + GraphQL)
  [7] ocis/intelligence/community.py        (HN, Reddit free APIs)
  [8] ocis/intelligence/gatherer.py         (orchestrate all scrapers)
  [9] Test: python -m ocis.intelligence.gatherer --repo torvalds/linux

Sprint 3 — Analysis (Days 5-6)
  [10] ocis/analysis/repo_analyzer.py       (file tree, TODOs, gaps)
  [11] ocis/analysis/embedder.py            (Qdrant + sentence-transformers)
  [12] Start Qdrant: docker run -p 6333:6333 qdrant/qdrant
  [13] Test: embed a small repo, run vector search

Sprint 4 — Intelligence Engine (Days 7-8)
  [14] ocis/correlation/engine.py           (issue→code mapping + scoring)
  [15] ocis/recommendation/generator.py     (LLM-powered specs)
  [16] Test: full Phase 1-4 pipeline on a real repo (e.g., psf/black)

Sprint 5 — Dashboard (Days 9-11)
  [17] ocis/dashboard/ React app scaffold
  [18] Home + JobView + LogStream (SSE)
  [19] ReviewPage (the HiTL review interface)
  [20] Full frontend ↔ backend integration test

Sprint 6 — Execution (Days 12-14)
  [21] ocis/contribution/engine.py           (add fork_repository())
  [22] ocis/execution/impl_agent.py          (LLM code generation)
  [23] ocis/execution/executor.py            (Phase 6 orchestration)
  [24] End-to-end dry_run=True test
  [25] End-to-end dry_run=False on a real "good-first-issue"
```

---

## 14. Testing Strategy

### 14.1 Unit Tests (per module)
```bash
pytest ocis/tests/ -v --tb=short
```

### 14.2 Integration Test — Full Pipeline Dry Run
```python
# test_full_pipeline.py
"""
Runs the complete OCIS pipeline against a real public repo (dry_run=True).
Uses: https://github.com/psf/black (Python formatter — welcoming to contributions)
Expected: Phase 1-4 complete, dashboard review page shows recommendations.
"""
TARGET_REPO = "https://github.com/psf/black"
```

### 14.3 Free Repos Good for First Contributions
Start with these — actively maintained, welcoming, diverse complexity:
- `psf/black` — Python formatter, great docs
- `tiangolo/fastapi` — FastAPI itself (meta!)
- `httpie/httpie` — HTTP client, clean codebase
- `nicklockwood/SwiftFormat` — Swift formatter
- `charmbracelet/glow` — Markdown renderer in Go

For ambitious contributions:
- `torvalds/linux` — already in your repo scaffold
- `python/cpython` — Python itself
- `rust-lang/rust` — Rust compiler

---

## 15. Resume Integration

Every PR opened by OCIS should generate a resume bullet automatically:

```python
def generate_resume_bullet(recommendation: dict, pr_result: dict,
                            intelligence: dict) -> str:
    """
    Template:
    "Contributed {contribution_type} to {project_name} ({stars}★) —
     {one_line_description}; PR merged by {maintainer} within {days} days.
     [{pr_url}]"

    Example:
    "Contributed async file watching feature to watchdog (3.2k★) —
     implemented non-blocking watch loops via asyncio, adopted by 847 dependent
     projects; PR merged within 4 days. [github.com/gorakhargosh/watchdog/pull/1023]"
    """
```

Add a `/api/v1/resume` endpoint that returns all successful PRs formatted as
resume bullets in Markdown and JSON.

---

## 16. Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| LLM provider | OpenRouter free tier | Zero cost, 50+ models, OpenAI-compatible |
| Primary model | llama-3.3-70b:free | 128k context, strong reasoning |
| Code model | deepseek-r1:free | Best free model for code tasks |
| Embeddings | sentence-transformers local | No API cost, runs on CPU |
| Vector DB | Qdrant self-hosted | Free, Docker, production-grade |
| Web scraping | httpx + BS4 | Async, lightweight, no headless browser needed |
| GitHub data | REST + GraphQL | Free 5000 req/hr with PAT |
| Community | HN Firebase + Reddit JSON | Both free, no key required |
| Database | SQLite → Postgres | Zero setup dev, scale to prod |
| Frontend | React SPA served by FastAPI | Single deploy, no separate server |
| Auth | GitHub OAuth (optional) | Reuse GitHub identity |

---

## 17. Environment Setup (Zero Cost)

```bash
# 1. Clone your repo
git clone https://github.com/Ravant2005/opensource.git
cd opensource

# 2. Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Qdrant (free vector DB)
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/qdrant_storage:/qdrant/storage \
  qdrant/qdrant

# 4. Copy and fill secrets
cp .env.example .env
# Fill: OPENROUTER_API_KEY, GITHUB_TOKEN, GITHUB_USERNAME

# 5. Start OCIS
python run.py
# → http://127.0.0.1:8001
# → http://127.0.0.1:8001/ui  (dashboard)
# → http://127.0.0.1:8001/docs (API explorer)
```

---

## 18. OpenRouter Free Model Selection Guide

Use the right model for each phase to maximise quality within free limits:

| Phase | Task | Best Free Model | Why |
|---|---|---|---|
| Phase 1 | Intelligence synthesis | `llama-3.3-70b:free` | Strong at summarisation |
| Phase 2 | Code understanding | `deepseek-r1:free` | Best free code model |
| Phase 3 | Opportunity scoring | `llama-3.3-70b:free` | Structured JSON output |
| Phase 4 | Recommendation spec | `deepseek-r1:free` | Detailed code planning |
| Phase 6 | Code generation | `deepseek-r1:free` | Follows existing style |
| PR desc | PR writing | `google/gemma-3-27b-it:free` | Clean prose |

Rate limit strategy:
- Cache all LLM responses in SQLite by `hash(prompt)` — re-runs are instant and free
- Batch requests: instead of 1 issue per call, send 10 issues in one call
- Use streaming for Phase 6 code generation (better UX, same token budget)

---

## 19. What Makes This World-Class

1. **Not just a PR bot** — OCIS understands *why* something matters to the community before touching a line of code. This prevents "noise PRs" that maintainers hate.

2. **Resume-aware scoring** — the composite score explicitly weights novelty and visibility, so you don't spend time on invisible bug fixes when a visible feature would land better.

3. **Evidence-backed PRs** — every PR description quotes real GitHub issues and community discussions, making maintainers take it seriously.

4. **Human-in-the-loop gate** — you stay in control. The system proposes; you decide. This is what separates OCIS from automated spam bots.

5. **Learning loop** — track which PRs get merged, which get ignored, and feed that signal back into scoring weights using `ocis/learning/`.

6. **Polite scraping** — 500ms delay between web requests, respects `robots.txt`, uses the official APIs wherever possible. You won't get banned.

---

*Build this. Every PR merged to a top open-source project is a permanent, public,
verifiable proof of your engineering ability — more powerful than any certification.*