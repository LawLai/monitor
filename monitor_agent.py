#!/usr/bin/env python3
"""
US-Iran War Monitor Agent
Searches the web for the latest news and refreshes the war game theory monitor.

Usage:
  python monitor_agent.py          # refresh once, then every 30 minutes
  python monitor_agent.py 60       # refresh every 60 minutes
  python monitor_agent.py --once   # run once and exit (no browser)

Requirements:
  pip install anthropic google-genai
  Set environment variables:
    ANTHROPIC_API_KEY=your-claude-key
    GEMINI_API_KEY=your-gemini-key
"""

import anthropic
import json
import os
import re
import subprocess
import time
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from google import genai

# ── File paths ────────────────────────────────────────────────────────────────
SOURCE_HTML = Path("us_iran_war_game_theory_monitor_day34.html")
OUTPUT_HTML = Path("us_iran_monitor_live.html")

# ── Model & pricing ──────────────────────────────────────────────────────────
# Gemini: web search (cheap)  |  Claude: game theory analysis (quality)
GEMINI_MODEL  = "gemini-2.5-flash"
CLAUDE_MODEL  = "claude-opus-4-6"
PRICE_INPUT   = 5.00    # Claude USD per 1M input tokens
PRICE_OUTPUT  = 25.00   # Claude USD per 1M output tokens
BUDGET_LIMIT  = 1.00    # USD — hard abort (now much lower since search is free via Gemini)


# ── Step 1a: Fetch premium RSS feeds (WSJ, FT, NYT) ─────────────────────────

