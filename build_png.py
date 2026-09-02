"""
build_png.py  –  render the upcoming seminars as a 1920x1080 PNG for the
                 hallway TV.

Fills template_tv.html with the talks in the TV lookahead window, opens it in
headless Chromium and screenshots the viewport.  Output: docs/seminars.png,
published at https://slavakargin.github.io/seminar-scraper/seminars.png

    python build_png.py            # write docs/seminars.png
    python build_png.py --keep-html  # also keep the intermediate HTML

Requires Playwright's Chromium:
    pip install -r requirements.txt
    playwright install chromium
"""

import os
import sys
import html
import datetime

import scrape
from scrape import get_upcoming_talks
from config import TV_LOOKAHEAD_DAYS

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_tv.html")
OUTPUT_DIR = os.path.join(HERE, "docs")
RENDER_HTML = os.path.join(OUTPUT_DIR, "_tv.html")
OUTPUT_PNG = os.path.join(OUTPUT_DIR, "seminars.png")

WIDTH, HEIGHT = 1920, 1080

# A hallway screen is read in passing, so legibility beats completeness:
# show at most this many talks at full size and count the rest in the footer.
MAX_TALKS = 6


def esc(text):
    return html.escape(text or "", quote=False)


def format_time(talk):
    """'Wed 4:00' -> '4:00 pm'; a special time from the page wins."""
    note = talk.get("note", "")
    if note:
        import re
        m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', note, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    default_time = talk.get("default_time", "")
    clock = default_time.split(" ", 1)[1] if " " in default_time else default_time
    if not clock:
        return ""
    # Seminars all run in the afternoon; 12:15 is still pm.
    return f"{clock} pm"


def build_talks_html(talks):
    if not talks:
        return ('<div class="empty">No seminars scheduled in the next '
                f'{TV_LOOKAHEAD_DAYS} days.</div>')

    rows = []
    for t in talks:
        d = t["date"]
        speaker = esc(t["speaker"]) or '<span class="tba">Speaker TBA</span>'
        aff = f'<div class="aff">{esc(t["affiliation"])}</div>' if t.get("affiliation") else ""
        title = (f'<div class="title">{esc(t["title"])}</div>' if t.get("title")
                 else '<div class="title tba">Title to be announced</div>')
        room = f'<div class="room">{esc(t["room"])}</div>' if t.get("room") else ""
        time_str = esc(format_time(t))

        rows.append(
            '<div class="talk">'
            '<div class="when">'
            f'<div class="day">{d.strftime("%A")}</div>'
            f'<div class="date">{d.strftime("%B %-d")}</div>'
            f'<div class="time">{time_str}</div>'
            '</div>'
            '<div class="what">'
            f'<span class="field">{esc(t["seminar"])}</span>'
            f'{room}'
            '</div>'
            '<div class="who">'
            f'<div class="speaker">{speaker}</div>'
            f'{aff}'
            f'{title}'
            '</div>'
            '</div>'
        )
    return "\n".join(rows)


def build_range(talks):
    today = datetime.date.today()
    end = today + datetime.timedelta(days=TV_LOOKAHEAD_DAYS)
    return f'{today.strftime("%B %-d")} – {end.strftime("%B %-d, %Y")}'


def render_html(talks, overflow=0):
    with open(TEMPLATE) as f:
        page = f.read()
    page = page.replace("<!-- RANGE -->", build_range(talks))
    page = page.replace("<!-- TALKS -->", build_talks_html(talks))
    more = (f'+{overflow} more in this period &nbsp;·&nbsp; ' if overflow else "")
    page = page.replace("<!-- MORE -->", more)
    page = page.replace("<!-- UPDATED -->",
                        f'Updated {datetime.date.today().strftime("%B %-d, %Y")}')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(RENDER_HTML, "w") as f:
        f.write(page)
    return RENDER_HTML


def shoot(html_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        launch = {}
        # The sandboxed CI/container image ships Chromium at a fixed path.
        exe = os.environ.get("CHROMIUM_PATH")
        if exe:
            launch["executable_path"] = exe
        browser = p.chromium.launch(**launch)
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        page.goto("file://" + html_path)
        page.wait_for_timeout(300)   # let fonts settle before the shot
        fitted = page.evaluate("document.documentElement.dataset.fitted")
        page.screenshot(path=OUTPUT_PNG, clip={"x": 0, "y": 0,
                                               "width": WIDTH, "height": HEIGHT})
        browser.close()

    _compress(OUTPUT_PNG)
    return fitted


def _compress(path):
    """
    Re-encode with a 128-colour palette.  The design is flat colour on a flat
    background, so this is visually identical but a third of the size — worth
    it for a file the nightly job rewrites and commits every single day.
    """
    try:
        from PIL import Image
    except ImportError:
        print("  (Pillow not installed - keeping the full-size PNG)")
        return
    before = os.path.getsize(path)
    img = Image.open(path).convert("RGB")
    img.quantize(colors=128, method=Image.MEDIANCUT,
                 dither=Image.NONE).save(path, optimize=True)
    after = os.path.getsize(path)
    print(f"  Compressed {before // 1024} KB -> {after // 1024} KB")


def main():
    print(f"Scraping seminars for the next {TV_LOOKAHEAD_DAYS} days...")
    talks = get_upcoming_talks(days=TV_LOOKAHEAD_DAYS)
    print(f"Found {len(talks)} talk(s) for the display.\n")
    overflow = max(0, len(talks) - MAX_TALKS)
    if overflow:
        print(f"Showing the first {MAX_TALKS}; {overflow} more noted in the footer.")
    talks = talks[:MAX_TALKS]

    # Same guard as build_html.py: never publish a blank board because the
    # department site happened to be down.
    unreachable = scrape.unreachable_seminars()
    if unreachable and not talks:
        print("ABORT: could not reach " + ", ".join(unreachable) +
              " and found no talks; leaving the existing image untouched.")
        sys.exit(1)

    html_path = render_html(talks, overflow)
    fitted = shoot(html_path)
    if fitted and float(fitted) < 1.0:
        print(f"Note: list scaled to {float(fitted):.0%} to fit the frame.")

    if "--keep-html" not in sys.argv:
        os.remove(html_path)

    print(f"Written to {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
