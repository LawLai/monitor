"""
Colombia 2026 Election Monitor — Main Pipeline

Usage:
    python run.py                  # Full run: collect → analyze → generate HTML
    python run.py --collect-only   # Only collect data (skip analysis)
    python run.py --from-cache     # Skip collection, use latest cached data
    python run.py --model MODEL    # Use a specific Claude model (default: claude-sonnet-4-20250514)
    python run.py --no-publish     # Skip GitHub publish

Pipeline:
    1. Collect data (APIs + Gemini CLI searches)
    2. Send to Claude API for analysis
    3. Generate HTML dashboard
    4. Update history.json with this run's data
    5. Publish to GitHub Pages
"""

import argparse
import json
import shutil
import subprocess
import sys
import glob
import io
from datetime import datetime
from pathlib import Path

# Fix Windows cp950 encoding issues + force line buffering so each print()
# appears in real time instead of getting block-buffered behind subprocess output.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_DIR = Path(__file__).parent
REPO_ROOT = PROJECT_DIR.parent  # LL_Claude — the git repo root
PUBLISH_HTML = "colombia_2026_election_monitor.html"

from collect_data import collect_all
from analyze import run_analysis, update_history
from generate_html import generate_html


def load_history():
    """Load history.json."""
    history_path = PROJECT_DIR / "history.json"
    if history_path.exists():
        with open(history_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": [], "polymarket_seed": [], "candidates": {}, "pollster_tiers": {}, "economic_thresholds": {}, "electoral_calendar": {}}


def save_history(history):
    """Save updated history.json."""
    history_path = PROJECT_DIR / "history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def load_latest_collection():
    """Load the most recent collection file."""
    raw_files = sorted(glob.glob(str(PROJECT_DIR / "output" / "raw" / "collection_*.json")))
    if not raw_files:
        print("ERROR: No cached collection files found. Run without --from-cache first.")
        sys.exit(1)
    latest = raw_files[-1]
    print(f"Loading cached collection: {latest}")
    with open(latest, "r", encoding="utf-8") as f:
        return json.load(f)


def push_to_github(analysis):
    """Copy HTML to repo root and push to GitHub Pages."""
    try:
        src = PROJECT_DIR / PUBLISH_HTML
        dst = REPO_ROOT / PUBLISH_HTML
        shutil.copy2(str(src), str(dst))
        print(f"  Copied to repo root: {dst}")

        # Regenerate landing page with fresh stats from all monitors
        try:
            import importlib.util
            _spec = importlib.util.spec_from_file_location("generate_index", REPO_ROOT / "generate_index.py")
            _mod  = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _mod.generate_index()
        except Exception as _e:
            print(f"  [index] Warning: {_e}")

        now = datetime.now().strftime("%b %d %H:%M")
        race = analysis.get("race_status", "?")
        polling = analysis.get("polling", {}).get("first_round", {})
        # exclude "Others"
        ranked = sorted(
            [(k, v) for k, v in polling.items() if k != "Others" and isinstance(v, (int, float))],
            key=lambda x: x[1],
            reverse=True
        )
        leader = f"{ranked[0][0]} {ranked[0][1]}%" if ranked else "?"
        cleavage = analysis.get("cleavage", {}).get("frame", "?")
        ci = analysis.get("coalition", {}).get("index", "?")
        msg = f"Colombia monitor {now} — {race} / Leader: {leader} / Cleavage: {cleavage} / CI: {ci}"

        subprocess.run(["git", "add", PUBLISH_HTML, "index.html"], cwd=str(REPO_ROOT), check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO_ROOT), check=True)
        subprocess.run(["git", "push"], cwd=str(REPO_ROOT), check=True)

        print(f"  Published to GitHub Pages")
    except subprocess.CalledProcessError as e:
        print(f"  GitHub push failed: {e}")
        print(f"  Make sure GitHub Desktop has synced this folder first.")
    except FileNotFoundError:
        print(f"  Git not found — skipping GitHub publish.")