RSS_FEEDS = [
    ("WSJ World",    "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    ("WSJ Markets",  "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("NYT World",    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("NYT MiddleEast","https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml"),
    ("FT",           "https://www.ft.com/rss/home"),
]

# Must match at least ONE primary keyword to be considered Iran-relevant
IRAN_PRIMARY = ["iran", "tehran", "irgc", "hormuz", "persian gulf", "strait of hormuz"]
# Secondary keywords — article must also match one of these (or a primary)
IRAN_SECONDARY = [
    "ceasefire", "nuclear", "houthi", "hezbollah", "missile", "drone",
    "strike", "sanctions", "escalation", "war", "trump iran",
    "oil price", "brent", "proxy", "axis"
]
RSS_MAX_ARTICLES = 25  # cap to control prompt size (~750 tokens max)

def _parse_rss_date(date_str: str) -> datetime | None:
    """Try common RSS date formats, return UTC datetime or None."""
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",   # RFC 822: "Mon, 02 Apr 2026 14:30:00 +0000"
        "%a, %d %b %Y %H:%M:%S",       # without timezone
        "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 UTC
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
    return None

def fetch_rss() -> str:
    """
    Fetch WSJ, NYT, FT RSS feeds and return a formatted string of
    Iran-relevant headlines from the last 36 hours.
    No API cost — pure HTTP fetch using Python built-ins.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    results = []
    feed_stats = []

    for feed_name, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()

            root = ET.fromstring(raw)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            feed_count = 0
            for item in items:
                # Get title
                title_el = item.find("title")
                title = title_el.text.strip() if title_el is not None and title_el.text else ""

                # Get description/summary
                desc_el = item.find("description") or item.find("summary")
                desc = ""
                if desc_el is not None and desc_el.text:
                    desc = re.sub(r"<[^>]+>", "", desc_el.text).strip()[:200]

                # Get pub date and filter by recency
                date_el = item.find("pubDate") or item.find("published") or item.find("updated")
                pub_date_str = date_el.text.strip() if date_el is not None and date_el.text else ""
                pub_dt = _parse_rss_date(pub_date_str)
                if pub_dt and pub_dt < cutoff:
                    continue  # skip articles older than 36 hours

                # Filter: must match at least one PRIMARY Iran keyword
                combined = (title + " " + desc).lower()
                has_primary = any(kw in combined for kw in IRAN_PRIMARY)
                if not has_primary:
                    continue

                results.append(f"[{feed_name}] {title} — {desc}")
                feed_count += 1

            feed_stats.append(f"{feed_name}: {feed_count}")

        except Exception as e:
            feed_stats.append(f"{feed_name}: failed ({type(e).__name__})")

    if not results:
        return ""

    # Cap at RSS_MAX_ARTICLES to control prompt token usage
    if len(results) > RSS_MAX_ARTICLES:
        results = results[:RSS_MAX_ARTICLES]

    header = (f"=== PREMIUM RSS FEEDS ({len(results)} Iran-relevant articles) ===\n"
              f"Sources: {' | '.join(feed_stats)}\n\n")
    return header + "\n".join(f"• {r}" for r in results)


# ── Step 1b: Search news via Gemini (cheap) ──────────────────────────────────

def search_news_gemini() -> str:
    """
    Use Gemini + Google Search grounding to gather latest US-Iran news.
    Cost: ~$0.0002 per call (practically free).
    Returns plain text news summary.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("  ⚠  GEMINI_API_KEY not set — skipping Gemini search")
        return ""

    today = datetime.now().strftime("%B %d, %Y")

    try:
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"""Today is {today}. Search for the latest US-Iran war news from the last 24 hours.

Cover ALL of these perspectives:
1. Military developments (strikes, casualties, deployments, weapons)
2. Diplomatic moves (ceasefire talks, negotiations, UN activity)
3. Iranian state perspective (what Tehran/IRGC is saying and doing)
4. Israeli actions and statements
5. Arab/Palestinian regional perspective
6. Oil price and economic/sanctions impact
7. Trump administration statements and signals

For each development, note which source reported it.
Include any conflicting accounts between Western and Iranian/Arab media.
Be specific: cite names, numbers, locations, dates.""",
            config=genai.types.GenerateContentConfig(
                tools=[genai.types.Tool(google_search=genai.types.GoogleSearch())],
            ),
        )

        result = response.text or ""

        # Print Gemini cost
        if response.usage_metadata:
            inp = response.usage_metadata.prompt_token_count or 0
            out = response.usage_metadata.candidates_token_count or 0
            gcost = inp / 1_000_000 * 0.10 + out / 1_000_000 * 0.40
            print(f"  ✓ Gemini: {out:,} tokens, ${gcost:.6f}")

        return result

    except Exception as e:
        print(f"  ⚠  Gemini search failed: {e}")
        return ""


# ── Step 1c: Analyze news via Claude (quality) ───────────────────────────────

def fetch_latest(client: anthropic.Anthropic) -> dict | None:
    """
    Two-phase approach:
      Phase 1 (free/cheap): RSS feeds + Gemini Google Search gather news
      Phase 2 (Claude): Analyze the gathered news, produce game theory JSON

    Claude does NOT use web_search — all news is pre-gathered.
    This cuts Claude cost from ~$1.50 to ~$0.10-0.20 per run.
    """
    today    = datetime.now().strftime("%B %d, %Y")
    time_now = datetime.now().strftime("%H:%M UTC")

    # Phase 1a: RSS feeds (free)
    print(f"  📰 Fetching premium RSS feeds (WSJ / NYT / FT)...")
    rss_content = fetch_rss()
    if rss_content:
        line_count = rss_content.count("\n•")
        print(f"  ✓ RSS: {line_count} Iran-relevant articles retrieved")
    else:
        print(f"  ⚠  RSS: no articles retrieved (feeds may be unavailable)")

    # Phase 1b: Gemini web search (practically free)
    print(f"  🔍 Searching via Gemini + Google Search...")
    gemini_news = search_news_gemini()
    if gemini_news:
        print(f"  ✓ Gemini: {len(gemini_news):,} chars of news gathered")
    else:
        print(f"  ⚠  Gemini: no results — Claude will work with RSS only")

    # Build the combined news briefing for Claude
    news_briefing = ""
    if rss_content:
        news_briefing += rss_content + "\n\n"
    if gemini_news:
        news_briefing += "=== GOOGLE NEWS SEARCH (via Gemini) ===\n" + gemini_news + "\n\n"

    if not news_briefing.strip():
        print("  ✗ No news gathered from any source — cannot update")
        return None

    # Phase 2: Claude analysis (no web search tool — just analysis)
    print(f"  🧠 Analyzing via Claude ({CLAUDE_MODEL})...")

    analysis_prompt = f"""Today is {today} at {time_now}.

Below is a news briefing about the US-Iran war gathered from multiple sources (RSS feeds from WSJ/NYT/FT + Google News search covering Western, Iranian, Arab, Israeli, and financial media).

{news_briefing}

Based on ALL the news above, produce a game theory analysis.
Return ONLY a valid JSON object (no markdown, no explanation):
{{
  "ceasefire_pct": <integer 0-100>,
  "ceasefire_delta": "<like +2 or -3>",
  "ceasefire_reasoning": "2-3 sentences citing specific headlines and why the number moved",

  "escalation": <integer 0-100>,
  "escalation_delta": "<like +5 or -2>",
  "escalation_reasoning": "2-3 sentences citing specific headlines and why the number moved",

  "ground_war_pct": <integer 0-100>,
  "ground_war_delta": "<like +1 or -4>",
  "ground_war_reasoning": "2-3 sentences citing specific headlines and why the number moved",

  "ticker_items": ["🔴 military event", "🟡 political statement", "🟢 diplomatic move"],
  "summary": "2-3 sentence intelligence summary",

  "sources_count": <integer — total articles/sources in the briefing above>,
  "sources_breakdown": {{
    "premium_rss": <integer — WSJ/NYT/FT RSS articles>,
    "western": <integer>, "iranian": <integer>,
    "arab_palestinian": <integer>, "israeli": <integer>, "financial": <integer>
  }},
  "sources_quality": "good" | "limited" | "poor",
  "sources_quality_reason": "one sentence",
  "perspective_gaps": "one sentence — which perspective had thin coverage today",
  "key_discrepancy": "one sentence — biggest factual conflict between sources, or 'none significant'",

  "confidence": {{
    "ceasefire_low": <int>, "ceasefire_high": <int>,
    "escalation_low": <int>, "escalation_high": <int>,
    "ground_war_low": <int>, "ground_war_high": <int>
  }},

  "tree": [
    {{"index": 0, "probability": <int>, "note": "short phrase — Trump unilateral exit"}},
    {{"index": 1, "probability": <int>, "note": "short phrase — War continues Apr-Jun"}},
    {{"index": 2, "probability": <int>, "note": "short phrase — Negotiated ceasefire"}},
    {{"index": 3, "probability": <int>, "note": "short phrase — Regime collapse"}},
    {{"index": 4, "probability": <int>, "note": "short phrase — Nuclear/Black Swan"}}
  ],

  "actor_decisions": {{
    "us":   {{"Withdraw": <int>, "Negotiate": <int>, "Escalate": <int>}},
    "iran": {{"Escalate": <int>, "Attrit": <int>, "Negotiate": <int>}}
  }},

  "timeline_event": {{
    "date": "<like Apr 5>", "day": <int>,
    "cf": <int>, "es": <int>, "gw": <int>, "rg": 14,
    "event": "one-line summary of today's most important development",
    "hot": <true|false>
  }},

  "matrix": {{
    "vals": [
      [[<US>,<Iran>],[<US>,<Iran>],[<US>,<Iran>]],
      [[<US>,<Iran>],[<US>,<Iran>],[<US>,<Iran>]],
      [[<US>,<Iran>],[<US>,<Iran>],[<US>,<Iran>]]
    ],
    "nash": [<row 0-2>, <col 0-2>],
    "shifting": [<row 0-2>, <col 0-2>],
    "nash_reasoning": "1-2 sentences on why this is the stable cell",
    "cell_changes": [{{"cell": "row,col", "reason": "what news changed this cell"}}]
  }}
}}

Rules:
- ticker: 🔴=military  🟡=political  🟢=diplomatic — include 5-8 items
- tree: all 5 probabilities must sum to 100
- actor_decisions: each side's 3 values must sum to 100
- matrix rows: 0=US escalate, 1=US air+Hormuz, 2=US negotiate/exit
- matrix cols: 0=Iran full escalate, 1=Iran attrit+block, 2=Iran accepts deal
- payoff scale: -10 to +10 for each side in each cell
- Nash cell = neither side gains by deviating unilaterally
- Base all estimates on the combined news briefing above"""

    messages = [{"role": "user", "content": analysis_prompt}]

    # Single Claude call — no web search tool, no agentic loop needed
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=messages,
        )
    except (anthropic.InternalServerError, anthropic.RateLimitError) as e:
        print(f"  ⚠️  API error: {e} — retrying in 10 seconds...")
        time.sleep(10)
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=messages,
            )
        except Exception as e2:
            print(f"  ✗ Retry failed: {e2}")
            return None

    # Token tracking & cost
    total_input  = response.usage.input_tokens
    total_output = response.usage.output_tokens
    cost_input   = total_input  / 1_000_000 * PRICE_INPUT
    cost_output  = total_output / 1_000_000 * PRICE_OUTPUT
    cost_total   = cost_input + cost_output

    print(f"  🔢 Tokens  : {total_input:,} input  |  {total_output:,} output")
    print(f"  💰 Claude  : ${cost_total:.4f}  ({CLAUDE_MODEL})")

    if cost_total > BUDGET_LIMIT:
        print(f"  🛑 Budget cap ${BUDGET_LIMIT:.2f} exceeded (${cost_total:.2f}) — result discarded")
        return None

    # Extract JSON from the response
    for block in response.content:
        if block.type == "text" and block.text.strip():
            text = block.text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$',          '', text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

    # Save raw response for debugging
    debug_file = Path("debug_last_response.txt")
    raw_texts = [b.text for b in response.content if b.type == "text"]
    debug_file.write_text("\n---\n".join(raw_texts), encoding="utf-8")
    print(f"  ⚠️  Response received but could not parse JSON")
    print(f"     Raw response saved to {debug_file} for debugging")
    return None


