"""Publish / refresh the LL Macro page on lawlai.github.io/monitor/.

Regenerates the public teaser from the fund's LATEST real dashboard output, drops it
into this GitHub Pages repo, rebuilds the landing page, and commits + pushes — one
command. Run it whenever you want the live page to reflect the current book.

    python publish_ll_macro.py             # regenerate -> commit -> push (go live)
    python publish_ll_macro.py --no-push   # regenerate + commit, but don't push yet
    python publish_ll_macro.py --dry-run   # regenerate the files locally only, no git

Before running: refresh the fund output first so the dashboard artifacts are current.
This script reads whatever is already there — it does not run the book.

It stages ONLY the LL Macro files, so the repo's other untracked experiments are never
swept into a commit.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent                       # LawLai/monitor (GitHub Pages)
FUND = REPO / "macro-fund"                                    # the fund repo (gitignored here)
GEN = FUND / "reporting" / "artifact_page.py"
ART = FUND / "output" / "artifact" / "ll_macro.html"
STATUS = FUND / "output" / "artifact" / "ll_macro_status.json"
INDEX_GEN = REPO / "generate_index.py"
STAGE = ["ll_macro.html", "ll_macro_status.json", "index.html",
         "generate_index.py", "publish_ll_macro.py"]


def run(cmd, cwd=None, check=True):
    print("   $", " ".join(str(c) for c in cmd))
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=check)


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    push = ("--no-push" not in args) and not dry

    if not GEN.exists():
        sys.exit(f"can't find the fund generator at {GEN} — is macro-fund/ present?")

    print("1. regenerating the LL Macro page from the live dashboard...")
    run([sys.executable, GEN])
    if not ART.exists() or not STATUS.exists():
        sys.exit(f"generator did not produce {ART.name} / {STATUS.name}")

    print("2. copying into the GitHub Pages repo root...")
    shutil.copyfile(ART, REPO / "ll_macro.html")
    shutil.copyfile(STATUS, REPO / "ll_macro_status.json")

    print("3. rebuilding the landing page...")
    run([sys.executable, INDEX_GEN])

    if dry:
        print("dry-run complete - files written, git untouched.")
        print(f"   preview: open {REPO / 'index.html'}  and  {REPO / 'll_macro.html'}")
        return 0

    print("4. committing the LL Macro files...")
    st = json.loads(STATUS.read_text(encoding="utf-8"))
    # Neutral message on purpose: commit history is public and append-only, so stance
    # detail (dial/sentiment/top desk) lives only on the overwritable page itself.
    msg = f"LL Macro update {st.get('as_of', '?')}"
    run(["git", "add", "--"] + STAGE, cwd=REPO)
    committed = run(["git", "commit", "-m", msg], cwd=REPO, check=False).returncode == 0
    if not committed:
        print("   (nothing changed since last publish)")

    if push:
        print("5. pushing to GitHub...")
        run(["git", "push", "origin", "main"], cwd=REPO)
        print("\n   Live: https://lawlai.github.io/monitor/  (LL Macro card)")
        print("         https://lawlai.github.io/monitor/ll_macro.html")
    else:
        print("   committed locally; run `git push origin main` when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
