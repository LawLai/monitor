"""
generate_index.py  —  Regenerate the Agent LL's Chupe de jaiba landing page.

Called automatically by each monitor's run.py and monitor_agent.py after a
successful pipeline run, so lawlai.github.io/monitor/ always shows the latest
snapshot stats from all three monitors.

Can also be run manually:
    python generate_index.py
"""

import glob
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

REPO_ROOT = Path(__file__).parent
OUTPUT_PATH = REPO_ROOT / "index.html"


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_latest_analysis(monitor_subdir: str) -> dict:
    pattern = str(REPO_ROOT / monitor_subdir / "output" / "analysis" / "analysis_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return {}
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def load_colombia_polymarket() -> dict:
    """Return {candidate: latest_pct} from Colombia history polymarket_seed."""
    history_path = REPO_ROOT / "colombia-monitor" / "history.json"
    if not history_path.exists():
        return {}
    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)
    seed_list = sorted(history.get("polymarket_seed", []),
                       key=lambda s: s.get("date", ""), reverse=True)
    pm = {}
    seen = set()
    for snap in seed_list:
        for c, v in snap.get("candidates", {}).items():
            if c not in seen and v is not None:
                pm[c] = v
                seen.add(c)
    return pm


def load_iran_status() -> dict:
    """Load Iran status from sidecar JSON written by monitor_agent.py."""
    path = REPO_ROOT / "iran_status.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # Fallback: parse the live HTML
    html_path = REPO_ROOT / "us_iran_monitor_live.html"
    if not html_path.exists():
        return {"day": "?", "escalation_pct": "?", "ceasefire_pct": "?", "updated": "N/A"}
    html = html_path.read_text(encoding="utf-8")
    day = re.search(r"Day\s*(\d+)", html[:600])
    title_date = re.search(r"\|\s*([A-Z][a-z]+\s+\d+,\s+\d{4})", html[:600])
    # Find the main escalation/ceasefire pair — look for large clean integers
    esc = re.search(r'"escalation"\s*:\s*(\d+)', html)
    cef = re.search(r'"ceasefire_pct"\s*:\s*(\d+)', html)
    if not esc:
        esc = re.search(r'escalation[^0-9]{1,30}?(\d{1,3})%', html)
    if not cef:
        cef = re.search(r'ceasefire[^0-9]{1,30}?(\d{1,3})%', html)
    return {
        "day": int(day.group(1)) if day else "?",
        "escalation_pct": int(esc.group(1)) if esc else "?",
        "ceasefire_pct": int(cef.group(1)) if cef else "?",
        "updated": title_date.group(1).strip() if title_date else "N/A",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_date(iso: str) -> str:
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except Exception:
        return iso


def pill(status: str) -> str:
    s = (status or "").upper()
    if s in ("COMPETITIVE", "TOSSUP"):
        return "pill-amber"
    if s in ("ESCALATING", "ALERT"):
        return "pill-red"
    if s in ("SAFE", "DOMINATED", "CONSOLIDATED"):
        return "pill-green"
    return "pill-blue"


# ── HTML template ─────────────────────────────────────────────────────────────

def build_html(br: dict, co: dict, co_pm: dict, iran: dict) -> str:
    # ── Brazil ────────────────────────────────────────────────────────────────
    br_race    = br.get("race_status", "N/A")
    br_polling = br.get("polling", {}).get("weighted_first_round", {})
    br_top     = sorted([(k, v) for k, v in br_polling.items() if isinstance(v, (int, float))],
                        key=lambda x: x[1], reverse=True)[:3]
    br_poll_html = " &nbsp;·&nbsp; ".join(
        f'<span class="{"hi" if i == 0 else ""}">{n} {p}%</span>'
        for i, (n, p) in enumerate(br_top)
    ) if br_top else "N/A"
    br_ci      = br.get("consolidation", {}).get("index", "?")
    br_econ    = br.get("economic", {}).get("status", "STABLE")
    br_econ_html = (
        f'<span style="color:#f87171;">Econ Alert</span>'
        if (br.get("economic", {}).get("alerts") or br_econ == "ALERT") else
        f'<strong style="color:var(--green);">Econ Stable</strong>'
    )
    br_date    = fmt_date(br.get("report_date", ""))
    br_pill    = pill(br_race)

    # ── Colombia ──────────────────────────────────────────────────────────────
    co_race    = co.get("race_status", "N/A")
    # Polymarket from seed — map short names
    name_map   = {"Iván Cepeda": "Cepeda", "Paloma Valencia": "Valencia",
                  "Abelardo de la Espriella": "DLE"}
    co_pm_top  = sorted([(name_map.get(k, k), v) for k, v in co_pm.items()
                          if isinstance(v, (int, float))],
                         key=lambda x: x[1], reverse=True)[:3]
    co_pm_html = " &nbsp;·&nbsp; ".join(
        f'<span class="{"hi" if i == 0 else "dim" if i == 2 else ""}">{n} {p}%</span>'
        for i, (n, p) in enumerate(co_pm_top)
    ) if co_pm_top else "N/A"
    co_ci      = co.get("coalition", {}).get("index", "?")
    co_cleavage= co.get("cleavage", {}).get("frame", "?")
    co_date    = fmt_date(co.get("report_date", ""))
    co_pill    = pill(co_race)

    # ── Iran ──────────────────────────────────────────────────────────────────
    ir_day     = iran.get("day", "?")
    ir_esc     = iran.get("escalation_pct", "?")
    ir_cef     = iran.get("ceasefire_pct", "?")
    ir_date    = iran.get("updated", "N/A")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent LL's Chupe de jaiba</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg:        #080d14;
  --surface:   #0e1620;
  --surface2:  #131f2e;
  --border:    #1c2d40;
  --border2:   #243447;
  --blue:      #2563eb;
  --blue-dim:  #1d4ed8;
  --blue-glow: rgba(37,99,235,0.18);
  --text:      #e2eaf4;
  --muted:     #5a7a9a;
  --muted2:    #3a5472;
  --amber:     #f59e0b;
  --red:       #ef4444;
  --green:     #22c55e;
}}