# ── Step 2: Inject updated data into the HTML via a script tag ────────────────

def build_updated_html(data: dict) -> str:
    """
    Read the original HTML and inject a <script> that updates the page
    with fresh stats, ticker items, and a timestamp badge.
    This approach is robust — no fragile regex surgery on the HTML.
    """
    html = SOURCE_HTML.read_text(encoding="utf-8")
    now = datetime.now()

    # Only embed fields the JavaScript actually uses — strip analysis-only fields
    frontend_keys = [
        "ceasefire_pct", "ceasefire_delta",
        "escalation", "escalation_delta",
        "ground_war_pct", "ground_war_delta",
        "ticker_items", "confidence",
        "tree", "actor_decisions", "timeline_event", "matrix",
    ]
    frontend_data = {k: data[k] for k in frontend_keys if k in data}
    data_json = json.dumps(frontend_data, ensure_ascii=False)

    update_script = f"""
<!-- ═══ Auto-injected by US-Iran Monitor Agent · {now.isoformat()} ═══ -->
<script>
(function() {{
  var data = {data_json};

  // ── Update header stats ──────────────────────────────────────────────────
  var statDivs = document.querySelectorAll('.stat');
  statDivs.forEach(function(stat) {{
    var label = stat.querySelector('.stat-label');
    if (!label) return;
    var val   = stat.querySelector('.stat-val');
    var delta = stat.querySelector('.stat-delta');
    var lbl   = label.textContent.trim();

    if (lbl === 'CEASEFIRE' && val) {{
      val.textContent   = data.ceasefire_pct + '%';
      if (delta) delta.textContent = data.ceasefire_delta;
    }}
    if (lbl === 'ESCALATION' && val) {{
      val.textContent   = data.escalation;
      if (delta) delta.textContent = data.escalation_delta;
    }}
    if (lbl === 'GROUND WAR' && val) {{
      val.textContent   = data.ground_war_pct + '%';
      if (delta) delta.textContent = data.ground_war_delta;
    }}
  }});

  // ── Update news ticker ───────────────────────────────────────────────────
  var ticker = document.querySelector('.ticker-inner');
  if (ticker && data.ticker_items && data.ticker_items.length) {{
    ticker.innerHTML = data.ticker_items.map(function(item) {{
      return '<span class="ticker-item">' + item +
             ' <span class="ticker-sep">///</span></span>';
    }}).join('');
  }}

  // ── Update subtitle bar ──────────────────────────────────────────────────
  var sub = document.querySelector('.brand-sub');
  if (sub) {{
    sub.textContent = 'LIVE — {now.strftime("%b %d, %Y").upper()} '
      + '{now.strftime("%H:%M")} UTC — AUTO-REFRESHED BY MONITOR AGENT';
  }}

  // ── Update payoff matrix ─────────────────────────────────────────────────
  if (data.matrix) {{
    var m = data.matrix;
    if (m.vals)     MATRIX.vals     = m.vals;
    if (m.nash)     MATRIX.nash     = m.nash;
    if (m.shifting) MATRIX.shifting = m.shifting;

    // Re-render matrix tab if it is currently visible
    var matrixPane = document.getElementById('tab-matrix');
    if (matrixPane && matrixPane.style.display !== 'none') {{
      matrixPane.innerHTML = renderMatrix();
    }}

    // Inject Nash reasoning box below the matrix insight box
    if (m.nash_reasoning) {{
      var existingBox = document.getElementById('agent-nash-box');
      if (existingBox) existingBox.remove();
      var nashBox = document.createElement('div');
      nashBox.id = 'agent-nash-box';
      nashBox.style.cssText = 'margin:10px 20px;padding:12px;background:rgba(0,255,136,.03);border:1px solid rgba(0,255,136,.15);border-radius:7px;font-family:monospace';
      nashBox.innerHTML =
        '<div style="font-size:.46rem;color:#00ff88;font-weight:700;letter-spacing:.1em;margin-bottom:6px">⚡ AGENT NASH ASSESSMENT — {now.strftime("%H:%M")} UTC</div>' +
        '<div style="font-size:.5rem;color:rgba(255,255,255,.55);line-height:1.7">' + m.nash_reasoning + '</div>' +
        (m.cell_changes && m.cell_changes.length ?
          '<div style="margin-top:8px;font-size:.44rem;color:rgba(255,255,255,.3)">' +
          m.cell_changes.map(function(c) {{
            return '• Cell [' + c.cell + ']: ' + c.reason;
          }}).join('<br>') + '</div>' : '');
      var matrixTab = document.getElementById('tab-matrix');
      if (matrixTab) matrixTab.appendChild(nashBox);
    }}
  }}

  // ── 1. Confidence ranges on header stats ─────────────────────────────────
  if (data.confidence) {{
    var c = data.confidence;
    var statDivs2 = document.querySelectorAll('.stat');
    statDivs2.forEach(function(stat) {{
      var label = stat.querySelector('.stat-label');
      if (!label) return;
      var lbl = label.textContent.trim();
      var rangeEl = stat.querySelector('.agent-range');
      if (!rangeEl) {{
        rangeEl = document.createElement('div');
        rangeEl.className = 'agent-range';
        rangeEl.style.cssText = 'font-size:.3rem;color:rgba(255,255,255,.3);margin-top:2px;letter-spacing:.04em';
        stat.appendChild(rangeEl);
      }}
      if (lbl === 'CEASEFIRE')  rangeEl.textContent = 'range ' + c.ceasefire_low  + '–' + c.ceasefire_high  + '%';
      if (lbl === 'ESCALATION') rangeEl.textContent = 'range ' + c.escalation_low + '–' + c.escalation_high;
      if (lbl === 'GROUND WAR') rangeEl.textContent = 'range ' + c.ground_war_low + '–' + c.ground_war_high + '%';
    }});
  }}

  // ── 2. Probability tree update ────────────────────────────────────────────
  if (data.tree && data.tree.length) {{
    data.tree.forEach(function(upd) {{
      if (TREE[upd.index] !== undefined) {{
        TREE[upd.index].p    = upd.probability;
        TREE[upd.index].note = upd.note;
      }}
    }});
    // Re-render tree tab if visible
    if (currentTab === 'tree') render();
  }}

  // ── 3. Actor decision weights update ─────────────────────────────────────
  if (data.actor_decisions) {{
    var ad = data.actor_decisions;
    // US is ACTORS[0], Iran is ACTORS[1]
    if (ad.us   && ACTORS[0]) ACTORS[0].dec = ad.us;
    if (ad.iran && ACTORS[1]) ACTORS[1].dec = ad.iran;
    // Re-render actors tab if visible
    if (currentTab === 'actors') render();
  }}

  // ── 4. Timeline — append today's new event ───────────────────────────────
  if (data.timeline_event) {{
    var te = data.timeline_event;
    // Avoid duplicate entries for the same date
    var alreadyAdded = TL.some(function(e) {{ return e.d === te.date && e.ev === te.event; }});
    if (!alreadyAdded) {{
      TL.push({{
        d: te.date, day: te.day,
        cf: te.cf,  es: te.es, gw: te.gw, rg: te.rg,
        ev: te.event, hot: te.hot
      }});
    }}
    // Re-render timeline tab if visible
    if (currentTab === 'timeline') render();
  }}

  // ── Show update toast ────────────────────────────────────────────────────
  var toast = document.createElement('div');
  toast.style.cssText = [
    'position:fixed', 'bottom:20px', 'right:20px',
    'background:rgba(0,0,0,.88)', 'border:1px solid rgba(0,255,136,.4)',
    'border-radius:8px', 'padding:10px 16px',
    'font-size:.5rem', 'color:#00ff88',
    'z-index:9999', 'font-family:monospace', 'letter-spacing:.08em',
    'line-height:1.6'
  ].join(';');
  toast.innerHTML =
    '✓ LIVE UPDATE &nbsp;{now.strftime("%H:%M")} UTC<br>' +
    '<span style="color:rgba(255,255,255,.4);font-size:.4rem">' +
    'Monitor agent refreshed</span>';
  document.body.appendChild(toast);
  setTimeout(function() {{
    toast.style.transition = 'opacity .5s';
    toast.style.opacity = '0';
    setTimeout(function() {{ toast.remove(); }}, 500);
  }}, 7000);

}})();
</script>
<!-- ═══ End monitor agent injection ═══ -->
"""

    # ── Replace hardcoded US-actor alert banner with latest timeline_event ──
    import re as _re
    te = data.get("timeline_event", {})
    if te and te.get("event"):
        te_label = te.get("date", now.strftime("%b %d")).upper()
        te_text  = te.get("event", "")
        # 1. Replace the tag label (e.g. "TONIGHT 9PM ET" → "APR 8")
        html = _re.sub(
            r'(<span class="alert-tag" style="background:rgba\(90,200,250,\.15\);color:#5ac8fa">)'
            r'[^<]+'
            r'(</span>)',
            rf'\g<1>{te_label}\2',
            html
        )
        # 2. Replace the alert-text span immediately following that tag
        html = _re.sub(
            r'(rgba\(90,200,250,\.15\);color:#5ac8fa">[^<]*</span>\s*\n\s*'
            r'<span class="alert-text" style="color:rgba\(255,255,255,\.65\)">)'
            r'[^<]+'
            r'(</span>)',
            rf'\g<1>{te_text}\2',
            html
        )

    # Inject just before </body>
    if "</body>" in html:
        html = html.replace("</body>", update_script + "\n</body>")
    else:
        html += update_script

    return html


