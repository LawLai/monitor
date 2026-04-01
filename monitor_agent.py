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


# ── Step 1: Fetch latest news & analysis via Claude + web search ──────────────

def fetch_latest(client: anthropic.Anthropic) -> dict | None:
    """
    Ask Claude to search the web for latest US-Iran news and return
    structured JSON with updated probabilities and headlines.
    """
    today = datetime.now().strftime("%B %d, %Y")
    time_now = datetime.now().strftime("%H:%M UTC")

    print(f"  🔍 Searching for latest US-Iran developments...")

    messages = [{
        "role": "user",
        "content": f"""Today is {today} at {time_now}.

Search for the most recent news about the US-Iran war, conflict, or tensions from the last 24 hours.

SEARCH STRATEGY — run MULTIPLE searches to get balanced coverage across all perspectives:

ROUND 1 — Western / international wire services:
  Search: "Iran US war" site:reuters.com OR site:apnews.com OR site:bbc.com OR site:aljazeera.com

ROUND 2 — Iranian state media (official Tehran perspective):
  Search: "Iran war ceasefire" site:nournews.ir OR site:irna.ir OR site:presstv.ir OR site:tasnimnews.com
  Also visit: https://nournews.ir/en/Service/AllNews  (scan latest headlines)

ROUND 3 — Palestinian / Arab media (ground-level regional view):
  Search: "Iran Israel US" site:palestinechronicle.com OR site:middleeasteye.net OR site:arabnews.com OR site:thenationalnews.com
  Also check: https://www.palestinechronicle.com for their latest live blog

ROUND 4 — Israeli media (Israeli perspective):
  Search: "Iran attack ceasefire" site:timesofisrael.com OR site:haaretz.com OR site:ynetnews.com

ROUND 5 — Gulf / financial:
  Search: "Iran Hormuz oil war" site:gulfnews.com OR site:zawya.com OR site:bloomberg.com OR site:cnbc.com

For each search round, read the actual articles — do not just list headlines.
When you find conflicting accounts of the same event across different sources, note the discrepancy.
The goal is to understand the SAME situation through multiple national lenses.

After all searches, return ONLY a valid JSON object (no explanation, no markdown fences, just JSON):
{{
  "ceasefire_pct": <integer 0-100>,
  "ceasefire_delta": "<like +2 or -3>",
  "ceasefire_reasoning": "2-3 sentences explaining exactly which news stories pushed this number up or down, and why",

  "escalation": <integer 0-100>,
  "escalation_delta": "<like +5 or -2>",
  "escalation_reasoning": "2-3 sentences explaining exactly which news stories pushed this number up or down, and why",

  "ground_war_pct": <integer 0-100>,
  "ground_war_delta": "<like +1 or -4>",
  "ground_war_reasoning": "2-3 sentences explaining exactly which news stories pushed this number up or down, and why",

  "ticker_items": [
    "🔴 Direct military event or strike",
    "🟡 Political statement or threat",
    "🟢 Diplomatic or de-escalation news"
  ],
  "summary": "2-3 sentence intelligence summary of current situation",

  "sources_count": <integer — total number of individual news articles/sources you read>,
  "sources_breakdown": {{
    "western": <integer — Reuters, AP, BBC, CNN, Bloomberg, Al Jazeera>,
    "iranian": <integer — Nour News, IRNA, PressTV, Tasnim>,
    "arab_palestinian": <integer — Palestine Chronicle, Middle East Eye, Arab News, Gulf News>,
    "israeli": <integer — Times of Israel, Haaretz, Ynet>,
    "financial": <integer — Bloomberg, CNBC, Zawya, oil/markets focus>
  }},
  "sources_quality": "good" | "limited" | "poor",
  "sources_quality_reason": "one sentence — which perspectives had good coverage today and which were thin",
  "perspective_gaps": "one sentence — note any major perspective that was missing or had very little to say today",
  "key_discrepancy": "one sentence — the single biggest factual conflict between sources (e.g. Iran denies X that Reuters reported), or 'none significant' if accounts broadly align",

  "confidence": {{
    "ceasefire_low": <integer — pessimistic estimate>,
    "ceasefire_high": <integer — optimistic estimate>,
    "escalation_low": <integer>,
    "escalation_high": <integer>,
    "ground_war_low": <integer>,
    "ground_war_high": <integer>
  }},

  "tree": [
    {{"index": 0, "probability": <integer>, "note": "one short phrase explaining what news drove this change"}},
    {{"index": 1, "probability": <integer>, "note": "one short phrase"}},
    {{"index": 2, "probability": <integer>, "note": "one short phrase"}},
    {{"index": 3, "probability": <integer>, "note": "one short phrase"}},
    {{"index": 4, "probability": <integer>, "note": "one short phrase"}}
  ],

  "actor_decisions": {{
    "us":   {{"Withdraw": <integer>, "Negotiate": <integer>, "Escalate": <integer>}},
    "iran": {{"Escalate": <integer>, "Attrit":    <integer>, "Negotiate": <integer>}}
  }},

  "timeline_event": {{
    "date":  "<like Apr 5>",
    "day":   <integer — conflict day number>,
    "cf":    <ceasefire_pct integer>,
    "es":    <escalation integer>,
    "gw":    <ground_war_pct integer>,
    "rg":    14,
    "event": "brief one-line summary of today's single most important development",
    "hot":   <true if this is a major turning-point event, else false>
  }},

  "matrix": {{
    "vals": [
      [
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>]
      ],
      [
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>]
      ],
      [
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>],
        [<US_payoff>, <Iran_payoff>]
      ]
    ],
    "nash": [<row 0-2>, <col 0-2>],
    "shifting": [<row 0-2>, <col 0-2>],
    "nash_reasoning": "1-2 sentences: which cell is Nash and why neither side wants to deviate first",
    "cell_changes": [
      {{"cell": "row,col", "reason": "what today's news changed about this cell"}}
    ]
  }}
}}

Rules:
- 🔴 = military action, strikes, casualties, weapons
- 🟡 = political statements, threats, negotiations in doubt
- 🟢 = diplomacy, ceasefire talks, de-escalation moves
- Include 5-8 ticker_items covering today's key developments
- Try to include at least one ticker item sourced from Iranian/Arab media if available
- For each reasoning field: cite specific headlines or events you found, explain the logic clearly
- When Western and non-Western sources contradict each other, note it in your reasoning
- Count every distinct article or source you read for sources_count
- Be honest about sources_quality: if news is sparse today, say so
- Base probability estimates on the COMBINED picture from all sources, not just Western wire services

PAYOFF MATRIX INSTRUCTIONS:
The matrix has 3 US strategies (rows) vs 3 Iran strategies (cols).
Rows: 0=Escalate to ground war, 1=Continue air+Hormuz, 2=Negotiate/US exit
Cols: 0=Iran full escalation (tri-axis), 1=Iran attrit+Hormuz block, 2=Iran accepts deal

For each of the 9 cells score US payoff and Iran payoff on scale -10 to +10.
Use these 4 factors from today's news to justify each value:

  MILITARY COST: How many casualties, strikes, capability losses happened today?
    → More violence = lower payoffs for escalation cells
  ECONOMIC COST: What is oil price? Are sanctions biting? Are shipping routes blocked?
    → Higher oil/disruption = lower payoffs across the board, especially for prolonged war
  POLITICAL STANDING: What do allies, public opinion, and UN say today?
    → More isolation = lower payoffs for aggressive cells
  STRATEGIC POSITION: Who gained/lost territory or leverage today?
    → Gains = higher payoff for that side's aggressive options

Then find the Nash Equilibrium mathematically:
  For each cell, ask: "If Iran plays THIS column, does US prefer a DIFFERENT row?"
  And: "If US plays THIS row, does Iran prefer a DIFFERENT column?"
  The Nash cell = where the answer is NO to both questions (neither side gains by moving first).

The "shifting" cell = where both sides' incentives are currently pointing toward.

CONFIDENCE RANGE INSTRUCTIONS:
For each metric give a low (pessimistic) and high (optimistic) estimate.
The range should reflect genuine uncertainty — if news is mixed, widen the range.
Example: if ceasefire looks like 18% but could be anywhere 12–25% depending on Trump's speech tonight → low=12, high=25.

PROBABILITY TREE INSTRUCTIONS:
5 top-level branches (index 0–4):
  0 = Trump unilateral exit (baseline was 32%)
  1 = War continues Apr–Jun (baseline was 36%)
  2 = Negotiated ceasefire (baseline was 20%)
  3 = Regime collapse (baseline was 7%)
  4 = Nuclear / Black Swan (baseline was 5%)
All 5 must sum to 100. Update each based on today's news. The note should cite a specific headline.

ACTOR DECISION INSTRUCTIONS:
US decisions: Withdraw / Negotiate / Escalate — must sum to 100.
Iran decisions: Escalate / Attrit / Negotiate — must sum to 100.
Base on today's signals: Trump statements, IRGC actions, diplomatic moves.

TIMELINE EVENT INSTRUCTIONS:
Create ONE new timeline entry summarising today's single most important development.
Use today's ceasefire_pct, escalation, ground_war_pct values you already calculated.
Set hot=true only if this is a major turning point (major attack, ceasefire breakthrough, new country enters war)."""
    }]

    # Accumulate token usage across all API calls in this update
    total_input_tokens  = 0
    total_output_tokens = 0

    # Loop to handle pause_turn (server-side tool iteration limit)
    for iteration in range(5):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4000,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=messages
        )

        # Accumulate token counts from every API call
        total_input_tokens  += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            # Print token usage & estimated cost
            # Opus 4.6 pricing: $5.00 / 1M input tokens, $25.00 / 1M output tokens
            cost_input  = total_input_tokens  / 1_000_000 * 5.00
            cost_output = total_output_tokens / 1_000_000 * 25.00
            cost_total  = cost_input + cost_output
            print(f"  🔢 Tokens used  : {total_input_tokens:,} input  +  {total_output_tokens:,} output")
            print(f"  💰 Est. cost    : ${cost_total:.4f}  (${cost_input:.4f} in + ${cost_output:.4f} out)")

            # Extract JSON from the final text response
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    text = block.text.strip()
                    # Strip markdown code fences if Claude added them
                    text = re.sub(r'^```(?:json)?\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                    # Try direct parse first
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        pass
                    # Fall back to extracting JSON from surrounding text
                    match = re.search(r'\{[\s\S]*\}', text)
                    if match:
                        try:
                            return json.loads(match.group())
                        except json.JSONDecodeError:
                            pass
            print("  ⚠️  Response received but could not parse JSON")
            return None

        elif response.stop_reason == "pause_turn":
            # Server-side tool hit iteration limit — re-send to continue
            messages.append({"role": "assistant", "content": response.content})
            print(f"  ⏳ Continuing search (pass {iteration + 2})...")

        else:
            # Unexpected stop reason — append and retry
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
