"""Regenerate assets/hero.png (DEMO leaderboard) and assets/flow.png.

    pip install playwright && python -m playwright install chromium
    python scripts/make_assets.py

hero.png is a screenshot of the real leaderboard built from simulated
(mock) models, so every row is tagged DEMO. No real model scores.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def shot(src: Path, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        page.goto(src.resolve().as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out))
        browser.close()
    print("wrote", out)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cli = [sys.executable, "-m", "ar_llm_eval"]
        subprocess.run([*cli, "demo", "--out", tmp], check=True)
        board = Path(tmp) / "board.html"
        subprocess.run([*cli, "board", f"{tmp}/results", "--out", str(board), "--no-items"], check=True)
        shot(board, ROOT / "assets" / "hero.png")
    shot(ROOT / "scripts" / "flow.html", ROOT / "assets" / "flow.png")


if __name__ == "__main__":
    main()
