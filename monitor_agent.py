#!/usr/bin/env python3
"""
US-Iran War Monitor Agent
Searches the web for the latest news and refreshes the war game theory monitor.

Usage:
  python monitor_agent.py          # refresh once, then every 30 minutes
  python monitor_agent.py 60       # refresh every 60 minutes
  python monitor_agent.py --once   # run once and exit (no browser)

Requirements:
  pip install anthropic
  Set environment variable: ANTHROPIC_API_KEY=your-key-here
"""

import anthropic
import json
import re
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# ── File paths ────────────────────────────────────────────────────────────────
SOURCE_HTML = Path("us_iran_war_game_theory_monitor_day34.html")
OUTPUT_HTML = Path("us_iran_monitor_live.html")

# ── Model & pricing (edit here if Anthropic changes rates) ────────────────────
MODEL         = "claude-haiku-4-5-20251001"  # ~6× cheaper than Opus
PRICE_INPUT   = 0.80   # USD per 1M input tokens
PRICE_CACHE_W = 1.00   # USD per 1M cache-write tokens
PRICE_CACHE_R = 0.08   # USD per 1M cache-read tokens (90% cheaper than normal)
PRICE_OUTPUT  = 4.00   # USD per 1M output tokens
BUDGET_LIMIT  = 1.80   # USD — hard abort to protect credits; target is <$1/run


# ── Step 1: Fetch latest news & analysis via Claude + web search ──────────────

def fetch_latest(client: anthropic.Anthropic) -> dict | None:
    """
    Ask Claude to search the web for latest US-Iran news and return
    structured JSON with updated probabilities and headlines.

    Cost controls:
      - Uses Haiku (6× cheaper than Opus)
      - Prompt caching on static instructions (90% cheaper on continuation passes)
      - Hard budget cap: aborts if BUDGET_LIMIT is reached mid-run
      - Max 3 loop passes (was 5)
      - Max 2000 output tokens (was 4000)
    """
    today    = datetime.now().strftime("%B %d, %Y")
    time_now = datetime.now().strftime("%H:%M UTC")

    print(f"  🔍 Searching for latest US-Iran developments...")

    # Static instructions — marked for caching so continuation passes cost 90% less
    static_prompt = f"""Today is {today} at {time_now}.

Search for the most recent US-Iran war news from the last 24 hours.
Run 3 targeted searches for balanced multi-perspective coverage:
  1. Wire services: "Iran US war {today}" — reuters.com, apnews.com, bbc.com, aljazeera.com
  2. Regional media: "Iran war" — nournews.ir or irna.ir (Iranian view) + palestinechronicle.com or middleeasteye.net (Arab/Palestinian)
  3. Israeli + financial: "Iran attack" — timesofisrael.com or haaretz.com + oil/sanctions on bloomberg.com or cnbc.com

Read actual articles, not just headlines. Note any discrepancies between sources. 3 searches is enough — do not do more.

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

  "sources_count": <integer>,
  "sources_breakdown": {{
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
- Base all estimates on the combined picture from all 3 search rounds"""

    # cache_control marks this as cacheable — continuation passes pay 90% less
    messages = [{
        "role": "user",
        "content": [{"type": "text", "text": static_prompt,
                     "cache_control": {"type": "ephemeral"}}]
    }]

    total_input_tokens  = 0
    total_output_tokens = 0
    total_cache_write   = 0
    total_cache_read    = 0
    container_id        = None

    for iteration in range(3):   # max 3 passes — was 5
        call_kwargs = dict(
            model=MODEL,
            max_tokens=2000,     # was 4000 — output JSON needs ~1200 tokens max
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "allowed_callers": ["direct"]}],
            messages=messages,
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        if container_id:
            call_kwargs["container_id"] = container_id

        response = client.messages.create(**call_kwargs)

        # Accumulate all token types
        total_input_tokens  += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_write   += getattr(response.usage, "cache_creation_input_tokens", 0)
        total_cache_read    += getattr(response.usage, "cache_read_input_tokens", 0)

        # ── Budget guard — check after every API call ─────────────────────────
        running_cost = (
            total_input_tokens  / 1_000_000 * PRICE_INPUT  +
            total_cache_write   / 1_000_000 * PRICE_CACHE_W +
            total_cache_read    / 1_000_000 * PRICE_CACHE_R +
            total_output_tokens / 1_000_000 * PRICE_OUTPUT
        )
        if running_cost > BUDGET_LIMIT:
            print(f"  🛑 Budget cap ${BUDGET_LIMIT:.2f} reached "
                  f"(${running_cost:.2f} spent so far) — stopping to protect credits")
            return None

        if response.stop_reason == "end_turn":
            # Print full token & cost breakdown
            cost_input   = total_input_tokens  / 1_000_000 * PRICE_INPUT
            cost_cache_w = total_cache_write   / 1_000_000 * PRICE_CACHE_W
            cost_cache_r = total_cache_read    / 1_000_000 * PRICE_CACHE_R
            cost_output  = total_output_tokens / 1_000_000 * PRICE_OUTPUT
            cost_total   = cost_input + cost_cache_w + cost_cache_r + cost_output

            print(f"  🔢 Tokens  : {total_input_tokens:,} input"
                  + (f"  |  {total_cache_write:,} cache-write"  if total_cache_write else "")
                  + (f"  |  {total_cache_read:,} cache-read"    if total_cache_read  else "")
                  + f"  |  {total_output_tokens:,} output")
            print(f"  💰 Cost    : ${cost_total:.4f}  "
                  f"(model: {MODEL.split('-')[2]})")

            # Extract JSON from the final text response
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
            print("  ⚠️  Response received but could not parse JSON")
            return None

        elif response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            raw = getattr(response, "container", None)
            if raw is not None:
                container_id = getattr(raw, "id", raw)
            print(f"  ⏳ Continuing search (pass {iteration + 2}/3)...")

        else:
            messages.append({"role": "assistant", "content": response.content})

    print("  ⚠️  Reached max iterations without a final response")
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

    # Safely encode data as JSON for embedding in JavaScript
    data_json = json.dumps(data, ensure_ascii=False)

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
        print(f"     └─ 🌐 Western: {breakdown.get('western',0)}  "
              f"🇮🇷 Iranian: {breakdown.get('iranian',0)}  "
              f"🕌 Arab/Palestinian: {breakdown.get('arab_palestinian',0)}  "
              f"🇮🇱 Israeli: {breakdown.get('israeli',0)}  "
              f"💹 Financial: {breakdown.get('financial',0)}")
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

    # Push to GitHub so the live link updates for viewers
    push_to_github(data)

    if open_browser:
        webbrowser.open(OUTPUT_HTML.resolve().as_uri())

    # ── Done banner ───────────────────────────────────────────────────────────
    live_url = "https://lawlai.github.io/iran-monitor/us_iran_monitor_live.html"
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

        subprocess.run(["git", "add", str(OUTPUT_HTML)], cwd=folder, check=True)
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
