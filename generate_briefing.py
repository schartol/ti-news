#!/usr/bin/env python3
"""
Transatlantic Intelligence News Briefing Generator
Fetches AI/gov-tech news via RSS feeds, scores with Claude, generates HTML.
"""

import anthropic
import feedparser
import json
import re
from datetime import datetime, timedelta

# --- RSS Feeds covering AI, gov-tech, defense, EU policy ---
RSS_FEEDS = [
    # US Gov Tech
    ("https://www.nextgov.com/rss/all/", "gov-us", "Nextgov/FCW"),
    ("https://federalnewsnetwork.com/category/technology/feed/", "gov-us", "Federal News Network"),
    ("https://www.govtech.com/rss.xml", "gov-us", "GovTech"),
    # Defense / Intel
    ("https://www.defenseone.com/rss/technology/", "defense", "Defense One"),
    ("https://breakingdefense.com/feed/", "defense", "Breaking Defense"),
    # EU Policy
    ("https://www.euractiv.com/sections/digital/feed/", "eu", "Euractiv"),
    ("https://feeds.feedburner.com/euobserver/9all", "eu", "EUobserver"),
    # AI Industry
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "company", "TechCrunch"),
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "company", "The Verge"),
    ("https://venturebeat.com/category/ai/feed/", "enterprise", "VentureBeat"),
    # Policy / Regulation
    ("https://www.brookings.edu/topic/artificial-intelligence/feed/", "policy", "Brookings"),
    ("https://www.lawfaremedia.org/feed", "policy", "Lawfare"),
]

def fetch_rss_articles(max_age_days=7, max_per_feed=8):
    """Fetch recent articles from RSS feeds."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    articles = []

    for feed_url, category, source_name in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break
                # Filter for AI-related content
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                text = (title + " " + summary).lower()
                ai_keywords = ["artificial intelligence", " ai ", "ai-", "machine learning",
                               "large language model", "llm", "chatgpt", "openai", "anthropic",
                               "claude", "gemini", "automation", "autonomous", "algorithm",
                               "deepfake", "generative", "neural", "gpt", "copilot"]
                if not any(kw in text for kw in ai_keywords):
                    continue

                # Strip HTML from summary
                clean_summary = re.sub(r'<[^>]+>', '', summary)[:500]

                articles.append({
                    "title": title,
                    "summary": clean_summary,
                    "url": entry.get("link", ""),
                    "source": source_name,
                    "category": category,
                    "published": entry.get("published", ""),
                })
                count += 1
        except Exception as e:
            print(f"Warning: Could not fetch {feed_url}: {e}")

    print(f"Fetched {len(articles)} AI-related articles from RSS feeds")
    return articles


def score_and_curate_with_claude(articles):
    """Send articles to Claude for scoring, blog angle generation, and curation."""
    client = anthropic.Anthropic()

    articles_text = json.dumps(articles, indent=2)

    prompt = f"""You are curating the daily news briefing for "Transatlantic Intelligence," a blog about AI adoption in government, written from a transatlantic (US + EU) perspective.

The blog is written by:
- Suzanne Chartol: runs Customer Experience at CORAS, a US gov-tech company
- Her daughter: works at the European Stability Mechanism doing AI adoption, did a Schuman traineeship at the European Parliament

Here are today's candidate articles:

{articles_text}

Your job:
1. Select the 20-25 most relevant and interesting stories. Deduplicate similar stories — pick the best version.
2. For each selected story, provide:
   - A compelling rewritten title (concise, specific)
   - A 1-2 sentence summary
   - 4-5 key bullet points
   - A blog angle specific to Transatlantic Intelligence (reference Suzanne's CORAS work or her daughter's ESM/EU Parliament background where natural)
   - Category: one of "gov-us", "eu", "defense", "company", "enterprise", "policy", "infra"
   - Scores (1-5 each):
     * convo: How provocative/debate-worthy is this? Will readers want to discuss it?
     * gov: How directly relevant to government AI adoption, policy, or public sector?
     * impact: How significant for the overall AI domain?

Return ONLY a JSON array of objects with this exact structure (no markdown, no commentary):
[
  {{
    "title": "...",
    "summary": "...",
    "keyPoints": ["...", "...", "...", "...", "..."],
    "blogAngle": "...",
    "category": "gov-us|eu|defense|company|enterprise|policy|infra",
    "source": "Source Name",
    "sourceUrl": "https://...",
    "scores": {{ "convo": N, "gov": N, "impact": N }}
  }}
]

