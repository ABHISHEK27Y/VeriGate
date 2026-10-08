"""Record the VeriGate dashboard playground into an animated GIF.

Requires the gateway running on :8000 (uvicorn app.main:app) and Playwright + Pillow.
    python scripts/make_demo_gif.py
Writes docs/demo.gif.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000/ui"
OUT = Path(__file__).resolve().parent.parent / "docs" / "demo.gif"
FRAMES = Path(__file__).resolve().parent.parent / "scripts" / "_frames"
FRAMES.mkdir(exist_ok=True)

# (query, caption) — the story: MISS -> HIT (paraphrase) -> MISS -> BLOCKED (look-alike) -> BYPASS
STEPS = [
    "how do I reset my password",
    "what is the process to recover my account password",
    "please tell me the total monthly cost of the 5 gb data plan for a new user",
    "please tell me the total monthly cost of the 50 gb data plan for a new user",
    "what is the weather today",
]


def main() -> None:
    frame_files: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1240, "height": 820},
                                device_scale_factor=1)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(600)
        # focus the playground section
        page.eval_on_selector("#playground", "el => el.scrollIntoView()")
        page.wait_for_timeout(400)
        # clean slate
        page.click("#clear")
        page.click("#reset")
        page.wait_for_timeout(400)

        for i, q in enumerate(STEPS):
            page.fill("#query", q)
            page.click("#ask")
            # wait for the result badge to update
            page.wait_for_timeout(1500)
            page.eval_on_selector("#playground", "el => el.scrollIntoView()")
            f = FRAMES / f"frame_{i:02d}.png"
            page.screenshot(path=str(f))
            frame_files.append(f)
            print(f"captured: {q[:48]!r}")

        browser.close()

    # assemble GIF (resize + palette to keep it small)
    imgs = []
    for f in frame_files:
        im = Image.open(f).convert("RGB")
        w = 960
        im = im.resize((w, int(im.height * w / im.width)))
        imgs.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))

    # hold each frame ~1.7s, last frame ~2.6s
    durations = [1700] * (len(imgs) - 1) + [2600]
    imgs[0].save(OUT, save_all=True, append_images=imgs[1:], duration=durations,
                 loop=0, optimize=True, disposal=2)
    size_kb = OUT.stat().st_size / 1024
    print(f"\nSaved {OUT}  ({size_kb:.0f} KB, {len(imgs)} frames)")


if __name__ == "__main__":
    main()