body {{
  font-family: 'Inter', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}}

.topbar {{
  border-bottom: 1px solid var(--border);
  padding: 0 40px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(8,13,20,0.92);
  backdrop-filter: blur(8px);
  position: sticky;
  top: 0;
  z-index: 10;
}}

.brand {{ display: flex; align-items: center; gap: 12px; text-decoration: none; }}
.logo-mark {{ width: 40px; height: 40px; flex-shrink: 0; }}
.brand-name {{ font-size: 13px; font-weight: 700; letter-spacing: 0.08em; color: #fff; text-transform: uppercase; }}
.brand-sub {{ font-size: 9px; font-weight: 500; letter-spacing: 0.18em; color: var(--muted); text-transform: uppercase; margin-top: 1px; font-style: italic; }}
.topbar-right {{ font-size: 11px; color: var(--muted); letter-spacing: 0.04em; }}
.topbar-right span {{ color: var(--green); font-weight: 600; margin-right: 4px; }}

.hero {{ max-width: 960px; margin: 0 auto; padding: 72px 40px 48px; border-bottom: 1px solid var(--border); }}
.hero-eyebrow {{ font-size: 11px; font-weight: 600; letter-spacing: 0.2em; color: var(--blue); text-transform: uppercase; margin-bottom: 16px; }}
.hero-title {{ font-size: 38px; font-weight: 800; letter-spacing: -1px; line-height: 1.1; color: #fff; margin-bottom: 16px; }}
.hero-title em {{ font-style: normal; color: transparent; -webkit-text-stroke: 1px rgba(255,255,255,0.3); }}
.hero-desc {{ font-size: 12px; color: var(--muted); line-height: 1.7; max-width: 480px; }}

.grid-section {{ max-width: 960px; margin: 0 auto; padding: 48px 40px 80px; }}
.grid-label {{ font-size: 10px; font-weight: 700; letter-spacing: 0.2em; color: var(--muted2); text-transform: uppercase; margin-bottom: 24px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}

.card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 24px; text-decoration: none; color: inherit; display: flex;
  flex-direction: column; gap: 0; transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
  position: relative; overflow: hidden;
}}
.card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--card-accent, var(--blue)); opacity: 0; transition: opacity 0.2s; }}
.card:hover {{ border-color: var(--border2); background: var(--surface2); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
.card:hover::before {{ opacity: 1; }}
.card-election {{ --card-accent: #2563eb; }}
.card-conflict  {{ --card-accent: #ef4444; }}

.card-header {{ display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 16px; }}
.card-flag img {{ width: 32px; height: 24px; border-radius: 3px; object-fit: cover; display: block; }}
.card-flag.dual {{ display: flex; gap: 4px; }}

.card-type-badge {{ font-size: 9px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; padding: 3px 7px; border-radius: 4px; background: var(--blue-glow); color: #60a5fa; border: 1px solid rgba(37,99,235,0.2); }}
.card-type-badge.conflict {{ background: rgba(239,68,68,0.12); color: #f87171; border-color: rgba(239,68,68,0.2); }}

.card-title {{ font-size: 16px; font-weight: 700; color: #fff; line-height: 1.3; margin-bottom: 6px; }}
.card-intro {{ font-size: 12.5px; color: var(--muted); line-height: 1.6; margin-bottom: 16px; flex: 1; }}

.snapshot {{ background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 7px; padding: 12px 14px; margin-bottom: 12px; }}
.snapshot-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }}
.snapshot-label {{ font-size: 9px; font-weight: 700; letter-spacing: 0.18em; color: var(--muted2); text-transform: uppercase; }}

.status-pill {{ font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; padding: 2px 7px; border-radius: 20px; }}
.pill-amber {{ background: rgba(245,158,11,0.15); color: var(--amber); }}
.pill-red   {{ background: rgba(239,68,68,0.15);  color: var(--red); }}
.pill-blue  {{ background: var(--blue-glow);       color: #60a5fa; }}
.pill-green {{ background: rgba(34,197,94,0.12);   color: var(--green); }}

.snapshot-line {{ font-size: 11.5px; color: #94a8c0; line-height: 1.7; }}
.snapshot-line strong {{ color: var(--text); font-weight: 600; }}
.snapshot-line .hi  {{ color: #fff; font-weight: 700; }}
.snapshot-line .dim {{ color: var(--muted); }}
.snapshot-divider {{ border: none; border-top: 1px solid var(--border); margin: 7px 0; }}

.card-footer {{ display: flex; align-items: center; justify-content: space-between; }}
.card-updated {{ font-size: 10px; color: var(--muted2); letter-spacing: 0.03em; }}
.card-arrow {{ font-size: 12px; color: var(--muted2); transition: color 0.2s, transform 0.2s; }}
.card:hover .card-arrow {{ color: #60a5fa; transform: translateX(3px); }}

.page-footer {{ border-top: 1px solid var(--border); padding: 24px 40px; max-width: 960px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
.page-footer-left {{ font-size: 11px; color: var(--muted2); }}
.page-footer-left strong {{ color: var(--muted); font-weight: 500; }}
.page-footer-right {{ font-size: 11px; color: var(--muted2); }}

@media (max-width: 600px) {{
  .hero {{ padding: 48px 20px 36px; }}
  .hero-title {{ font-size: 26px; }}
  .grid-section {{ padding: 32px 20px 60px; }}
  .topbar {{ padding: 0 20px; }}
}}
</style>
</head>
<body>

<header class="topbar">
  <a class="brand" href="#">
    <svg class="logo-mark" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">
      <circle cx="20" cy="20" r="19" fill="#0c1a35" stroke="#c9962a" stroke-width="1.8"/>
      <circle cx="20" cy="20" r="15.5" fill="none" stroke="#c9962a" stroke-width="0.5" stroke-dasharray="2.5 2"/>
      <text x="20" y="13.5" font-family="Inter,Arial,sans-serif" font-size="4.8" font-weight="700" fill="#c9962a" text-anchor="middle" letter-spacing="2.2">AGENT</text>
      <circle cx="12" cy="16.5" r="0.9" fill="#c9962a"/>
      <circle cx="28" cy="16.5" r="0.9" fill="#c9962a"/>
      <text x="20" y="27" font-family="Inter,Arial,sans-serif" font-size="13.5" font-weight="800" fill="#ffffff" text-anchor="middle">LL</text>
      <line x1="13" y1="30" x2="27" y2="30" stroke="#c9962a" stroke-width="0.6"/>
    </svg>
    <div class="brand-text">
      <div class="brand-name">Agent LL's</div>
      <div class="brand-sub">Chupe de jaiba</div>
    </div>
  </a>
  <div class="topbar-right"><span>&#9679;</span> 3 monitors active</div>
</header>

<section class="hero">
  <div class="hero-eyebrow">Intelligence Briefings</div>
  <h1 class="hero-title">Chupe De Jaiba<br><em>made by Agent LL</em></h1>
  <p class="hero-desc">AI-powered macro event monitors &mdash; a project to leverage Agentic AI.</p>
</section>

<section class="grid-section">
  <div class="grid-label">Active Monitors</div>
  <div class="grid">

    <a class="card card-election" href="brazil_2026_election_monitor.html">
      <div class="card-header">
        <div class="card-flag"><img src="https://flagcdn.com/br.svg" alt="Brazil"></div>
        <span class="card-type-badge">Election</span>
      </div>
      <div class="card-title">Brazil 2026</div>
      <div class="card-intro">Tracks the October presidential race across polling, Polymarket odds, right-wing coalition formation, and macroeconomic alerts.</div>
      <div class="snapshot">
        <div class="snapshot-header">
          <span class="snapshot-label">Latest Snapshot</span>
          <span class="status-pill {br_pill}">{br_race}</span>
        </div>
        <div class="snapshot-line">{br_poll_html}</div>
        <hr class="snapshot-divider">
        <div class="snapshot-line">
          Consolidation Index <strong>{br_ci}%</strong> &nbsp;&middot;&nbsp; {br_econ_html}
        </div>
      </div>
      <div class="card-footer">
        <span class="card-updated">Updated {br_date}</span>
        <span class="card-arrow">&rarr;</span>
      </div>
    </a>

    <a class="card card-election" href="colombia_2026_election_monitor.html">
      <div class="card-header">
        <div class="card-flag"><img src="https://flagcdn.com/co.svg" alt="Colombia"></div>
        <span class="card-type-badge">Election</span>
      </div>
      <div class="card-title">Colombia 2026</div>
      <div class="card-intro">Monitors the May 31 first round &mdash; Cepeda vs Valencia, runoff coalition index, security cleavage dynamics, and Polymarket odds since August 2025.</div>
      <div class="snapshot">
        <div class="snapshot-header">
          <span class="snapshot-label">Latest Snapshot</span>
          <span class="status-pill {co_pill}">{co_race}</span>
        </div>
        <div class="snapshot-line">{co_pm_html}</div>
        <hr class="snapshot-divider">
        <div class="snapshot-line">
          Coalition Index <strong>{co_ci}%</strong> &nbsp;&middot;&nbsp; Cleavage <strong>{co_cleavage}</strong>
        </div>
      </div>
      <div class="card-footer">
        <span class="card-updated">Updated {co_date}</span>
        <span class="card-arrow">&rarr;</span>
      </div>
    </a>

    <a class="card card-conflict" href="us_iran_monitor_live.html">
      <div class="card-header">
        <div class="card-flag dual">
          <img src="https://flagcdn.com/us.svg" alt="US" style="width:28px;height:18px;">
          <img src="https://flagcdn.com/ir.svg" alt="Iran" style="width:28px;height:18px;">
        </div>
        <span class="card-type-badge conflict">Conflict</span>
      </div>
      <div class="card-title">US&ndash;Iran War</div>
      <div class="card-intro">Game-theory escalation tracker using RSS intelligence feeds, actor objective mapping, and scenario probability modelling.</div>
      <div class="snapshot">
        <div class="snapshot-header">
          <span class="snapshot-label">Latest Snapshot &middot; Day {ir_day}</span>
          <span class="status-pill pill-red">Escalating</span>
        </div>
        <div class="snapshot-line">
          Escalation <span class="hi">{ir_esc}%</span> &nbsp;&middot;&nbsp; Ceasefire <span class="dim">{ir_cef}%</span>
        </div>
        <hr class="snapshot-divider">
        <div class="snapshot-line">Strait of Hormuz pressure &nbsp;&middot;&nbsp; IRGC posture elevated</div>
      </div>
      <div class="card-footer">
        <span class="card-updated">Updated {ir_date}</span>
        <span class="card-arrow">&rarr;</span>
      </div>
    </a>

  </div>
</section>

<footer class="page-footer">
  <div class="page-footer-left">
    <strong>Agent LL's Chupe de jaiba</strong> &nbsp;&middot;&nbsp; lawlai.github.io/monitor
  </div>
  <div class="page-footer-right">Powered by Gemini search + Claude analysis</div>
</footer>

</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_index():
    brazil   = load_latest_analysis("brazil-monitor")
    colombia = load_latest_analysis("colombia-monitor")
    co_pm    = load_colombia_polymarket()
    iran     = load_iran_status()

    html = build_html(brazil, colombia, co_pm, iran)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"  [index] Landing page updated → {OUTPUT_PATH}")


if __name__ == "__main__":
    generate_index()
    print("Done.")