Sort by total score descending. Aim for 3-6 stories scoring 12+/15."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}]
    )

    # Extract JSON from response with robust parsing
    text = response.content[0].text

    def try_parse_json(s):
        """Try to parse JSON, with automatic repair for common issues."""
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # Fix trailing commas before ] or }
        s = re.sub(r',\s*([}\]])', r'\1', s)
        # Fix missing commas between objects: }{ -> },{
        s = re.sub(r'}\s*{', '},{', s)
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # Try to extract individual objects and rebuild array
        objects = []
        for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s):
            try:
                obj = json.loads(m.group())
                if 'title' in obj and 'scores' in obj:
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
        if objects:
            return objects
        return None

    stories = try_parse_json(text)
    if stories is None:
        # Extract from code block
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            stories = try_parse_json(match.group())
        if stories is None:
            raise ValueError("Could not parse Claude's response as JSON")

    print(f"Claude selected and scored {len(stories)} stories")
    return stories


def generate_html(stories):
    """Generate the complete HTML briefing page."""
    today = datetime.now().strftime("%B %d, %Y")
    story_count = len(stories)

    # Build JS stories array
    js_stories = []
    for i, s in enumerate(stories, 1):
        s_obj = {
            "id": i,
            "category": s["category"],
            "tag": {
                "gov-us": "US Gov", "eu": "EU", "defense": "Defense & Intel",
                "company": "AI Companies", "enterprise": "Enterprise AI",
                "policy": "Policy", "infra": "Infrastructure"
            }.get(s["category"], s["category"]),
            "tagClass": {
                "gov-us": "tag-gov-us", "eu": "tag-eu", "defense": "tag-defense",
                "company": "tag-company", "enterprise": "tag-enterprise",
                "policy": "tag-policy", "infra": "tag-infra"
            }.get(s["category"], "tag-policy"),
            "title": s["title"],
            "summary": s["summary"],
            "keyPoints": s["keyPoints"],
            "blogAngle": s["blogAngle"],
            "source": s["source"],
            "sourceUrl": s["sourceUrl"],
            "scores": s["scores"]
        }
        js_stories.append(s_obj)

    stories_json = json.dumps(js_stories, indent=2)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="TI News">