# ── Step 3: Run one update cycle ──────────────────────────────────────────────

def run_update(client: anthropic.Anthropic, open_browser: bool = False) -> bool:
    """Fetch latest news, update HTML, optionally open browser. Returns True on success."""

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running update...")

    data = fetch_latest(client)
    if not data:
        print("  ✗ Failed to fetch latest data — will retry next cycle")
        return False

    # Print summary to console
    print(f"  📊 Ceasefire  : {data.get('ceasefire_pct', '?')}%  ({data.get('ceasefire_delta', '')})")
    r = data.get('ceasefire_reasoning', '')
    if r: print(f"     └─ {r}")

    print(f"  📊 Escalation : {data.get('escalation', '?')}   ({data.get('escalation_delta', '')})")
    r = data.get('escalation_reasoning', '')
    if r: print(f"     └─ {r}")

    print(f"  📊 Ground War : {data.get('ground_war_pct', '?')}%  ({data.get('ground_war_delta', '')})")
    r = data.get('ground_war_reasoning', '')
    if r: print(f"     └─ {r}")

    summary = data.get("summary", "")
    if summary:
        print(f"  📋 {summary}")

    # Confidence ranges
    conf = data.get("confidence", {})
    if conf:
        print(f"\n  📏 Confidence ranges:")
        print(f"     Ceasefire  : {conf.get('ceasefire_low','?')}% – {conf.get('ceasefire_high','?')}%")
        print(f"     Escalation : {conf.get('escalation_low','?')} – {conf.get('escalation_high','?')}")
        print(f"     Ground War : {conf.get('ground_war_low','?')}% – {conf.get('ground_war_high','?')}%")

    # Probability tree
    tree = data.get("tree", [])
    labels = ["Trump exit","War continues","Ceasefire","Regime collapse","Black Swan"]
    if tree:
        print(f"\n  🌳 Probability tree:")
        for node in tree:
            idx = node.get("index", -1)
            label = labels[idx] if 0 <= idx < len(labels) else f"node {idx}"
            print(f"     {label:<20}: {node.get('probability','?')}%  — {node.get('note','')[:70]}")

    # Actor decisions
    actor_dec = data.get("actor_decisions", {})
    if actor_dec:
        print(f"\n  🎭 Actor decisions:")
        us = actor_dec.get("us", {})
        ir = actor_dec.get("iran", {})
        if us:
            print(f"     US   → Withdraw {us.get('Withdraw','?')}% / Negotiate {us.get('Negotiate','?')}% / Escalate {us.get('Escalate','?')}%")
        if ir:
            print(f"     Iran → Escalate {ir.get('Escalate','?')}% / Attrit {ir.get('Attrit','?')}% / Negotiate {ir.get('Negotiate','?')}%")

    # Timeline event
    tl = data.get("timeline_event", {})
    if tl:
        hot = "🔥" if tl.get("hot") else "📅"
        print(f"\n  {hot} New timeline entry: [{tl.get('date','?')}] {tl.get('event','')[:80]}")

    # Matrix update report
    matrix = data.get("matrix", {})
    if matrix:
        nash = matrix.get("nash", [])
        row_names = ["Escalate", "Continue Air", "Negotiate"]
        col_names = ["Iran Escalates", "Iran Attrits", "Iran Deals"]
        if nash:
            print(f"\n  ♟️  Nash Equilibrium → [{row_names[nash[0]]}] vs [{col_names[nash[1]]}]")
        reasoning = matrix.get("nash_reasoning", "")
        if reasoning:
            print(f"     └─ {reasoning}")
        changes = matrix.get("cell_changes", [])
        if changes:
            print(f"  📐 Matrix changes today:")
            for c in changes[:4]:
                print(f"     • Cell {c.get('cell','?')}: {c.get('reason','')[:90]}")

    # Sources report
    count = data.get("sources_count", "?")
    quality = data.get("sources_quality", "?").upper()
    quality_reason = data.get("sources_quality_reason", "")
    breakdown = data.get("sources_breakdown", {})
    quality_icon = {"GOOD": "🟢", "LIMITED": "🟡", "POOR": "🔴"}.get(quality, "⚪")
    print(f"\n  📰 News gathered : {count} articles  {quality_icon} Coverage: {quality}")
    if breakdown:
        rss_count = breakdown.get('premium_rss', 0)
        if rss_count:
            print(f"     └─ WSJ/NYT/FT RSS: {rss_count} premium articles")
        print(f"     └─ Western: {breakdown.get('western',0)}  "
              f"Iranian: {breakdown.get('iranian',0)}  "
              f"Arab/Palestinian: {breakdown.get('arab_palestinian',0)}  "
              f"Israeli: {breakdown.get('israeli',0)}  "
              f"Financial: {breakdown.get('financial',0)}")
    if quality_reason:
        print(f"     └─ {quality_reason}")
    discrepancy = data.get("key_discrepancy", "")
    if discrepancy and discrepancy.lower() != "none significant":
        print(f"  ⚠️  Source conflict : {discrepancy}")
    gap = data.get("perspective_gaps", "")
    if gap:
        print(f"  🔍 Coverage gap   : {gap}")

    # Write updated HTML
    updated_html = build_updated_html(data)
    OUTPUT_HTML.write_text(updated_html, encoding="utf-8")
    print(f"  ✓ Saved → {OUTPUT_HTML}")

    # Write sidecar JSON for generate_index.py
    import re as _re
    _day_match = _re.search(r"day(\d+)", SOURCE_HTML.stem, _re.IGNORECASE)
    _day = int(_day_match.group(1)) if _day_match else "?"
    _now = datetime.now()
    _date_str = f"{_now.strftime('%b')} {_now.day}, {_now.year}"
    status_path = Path(__file__).parent / "iran_status.json"
    status_path.write_text(json.dumps({
        "day": _day,
        "escalation_pct": data.get("escalation", "?"),
        "ceasefire_pct": data.get("ceasefire_pct", "?"),
        "updated": _date_str,
    }, indent=2), encoding="utf-8")

    # Regenerate landing page with fresh Iran stats
    try:
        import subprocess as _sp, sys as _sys
        _sp.run([_sys.executable, str(Path(__file__).parent / "generate_index.py")],
                cwd=str(Path(__file__).parent), check=True)
    except Exception as _e:
        print(f"  [index] Warning: could not regenerate landing page: {_e}")

    # Push to GitHub so the live link updates for viewers
    push_to_github(data)

    if open_browser:
        webbrowser.open(OUTPUT_HTML.resolve().as_uri())

    # ── Done banner ───────────────────────────────────────────────────────────
    live_url = "https://lawlai.github.io/monitor/us_iran_monitor_live.html"
    now_str  = datetime.now().strftime("%H:%M:%S")
    print(f"""
╔══════════════════════════════════════════════════════╗
║  ✅ UPDATE COMPLETE  {now_str}                      ║
║                                                      ║
║  🌐 {live_url[:50]}  ║
╚══════════════════════════════════════════════════════╝""")

    # Play a short beep so you hear it even without watching the screen
    try:
        import winsound
        winsound.Beep(1000, 300)   # frequency=1000Hz, duration=300ms
        winsound.Beep(1200, 200)
    except Exception:
        pass   # non-Windows or no audio — silently skip

    return True


