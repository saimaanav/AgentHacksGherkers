"""Record the demo with Playwright. The recording is code: every take is identical.

    python video/record.py --url https://<your-modal-url>            # writes video/out/demo.webm
    python video/record.py --url http://localhost:8000 --fast        # skip the card holds, for checking

Then mix the voice over it:

    ffmpeg -i video/out/demo.webm -i voice.m4a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo.mp4

Timeline (BUILD_PLAN.md §8.1):
    0:00–0:14  comparison card, then the opening screen
    0:14–0:30  Review → Discard → Yes always → Approve → the world fills
    0:30–0:45  Play 5 Fridays, the learned panel fills
    0:45–1:12  Autopilot, four holds
    1:12–1:37  architecture card → Friday 1's Logfire trace → the checked-vs-held chart
    1:37–1:50  real vs simulated card
    1:50–2:00  closing card
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
CARDS = ROOT / "web" / "cards"
ASSETS = HERE / "assets"  # put logfire-trace.png and logfire-chart.png here (screenshots, §3 3:45 block)

VIEWPORT = {"width": 1440, "height": 900}


def chromium_kwargs() -> dict:
    """Use a preinstalled Chromium when Playwright's own download is absent (PLAYWRIGHT_CHROMIUM=/path/to/chrome)."""
    import os

    path = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if not path:
        for candidate in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")):
            path = str(candidate)
    return {"executable_path": path} if path else {}


class Clock:
    """Absolute timestamps from the start of the recording, so the voiceover lines up."""

    def __init__(self, fast: bool) -> None:
        self.t0 = time.monotonic()
        self.fast = fast

    def until(self, seconds: float) -> None:
        if self.fast:
            return
        remaining = self.t0 + seconds - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def now(self) -> float:
        return time.monotonic() - self.t0


def show_image(page, path: Path, caption: str) -> None:
    """Show a screenshot full-frame on the dark background (the Logfire trace and chart)."""
    if not path.exists():
        page.set_content(
            f"<body style='margin:0;background:#0b0f14;color:#8a9bb0;font:28px system-ui;display:flex;"
            f"align-items:center;justify-content:center;height:100vh'>{caption} — add {path.name} to video/assets/</body>"
        )
        return
    data = path.read_bytes()
    import base64

    b64 = base64.b64encode(data).decode()
    page.set_content(
        "<body style='margin:0;background:#0b0f14;display:flex;align-items:center;justify-content:center;height:100vh'>"
        f"<img src='data:image/png;base64,{b64}' style='max-width:96vw;max-height:92vh;border-radius:12px'></body>"
    )


def record(url: str, fast: bool) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_kwargs())
        context = browser.new_context(viewport=VIEWPORT, record_video_dir=str(OUT), record_video_size=VIEWPORT, color_scheme="dark")
        page = context.new_page()
        clock = Clock(fast)

        # 0:00 comparison card
        page.goto((CARDS / "comparison.html").as_uri())
        clock.until(7.0)

        # 0:07 the opening screen: end of Friday 1, world at 0
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("[data-screen='opening']", timeout=30_000)
        clock.until(14.0)

        # 0:14 review → discard → yes always → approve
        page.click("[data-action='review']")
        page.wait_for_selector("[data-screen='review']")
        clock.until(19.0)
        page.click("[data-action='discard']")
        clock.until(23.0)
        page.click("[data-action='rule-accept']")
        clock.until(26.0)
        page.click("[data-action='approve']")
        clock.until(30.0)

        # 0:30 montage
        page.click("[data-action='montage']")
        clock.until(45.0)

        # 0:45 autopilot (ten Fridays over ~25 s)
        page.click("[data-action='autopilot']")
        clock.until(72.0)

        # 1:12 architecture card → trace → chart
        page.goto((CARDS / "architecture.html").as_uri())
        clock.until(82.0)
        show_image(page, ASSETS / "logfire-trace.png", "Friday 1's Logfire trace")
        clock.until(90.0)
        show_image(page, ASSETS / "logfire-chart.png", "Checked vs held, twenty Fridays")
        clock.until(97.0)

        # 1:37 real vs simulated
        page.goto((CARDS / "real-vs-simulated.html").as_uri())
        clock.until(110.0)

        # 1:50 closing, hold the last frame
        page.goto((CARDS / "closing.html").as_uri())
        clock.until(120.0 if not fast else 0)
        if not fast:
            time.sleep(3.0)

        print(f"recorded {clock.now():.1f}s", file=sys.stderr)
        video = page.video
        context.close()
        browser.close()
        src = Path(video.path())
    dst = OUT / "demo.webm"
    shutil.move(str(src), dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="the deployed Modal URL, or http://localhost:8000")
    ap.add_argument("--fast", action="store_true", help="no holds between steps; for checking the selectors")
    args = ap.parse_args()
    out = record(args.url, args.fast)
    print(out)


if __name__ == "__main__":
    main()