<title>Transatlantic Intelligence - News Briefing</title>
<style>
:root {{
  color-scheme: light;
  --bg: #FAFAFA; --card-bg: #FFFFFF; --text: #1a1a2e; --text-secondary: #555;
  --accent: #2D5BFF; --accent-light: #EEF2FF; --border: #E5E7EB;
  --tag-gov: #059669; --tag-gov-bg: #ECFDF5;
  --tag-eu: #2563EB; --tag-eu-bg: #EFF6FF;
  --tag-defense: #DC2626; --tag-defense-bg: #FEF2F2;
  --tag-company: #7C3AED; --tag-company-bg: #F5F3FF;
  --tag-enterprise: #D97706; --tag-enterprise-bg: #FFFBEB;
  --tag-policy: #0891B2; --tag-policy-bg: #ECFEFF;
  --tag-infra: #6366F1; --tag-infra-bg: #EEF2FF;
  --success: #059669; --success-bg: #ECFDF5;
  --score-high: #059669; --score-mid: #D97706; --score-low: #9CA3AF;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; padding: 16px;
  padding-top: max(16px, env(safe-area-inset-top));
  padding-bottom: max(16px, env(safe-area-inset-bottom));
  -webkit-font-smoothing: antialiased;
}}
.header {{ text-align: center; margin-bottom: 16px; padding-bottom: 14px; border-bottom: 2px solid var(--border); }}
.header h1 {{ font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }}
.header .subtitle {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
.controls {{ margin-bottom: 16px; }}
.sort-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: var(--text-secondary); flex-wrap: wrap; }}
.sort-row label {{ font-weight: 600; white-space: nowrap; }}
.sort-btn {{ padding: 4px 10px; border-radius: 14px; border: 1px solid var(--border); background: var(--card-bg); font-size: 11px; cursor: pointer; color: var(--text-secondary); transition: all 0.15s; -webkit-tap-highlight-color: transparent; }}
.sort-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.sort-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
.filters {{ display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px; scrollbar-width: none; }}
.filters::-webkit-scrollbar {{ display: none; }}
.filter-btn {{ padding: 6px 12px; border-radius: 20px; border: 1px solid var(--border); background: var(--card-bg); font-size: 12px; cursor: pointer; color: var(--text-secondary); white-space: nowrap; flex-shrink: 0; transition: all 0.15s; -webkit-tap-highlight-color: transparent; }}
.filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.filter-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
.score-legend {{ display: flex; gap: 12px; justify-content: center; margin: 12px 0 16px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; }}
.score-legend span {{ display: flex; align-items: center; gap: 4px; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.legend-high {{ background: var(--score-high); }} .legend-mid {{ background: var(--score-mid); }} .legend-low {{ background: var(--score-low); }}
.stories {{ display: flex; flex-direction: column; gap: 12px; }}
.story-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 16px; transition: all 0.2s; position: relative; }}
.story-card.top-pick {{ border-color: var(--score-high); border-width: 2px; }}
.story-top {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }}
.story-top-left {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.story-tag {{ font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 3px 8px; border-radius: 4px; white-space: nowrap; }}
.tag-gov-us {{ color: var(--tag-gov); background: var(--tag-gov-bg); }}
.tag-eu {{ color: var(--tag-eu); background: var(--tag-eu-bg); }}
.tag-defense {{ color: var(--tag-defense); background: var(--tag-defense-bg); }}
.tag-company {{ color: var(--tag-company); background: var(--tag-company-bg); }}
.tag-enterprise {{ color: var(--tag-enterprise); background: var(--tag-enterprise-bg); }}
.tag-policy {{ color: var(--tag-policy); background: var(--tag-policy-bg); }}
.tag-infra {{ color: var(--tag-infra); background: var(--tag-infra-bg); }}
.score-badge {{ display: flex; align-items: center; gap: 4px; font-size: 13px; font-weight: 700; padding: 4px 10px; border-radius: 8px; white-space: nowrap; flex-shrink: 0; }}
.score-high {{ color: var(--score-high); background: #ECFDF5; }}
.score-mid {{ color: var(--score-mid); background: #FFFBEB; }}
.score-low {{ color: var(--score-low); background: #F3F4F6; }}
.score-breakdown {{ display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }}
.score-item {{ font-size: 10px; color: var(--text-secondary); display: flex; align-items: center; gap: 3px; }}
.score-dots {{ display: flex; gap: 2px; }}
.score-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #E5E7EB; }}
.score-dot.filled {{ background: var(--accent); }}
.story-title {{ font-size: 15px; font-weight: 600; line-height: 1.35; margin-bottom: 8px; }}
.story-summary {{ font-size: 13px; color: var(--text-secondary); line-height: 1.55; margin-bottom: 10px; }}
.story-source {{ font-size: 11px; color: var(--text-secondary); margin-bottom: 10px; }}
.story-source a {{ color: var(--accent); text-decoration: none; }}
.blog-angle {{ background: var(--accent-light); border-left: 3px solid var(--accent); padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 10px; }}
.blog-angle-label {{ font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--accent); margin-bottom: 3px; }}
.blog-angle-text {{ font-size: 13px; line-height: 1.5; }}
.expand-toggle {{ font-size: 12px; color: var(--accent); cursor: pointer; background: none; border: none; padding: 4px 0; margin-bottom: 8px; -webkit-tap-highlight-color: transparent; }}
.details-expanded {{ display: none; }} .details-expanded.open {{ display: block; }}
.key-points {{ font-size: 13px; color: var(--text-secondary); margin-bottom: 10px; padding-left: 18px; }}
.key-points li {{ margin-bottom: 3px; line-height: 1.5; }}
.action-row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.action-btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; font-size: 12px; cursor: pointer; color: var(--text-secondary); transition: all 0.15s; -webkit-tap-highlight-color: transparent; }}
.action-btn:hover, .action-btn:active {{ border-color: var(--accent); color: var(--accent); background: var(--accent-light); }}
.action-btn.saved {{ border-color: var(--success); color: var(--success); background: var(--success-bg); cursor: default; }}
.action-btn svg {{ width: 15px; height: 15px; flex-shrink: 0; }}
.share-btn:hover, .share-btn:active {{ border-color: var(--tag-company); color: var(--tag-company); background: var(--tag-company-bg); }}
.top-pick-label {{ font-size: 10px; font-weight: 700; color: var(--score-high); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
.new-badge {{ display: inline-block; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 7px; border-radius: 4px; background: #EF4444; color: white; margin-left: 6px; vertical-align: middle; animation: pulse 2s ease-in-out 3; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
.story-card.read {{ opacity: 0.55; }}
.story-card.read:hover, .story-card.read:active {{ opacity: 0.85; }}
.read-btn {{ cursor: pointer; }}
.read-btn.is-read svg {{ stroke: var(--success); }}
.new-count {{ background: #EF4444; color: white; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 10px; margin-left: 4px; }}
.mark-all-row {{ display: flex; justify-content: flex-end; margin-bottom: 8px; }}
.mark-all-btn {{ font-size: 11px; color: var(--accent); background: none; border: none; cursor: pointer; padding: 4px 8px; -webkit-tap-highlight-color: transparent; }}
.mark-all-btn:hover {{ text-decoration: underline; }}
.toast {{ position: fixed; bottom: max(20px, env(safe-area-inset-bottom, 20px)); left: 50%; transform: translateX(-50%) translateY(100px); background: var(--text); color: white; padding: 12px 24px; border-radius: 10px; font-size: 14px; z-index: 100; transition: transform 0.3s ease; white-space: nowrap; max-width: 90vw; }}
.toast.show {{ transform: translateX(-50%) translateY(0); }}
@keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
.spin {{ animation: spin 1s linear infinite; }}
@media (max-width: 480px) {{ body {{ padding: 12px; }} .story-title {{ font-size: 14px; }} .action-btn {{ padding: 9px 12px; flex: 1; justify-content: center; }} }}
</style>
</head>
<body>
<div class="header">
  <h1>Transatlantic Intelligence</h1>
  <div class="subtitle">News Briefing &mdash; {today}</div>
</div>
<div class="controls">
  <div class="sort-row">
    <label>Sort:</label>
    <button class="sort-btn active" data-sort="score">Blog Score</button>
    <button class="sort-btn" data-sort="convo">Conversation Starter</button>
    <button class="sort-btn" data-sort="gov">Gov Relevance</button>
    <button class="sort-btn" data-sort="impact">Domain Impact</button>
    <button class="sort-btn" data-sort="category">Category</button>
  </div>
  <div class="filters" id="filters">
    <button class="filter-btn active" data-cat="all">All ({story_count})</button>
    <button class="filter-btn" data-cat="new">New <span id="newFilterCount" class="new-count">{story_count}</span></button>
    <button class="filter-btn" data-cat="gov-us">US Gov</button>
    <button class="filter-btn" data-cat="eu">EU</button>
    <button class="filter-btn" data-cat="defense">Defense</button>
    <button class="filter-btn" data-cat="company">AI Co's</button>
    <button class="filter-btn" data-cat="enterprise">Enterprise</button>
    <button class="filter-btn" data-cat="policy">Policy</button>
    <button class="filter-btn" data-cat="infra">Infrastructure</button>
  </div>
</div>
<div class="score-legend">
  <span><span class="legend-dot legend-high"></span> Top pick (12-15)</span>
  <span><span class="legend-dot legend-mid"></span> Strong (8-11)</span>
  <span><span class="legend-dot legend-low"></span> Worth watching (5-7)</span>
</div>
<div class="mark-all-row"><button class="mark-all-btn" id="markAllBtn" onclick="markAllRead()">Mark all as read</button></div>
<div class="stories" id="stories"></div>
<div class="toast" id="toast"></div>
<script>
const stories = {stories_json};
stories.forEach(s => {{ s.totalScore = s.scores.convo + s.scores.gov + s.scores.impact; }});
let currentFilter = 'all', currentSort = 'score';

// --- Read/Unread tracking via localStorage ---
const STORAGE_KEY = 'ti-news-read';
function getReadSet() {{ try {{ return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')); }} catch(e) {{ return new Set(); }} }}
function saveReadSet(s) {{ localStorage.setItem(STORAGE_KEY, JSON.stringify([...s])); }}
let readSet = getReadSet();
// Clean old entries not in current stories (keep storage small)
const currentUrls = new Set(stories.map(s => s.sourceUrl));
readSet = new Set([...readSet].filter(u => currentUrls.has(u)));
saveReadSet(readSet);

function isRead(s) {{ return readSet.has(s.sourceUrl); }}
function markRead(id) {{
  const s = stories.find(x => x.id === id); if (!s) return;
  readSet.add(s.sourceUrl);
  saveReadSet(readSet);
  renderStories();
  updateNewCount();
}}
function markAllRead() {{
  stories.forEach(s => readSet.add(s.sourceUrl));
  saveReadSet(readSet);
  renderStories();
  updateNewCount();
  showToast('All stories marked as read');
}}
function getNewCount() {{ return stories.filter(s => !isRead(s)).length; }}
function updateNewCount() {{
  const n = getNewCount();
  const badge = document.getElementById('newCount');
  if (badge) badge.textContent = n;
  const nb = document.getElementById('newFilterCount');
  if (nb) nb.textContent = n;
  // Hide mark-all if none new
  const mab = document.getElementById('markAllBtn');
  if (mab) mab.style.display = n > 0 ? '' : 'none';
}}

function getScoreClass(t) {{ return t >= 12 ? 'score-high' : t >= 8 ? 'score-mid' : 'score-low'; }}
function sortStories(list, k) {{
  return [...list].sort((a, b) => {{
    if (k === 'score') return b.totalScore - a.totalScore;
    if (k === 'convo') return b.scores.convo - a.scores.convo || b.totalScore - a.totalScore;
    if (k === 'gov') return b.scores.gov - a.scores.gov || b.totalScore - a.totalScore;
    if (k === 'impact') return b.scores.impact - a.scores.impact || b.totalScore - a.totalScore;
    if (k === 'category') return a.category.localeCompare(b.category) || b.totalScore - a.totalScore;
    return 0;
  }});
}}
function renderDots(v) {{ return Array.from({{length: 5}}, (_, i) => '<span class="score-dot ' + (i < v ? 'filled' : '') + '"></span>').join(''); }}
function renderStories() {{
  const c = document.getElementById('stories');
  let f = currentFilter === 'new' ? stories.filter(s => !isRead(s)) :
          currentFilter === 'all' ? stories : stories.filter(s => s.category === currentFilter);
  f = sortStories(f, currentSort);
  c.innerHTML = f.map(s => {{
    const sc = getScoreClass(s.totalScore), isTop = s.totalScore >= 12, read = isRead(s);
    const newBadge = !read ? '<span class="new-badge">New</span>' : '';
    const readClass = read ? ' read' : '';
    const readIcon = read ?
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Read' :
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg> Mark read';
    return '<div class="story-card' + readClass + (isTop && !read ? ' top-pick' : '') + '">' +
      (isTop && !read ? '<div class="top-pick-label">Top Pick for the Blog</div>' : '') +
      '<div class="story-top"><div class="story-top-left"><span class="story-tag ' + s.tagClass + '">' + s.tag + '</span>' + newBadge + '</div><div class="score-badge ' + sc + '">' + s.totalScore + '/15</div></div>' +
      '<div class="score-breakdown"><div class="score-item">Debate <div class="score-dots">' + renderDots(s.scores.convo) + '</div></div><div class="score-item">Gov <div class="score-dots">' + renderDots(s.scores.gov) + '</div></div><div class="score-item">Impact <div class="score-dots">' + renderDots(s.scores.impact) + '</div></div></div>' +
      '<div class="story-title">' + s.title + '</div><div class="story-summary">' + s.summary + '</div>' +
      '<button class="expand-toggle" onclick="toggleDetails(this,' + s.id + ')">Show details & blog angle</button>' +
      '<div class="details-expanded" id="details-' + s.id + '"><ul class="key-points">' + s.keyPoints.map(p => '<li>' + p + '</li>').join('') + '</ul>' +
      '<div class="blog-angle"><div class="blog-angle-label">Blog Angle</div><div class="blog-angle-text">' + s.blogAngle + '</div></div></div>' +
      '<div class="story-source">Source: <a href="' + s.sourceUrl + '" target="_blank" rel="noopener">' + s.source + '</a></div>' +
      '<div class="action-row">' +
      '<button class="action-btn read-btn' + (read ? ' is-read' : '') + '" onclick="markRead(' + s.id + ')">' + readIcon + '</button>' +
      '<button class="action-btn" onclick="saveToNotes(' + s.id + ',this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Save to Notes</button>' +
      '<button class="action-btn share-btn" onclick="shareStory(' + s.id + ')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg> Share</button></div></div>';
  }}).join('');
}}
function toggleDetails(btn, id) {{ const d = document.getElementById('details-' + id); const o = d.classList.toggle('open'); btn.textContent = o ? 'Hide details' : 'Show details & blog angle'; }}
document.getElementById('filters').addEventListener('click', function(e) {{ if (!e.target.classList.contains('filter-btn')) return; this.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active')); e.target.classList.add('active'); currentFilter = e.target.dataset.cat; renderStories(); }});
document.querySelector('.sort-row').addEventListener('click', function(e) {{ if (!e.target.classList.contains('sort-btn')) return; this.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active')); e.target.classList.add('active'); currentSort = e.target.dataset.sort; renderStories(); }});
function showToast(m) {{ const t = document.getElementById('toast'); t.textContent = m; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3000); }}
async function saveToNotes(id, btn) {{
  const s = stories.find(x => x.id === id); if (!s) return;
  markRead(id); // auto-mark as read when saving
  const t = [s.title,'','Score: '+s.totalScore+'/15 (Debate: '+s.scores.convo+' | Gov: '+s.scores.gov+' | Impact: '+s.scores.impact+')','','Category: '+s.tag,'',s.summary,'','KEY POINTS:',...s.keyPoints.map(p=>'\\u2022 '+p),'','BLOG ANGLE:',s.blogAngle,'','Source: '+s.sourceUrl].join('\\n');
  if (navigator.share) {{ try {{ await navigator.share({{title:'TI: '+s.title,text:t}}); btn.classList.add('saved'); btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Shared'; return; }} catch(e) {{ if(e.name==='AbortError') return; }} }}
  if (window.cowork && window.cowork.callMcpTool) {{
    btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><circle cx="12" cy="12" r="10" stroke-dasharray="30 70"/></svg> Saving...'; btn.disabled=true;
    try {{
      const nb='<h1>'+s.title+'</h1><p><b>Score:</b> '+s.totalScore+'/15</p><p><b>Category:</b> '+s.tag+'</p><p>'+s.summary+'</p><h2>Key Points</h2><ul>'+s.keyPoints.map(p=>'<li>'+p+'</li>').join('')+'</ul><h2>Blog Angle</h2><p>'+s.blogAngle+'</p><p><b>Source:</b> <a href="'+s.sourceUrl+'">'+s.source+'</a></p>';
      const esc=nb.replace(/\\\\/g,'\\\\\\\\').replace(/"/g,'\\\\"').replace(/'/g,"'\\\\''");
      const et=s.title.replace(/\\\\/g,'\\\\\\\\').replace(/"/g,'\\\\"').replace(/'/g,"'\\\\''");
      await window.cowork.callMcpTool('mcp__Desktop_Commander__start_process',{{command:"osascript -e 'tell application \\"Notes\\"\\nset targetFolder to folder \\"News Ideas\\"\\nmake new note at targetFolder with properties {{name:\\""+et+"\\", body:\\""+esc+"\\"}}\\nend tell'",timeout_ms:10000}});
      btn.classList.add('saved'); btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Saved'; showToast('Saved to Apple Notes!'); return;
    }} catch(e) {{ btn.disabled=false; console.error(e); }}
  }}
  try {{ await navigator.clipboard.writeText(t); btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Copied!'; showToast('Copied \\u2014 paste into Notes'); setTimeout(()=>{{btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Save to Notes';}},3000); }} catch(e) {{ showToast('Could not copy'); }}
}}
async function shareStory(id) {{
  const s = stories.find(x => x.id === id); if (!s) return;
  markRead(id); // auto-mark as read when sharing
  const t = s.title+' ('+s.totalScore+'/15)\\n\\n'+s.summary+'\\n\\nBlog angle: '+s.blogAngle+'\\n\\n'+s.sourceUrl;
  if (navigator.share) {{ try {{ await navigator.share({{title:s.title,text:t}}); }} catch(e) {{}} }} else {{ try {{ await navigator.clipboard.writeText(t); showToast('Copied!'); }} catch(e) {{ showToast('Could not copy'); }} }}
}}
renderStories();
updateNewCount();
</script>
</body>
</html>'''

    return html


def main():
    print("=== Transatlantic Intelligence News Briefing Generator ===")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Step 1: Fetch news
    articles = fetch_rss_articles()
    if len(articles) < 5:
        print("Warning: Very few articles found. RSS feeds may be down.")

    # Step 2: Score and curate with Claude
    stories = score_and_curate_with_claude(articles)

    # Step 3: Generate HTML
    html = generate_html(stories)

    # Step 4: Write to index.html
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated index.html ({len(html)} bytes) with {len(stories)} stories")
    print("Done!")


if __name__ == "__main__":
    main()