def push_to_github(data: dict):
    """Auto-commit and push the updated HTML to GitHub Pages."""
    try:
        now = datetime.now().strftime("%b %d %H:%M")
        ceasefire = data.get("ceasefire_pct", "?")
        escalation = data.get("escalation", "?")
        msg = f"Live update {now} — Ceasefire {ceasefire}% / Escalation {escalation}"

        folder = Path(__file__).parent

        subprocess.run(["git", "add", str(OUTPUT_HTML), "iran_status.json", "index.html"], cwd=folder, check=True)
        subprocess.run(["git", "commit", "-m", msg],     cwd=folder, check=True)
        subprocess.run(["git", "push"],                  cwd=folder, check=True)

        print(f"  🚀 Published to GitHub Pages")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  GitHub push failed: {e}")
        print(f"     Make sure GitHub Desktop has synced this folder first.")
    except FileNotFoundError:
        print(f"  ⚠️  Git not found — skipping GitHub publish.")
        print(f"     GitHub Desktop installs Git automatically — try restarting.")


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    import sys

    if not SOURCE_HTML.exists():
        print(f"❌ Error: '{SOURCE_HTML}' not found.")
        print(f"   Run this script from: {Path.cwd()}")
        return

    # Build client (reads ANTHROPIC_API_KEY from environment)
    try:
        client = anthropic.Anthropic()
    except Exception as e:
        print(f"❌ Could not create Anthropic client: {e}")
        print("   Make sure ANTHROPIC_API_KEY is set in your environment.")
        return

    args = sys.argv[1:]

    # --once: single run, no browser, exit
    if "--once" in args:
        run_update(client, open_browser=False)
        return

    # Optional positional arg: refresh interval in minutes
    interval = 30
    for arg in args:
        try:
            interval = int(arg)
            break
        except ValueError:
            pass

    print("╔══════════════════════════════════════════╗")
    print("║   US-Iran War Monitor Agent              ║")
    print(f"║   Refresh every {interval:3d} min  ·  Ctrl+C stop  ║")
    print("║   Output → us_iran_monitor_live.html     ║")
    print("╚══════════════════════════════════════════╝")

    # First run — open browser so user can see it
    run_update(client, open_browser=True)

    # Continuous loop
    while True:
        try:
            print(f"\n  ⏰ Next update in {interval} minutes...")
            time.sleep(interval * 60)
            run_update(client, open_browser=False)
        except KeyboardInterrupt:
            print("\n\n  Agent stopped. Goodbye.")
            break
        except Exception as e:
            print(f"  ⚠️  Unexpected error: {e}")
            print("  Retrying in 5 minutes...")
            time.sleep(300)


if __name__ == "__main__":
    main()