def main():
    parser = argparse.ArgumentParser(description="Colombia 2026 Election Monitor")
    parser.add_argument("--collect-only", action="store_true", help="Only collect data, skip analysis")
    parser.add_argument("--from-cache", action="store_true", help="Use latest cached collection")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
    parser.add_argument("--no-publish", action="store_true", help="Skip GitHub publish")
    args = parser.parse_args()

    print("=" * 60)
    print("  COLOMBIA 2026 ELECTION MONITOR — PIPELINE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    history = load_history()
    run_number = len(history.get("runs", [])) + 1
    print(f"\n  This will be Report #{run_number}")

    # ─── Step 1: Data Collection ────────────────────────────────
    if args.from_cache:
        collection = load_latest_collection()
    else:
        print("\n[STEP 1/3] DATA COLLECTION")
        collection = collect_all()

    if args.collect_only:
        print("\n--collect-only flag set. Stopping after data collection.")
        return

    # ─── Step 2: Analysis ───────────────────────────────────────
    print("\n[STEP 2/3] ANALYSIS")
    print(f"  Model: {args.model}")
    analysis = run_analysis(collection, model=args.model)

    if "parse_error" in analysis:
        print(f"\n  WARNING: Claude returned unparseable JSON.")
        print(f"  Error: {analysis['parse_error']}")
        debug_path = PROJECT_DIR / "output" / "raw" / f"debug_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(analysis.get("raw_output", ""))
        print(f"  Raw output saved to: {debug_path}")
        print("  Aborting HTML generation.")
        return

    # Save analysis JSON
    analysis_dir = PROJECT_DIR / "output" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    analysis_path = analysis_dir / f"analysis_{date_str}.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print(f"  Analysis saved to: {analysis_path}")

    # ─── Step 3: Generate HTML ──────────────────────────────────
    print("\n[STEP 3/3] HTML GENERATION")

    api_data = collection.get("api_data", {})
    history = update_history(history, analysis, api_data)
    save_history(history)
    print(f"  History updated ({len(history['runs'])} runs total)")

    output_path = str(PROJECT_DIR / PUBLISH_HTML)
    generate_html(analysis, history, output_path)
    print(f"  Dashboard: {output_path}")

    # Dated copy
    reports_dir = PROJECT_DIR / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    dated_path = str(reports_dir / f"report_{date_str}.html")
    generate_html(analysis, history, dated_path)
    print(f"  Dated copy: {dated_path}")

    # ─── Summary ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)

    race_status = analysis.get("race_status", "UNKNOWN")
    polling = analysis.get("polling", {}).get("first_round", {})
    coalition = analysis.get("coalition", {})
    cleavage = analysis.get("cleavage", {})
    economic = analysis.get("economic", {})
    polymarket = analysis.get("polymarket", {}).get("current", {})
    runoff_math = analysis.get("runoff_math", {})

    print(f"\n  Race Status:   {race_status}")
    print(f"  Cleavage:      {cleavage.get('frame', '?')} ({cleavage.get('intensity', '?')}) → {cleavage.get('beneficiary', '?')}")

    if polling:
        ranked = sorted(
            [(k, v) for k, v in polling.items() if k != "Others" and isinstance(v, (int, float))],
            key=lambda x: x[1],
            reverse=True
        )
        print(f"  Polling:       {' | '.join(f'{name}: {pct}%' for name, pct in ranked[:3])}")

    if polymarket:
        top_pm = sorted(polymarket.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)
        print(f"  Polymarket:    {' | '.join(f'{name}: {pct}%' for name, pct in top_pm[:3])}")

    ci = coalition.get("index")
    ci_status = coalition.get("status", "")
    if ci is not None:
        print(f"  Coalition:     {ci}% — {ci_status}")

    if runoff_math:
        gap = runoff_math.get("gap", 0)
        print(f"  Runoff math:   Cepeda {runoff_math.get('cepeda_base_pct', '?')}% vs Valencia projected {runoff_math.get('valencia_projected_pct', '?')}% (gap {gap:+.1f})")

    econ_status = economic.get("status", "")
    alerts = economic.get("alerts", [])
    if alerts:
        print(f"  Economic:      {econ_status} — {len(alerts)} alert(s)")
    else:
        print(f"  Economic:      {econ_status}")

    # ─── Step 4: Publish to GitHub ────────────────────────────
    if not args.collect_only and not args.no_publish:
        print("\n[PUBLISH] Pushing to GitHub Pages...")
        push_to_github(analysis)

    print(f"\n  Open the dashboard: {output_path}")
    print(f"  Live: https://lawlai.github.io/monitor/{PUBLISH_HTML}")
    print()


if __name__ == "__main__":
    main()
