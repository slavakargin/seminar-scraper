"""
build_html.py  –  generate a static HTML page of upcoming seminars.

Reads the template.html file and injects the seminar table.
Writes the result to docs/index.html (served by GitHub Pages).
"""

import os
import re
import datetime
from scrape import get_upcoming_talks
from config import LOOKAHEAD_DAYS

TEMPLATE = os.path.join(os.path.dirname(__file__), "template.html")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
OUTPUT = os.path.join(OUTPUT_DIR, "index.html")


def format_date(d):
    """Format a date like 'Tuesday, Mar 10'."""
    return d.strftime("%A, %b %-d")


def build_table_html(talks):
    """Build an HTML <table> from the list of talk dicts."""
    if not talks:
        return '<p class="no-talks">No seminars scheduled this week.</p>'

    rows = []
    for t in talks:
        speaker = t["speaker"]
        if t.get("affiliation"):
            speaker += f' ({t["affiliation"]})'

        title = t["title"] or "<em>TBA</em>"
        url = t["url"]
        title_link = f'<a href="{url}">{title}</a>'

        # Determine displayed time: use special time if present, else default
        note = t.get("note", "")
        default_time = t.get("default_time", "")
        if note:
            # Extract just the time portion from notes like "3:30pm, Alumni Lounge..."
            time_m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', note, re.IGNORECASE)
            if time_m:
                display_time = f'<strong>{time_m.group(1)}</strong> *'
            else:
                display_time = default_time
        else:
            display_time = default_time

        row_class = ' class="special"' if note else ""
        location_note = ""
        if note and "," in note:
            # Show location for special events
            loc = note.split(",", 1)[1].strip()
            if loc:
                location_note = f' <span class="note">({loc})</span>'

        rows.append(
            f"<tr{row_class}>"
            f"<td>{format_date(t['date'])}</td>"
            f"<td>{display_time}</td>"
            f"<td>{t['seminar']}</td>"
            f"<td>{speaker}</td>"
            f"<td>{title_link}{location_note}</td>"
            f"</tr>"
        )

    return (
        "<table>\n"
        "<tr><th>Date</th><th>Time</th><th>Seminar</th><th>Speaker</th><th>Title</th></tr>\n"
        + "\n".join(rows)
        + "\n</table>"
    )


def build_subtitle():
    today = datetime.date.today()
    end = today + datetime.timedelta(days=LOOKAHEAD_DAYS)
    return (
        f"Week of {today.strftime('%B %-d')}–{end.strftime('%B %-d, %Y')}. "
        f"Updated {today.strftime('%B %-d, %Y')}."
    )


def main():
    print("Scraping seminars...")
    talks = get_upcoming_talks()
    print(f"Found {len(talks)} upcoming talk(s).\n")

    with open(TEMPLATE, "r") as f:
        html = f.read()

    html = html.replace("<!-- SUBTITLE -->", build_subtitle())
    html = html.replace("<!-- TABLE -->", build_table_html(talks))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(html)

    print(f"Written to {OUTPUT}")


if __name__ == "__main__":
    main()