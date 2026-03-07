"""
scrape.py  –  fetch seminar pages and extract upcoming talks.

Each parser function receives a BeautifulSoup object of the page and
returns a list of dicts:
    {
        "date":        datetime.date,
        "speaker":     str,
        "affiliation": str,   # may be empty
        "title":       str,   # may be empty / "TBD"
        "url":         str,   # link back to the seminar page
    }
"""

import re
import datetime
import requests
from bs4 import BeautifulSoup

from config import SEMINARS, LOOKAHEAD_DAYS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CURRENT_YEAR = datetime.date.today().year

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

DEBUG = False   # set via --debug flag


def debug(msg):
    if DEBUG:
        print(f"    [DEBUG] {msg}")


def parse_month_day(text):
    """
    Parse a string like 'March 10', 'March 10th', 'March 10h' (typo-tolerant)
    into a datetime.date, inferring the year from context.
    Returns None if parsing fails.
    """
    text = text.strip().lower()
    # Strip ordinal suffixes (including common typos like '29h')
    text = re.sub(r'(\d+)(st|nd|rd|th|h)\b', r'\1', text)
    # Try to match 'month day'
    m = re.search(r'([a-z]+)\s+(\d{1,2})', text)
    if not m:
        return None
    month_name, day = m.group(1), int(m.group(2))
    month = MONTH_MAP.get(month_name)
    if not month:
        return None
    # If the month is before January of the current year we might be wrapping;
    # simple heuristic: if month < current month by more than 6, use next year.
    today = datetime.date.today()
    year = CURRENT_YEAR
    if month < today.month - 6:
        year += 1
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def is_placeholder(text):
    """Return True if the text is an unfilled placeholder."""
    if not text:
        return True
    t = text.strip().lower().rstrip(":")
    return t in {"", "title", "tbd", "text of abstract", "tba", "abstract"}


def upcoming_window():
    """Return (start, end) dates for the lookahead window."""
    today = datetime.date.today()
    return today, today + datetime.timedelta(days=LOOKAHEAD_DAYS)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_page(url):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  WARNING: could not fetch {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Parsers  (one per page format – add as formats are confirmed)
# ---------------------------------------------------------------------------

def parse_algebra(soup, url):
    """
    Format: positional list items.
      **Date**
      Speaker (Affiliation)
      ***Title***
      ***Abstract***: ...
    """
    talks = []
    content_div = soup.find("div", class_="dokuwiki")
    if not content_div:
        return talks

    for li in content_div.find_all("li"):
        text = li.get_text(" ", strip=True)
        lines = [l.strip() for l in li.get_text("\n").split("\n") if l.strip()]
        if not lines:
            continue

        date = parse_month_day(lines[0])
        if not date:
            continue

        # Skip 'No Meeting' entries
        if any("no meeting" in l.lower() for l in lines):
            continue

        speaker_aff = lines[1] if len(lines) > 1 else ""
        aff_m = re.search(r'\(([^)]+)\)', speaker_aff)
        affiliation = aff_m.group(1) if aff_m else ""
        speaker = re.sub(r'\s*\([^)]*\)', '', speaker_aff).strip()

        title = lines[2] if len(lines) > 2 else ""
        if is_placeholder(title):
            title = ""

        talks.append({
            "date": date,
            "speaker": speaker,
            "affiliation": affiliation,
            "title": title,
            "url": url,
        })
    return talks


def parse_analysis(soup, url):
    """
    Format: labeled fields.
      ***Speaker***: Name (Affiliation)
      ***Topic***: Title
      ***Abstract***: ...
    """
    talks = []
    content_div = soup.find("div", class_="dokuwiki")
    if not content_div:
        return talks

    for li in content_div.find_all("li"):
        raw = li.get_text("\n")
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            continue

        date = parse_month_day(lines[0])
        if not date:
            continue

        speaker, affiliation, title = "", "", ""
        for line in lines[1:]:
            ll = line.lower()
            if ll.startswith("speaker"):
                val = re.sub(r'(?i)^speaker\s*:\s*', '', line).strip()
                aff_m = re.search(r'\(([^)]+)\)', val)
                affiliation = aff_m.group(1) if aff_m else ""
                speaker = re.sub(r'\s*\([^)]*\)', '', val).strip()
            elif ll.startswith("topic") or ll.startswith("title"):
                val = re.sub(r'(?i)^(topic|title)\s*:\s*', '', line).strip()
                if not is_placeholder(val):
                    title = val

        if speaker or title:
            talks.append({
                "date": date,
                "speaker": speaker,
                "affiliation": affiliation,
                "title": title,
                "url": url,
            })
    return talks


def _find_current_semester_section(soup):
    """
    Find the section of the page corresponding to the current semester.
    Returns a list of <li> elements within that section.

    DokuWiki seminar pages typically have an <h1> like 'Spring 2026'
    followed by a <ul> with the talk list. Past semesters are behind
    collapsible blocks or further down the page.
    """
    # Look for the current semester heading
    today = datetime.date.today()
    season = "Spring" if today.month <= 7 else "Fall"
    semester_label = f"{season} {today.year}".lower()

    # Strategy 1: find an h1/h2/h3 matching the semester, then get the
    # <ul> that follows it.
    for tag in soup.find_all(re.compile(r'^h[1-3]$')):
        heading_text = tag.get_text(strip=True).lower()
        if semester_label in heading_text:
            debug(f"Found semester heading: '{tag.get_text(strip=True)}'")
            # Collect all <li> from sibling <ul> elements until the next heading
            items = []
            for sib in tag.find_next_siblings():
                if sib.name and re.match(r'^h[1-3]$', sib.name):
                    break  # hit next section
                if sib.name == 'ul':
                    items.extend(sib.find_all('li', recursive=False))
                # Also handle <div> wrappers around <ul>
                elif sib.name == 'div':
                    for ul in sib.find_all('ul'):
                        items.extend(ul.find_all('li', recursive=False))
            debug(f"Found {len(items)} list items under semester heading")
            return items

    debug(f"No semester heading found for '{semester_label}', falling back to all <li>")
    # Fallback: return all <li> in the main content
    content_div = soup.find("div", class_="dokuwiki")
    if content_div:
        return content_div.find_all("li")
    return []


def _extract_speaker_title(lines):
    """
    Given the text lines of a talk entry (after the date line),
    extract speaker, affiliation, and title.

    Handles both:
      - Labeled format: "Speaker: Name (Aff)" / "Title: ..."
      - Split format:   "Speaker:" on one line, name on the next,
        possibly affiliation on a third line like "(University of X)"
      - Special events: "PETER HILTON MEMORIAL LECTURE" etc.
    """
    speaker, affiliation, title = "", "", ""
    is_special = False
    special_info = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        ll = line.lower().strip()

        # Skip blanks and abstract lines
        if not ll or ll.startswith("abstract"):
            i += 1
            continue

        # Detect special events
        if "memorial lecture" in ll:
            is_special = True
            i += 1
            continue

        # Capture special time/location info
        if "special time" in ll:
            is_special = True
            # Extract time and location after it
            # Typical format: "SPECIAL TIME AND LOCATION: March 13, 3:30pm, Alumni Lounge..."
            m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*,?\s*(.*)', line, re.IGNORECASE)
            if m:
                time_str = m.group(1).strip()
                loc_str = m.group(2).strip()
                if loc_str:
                    special_info = f"{time_str}, {loc_str}"
                else:
                    special_info = time_str
            i += 1
            continue

        if ll.startswith("speaker"):
            val = re.sub(r'(?i)^speaker\s*:\s*', '', line).strip()
            # If the label was alone on its line, the name is on the next line
            if not val and i + 1 < len(lines):
                next_ll = lines[i + 1].strip().lower()
                # Don't grab the next line if it's another label
                if not (next_ll.startswith("title") or next_ll.startswith("abstract")):
                    i += 1
                    val = lines[i].strip()
            # Check if affiliation is already in parentheses within val
            aff_m = re.search(r'\(([^)]+)\)', val)
            if aff_m:
                affiliation = aff_m.group(1)
                speaker = re.sub(r'\s*\([^)]*\)', '', val).strip()
            else:
                speaker = val.strip()
                # Affiliation might be on the next line as "(University of X)"
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.startswith("(") and next_line.endswith(")"):
                        i += 1
                        affiliation = next_line[1:-1]
        elif ll.startswith("title"):
            val = re.sub(r'(?i)^title\s*:\s*', '', line).strip()
            # Same: title text might be on the next line
            if not val and i + 1 < len(lines):
                next_ll = lines[i + 1].strip().lower()
                if not (next_ll.startswith("speaker") or next_ll.startswith("abstract")):
                    i += 1
                    val = lines[i].strip()
            if not is_placeholder(val):
                title = val

        i += 1

    # Build note from special info
    note = ""
    if is_special and special_info:
        note = special_info
    elif is_special:
        note = "Special event"

    return speaker, affiliation, title, note


def parse_geom_topology(soup, url):
    """
    Format: inline labels within list items.
      **Date**
      Speaker: **Name (Affiliation)**
      Title: **Title**
      *Abstract:* ...

    Also handles special events like the Peter Hilton Memorial Lecture.
    """
    talks = []
    items = _find_current_semester_section(soup)

    for li in items:
        raw = li.get_text("\n")
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            continue

        # Try to find a date in the first line
        date = parse_month_day(lines[0])
        if not date:
            debug(f"No date in: {lines[0][:60]}")
            continue

        # Skip 'no seminar' / 'spring break' entries
        full_text = " ".join(lines).lower()
        if "no seminar" in full_text or "spring break" in full_text:
            debug(f"Skipping no-seminar entry for {date}")
            continue

        speaker, affiliation, title, note = _extract_speaker_title(lines[1:])

        if speaker or title:
            entry = {
                "date": date,
                "speaker": speaker,
                "affiliation": affiliation,
                "title": title,
                "url": url,
            }
            if note:
                entry["note"] = note
            debug(f"Found: {date} | {speaker} | {title[:40]}")
            talks.append(entry)
        else:
            debug(f"No speaker/title for {date}: {lines[1:3]}")

    return talks


# ---------------------------------------------------------------------------
# TODO: add parsers for remaining seminars once formats are confirmed
# ---------------------------------------------------------------------------
# parse_colloquium(soup, url)   – format TBD
# parse_arithmetic(soup, url)   – format TBD
# parse_combinatorics(soup, url) – format TBD
# parse_datasci(soup, url)      – format TBD
# parse_statistics(soup, url)   – format TBD

# Map seminar name → parser function
PARSERS = {
    "Algebra":           parse_algebra,
    "Analysis":          parse_analysis,
    "Geometry/Topology": parse_geom_topology,
    # Add remaining parsers here as they are written:
    # "Colloquium":      parse_colloquium,
    # "Arithmetic":      parse_arithmetic,
    # "Combinatorics":   parse_combinatorics,
    # "Data Science":    parse_datasci,
    # "Statistics":      parse_statistics,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_upcoming_talks():
    """
    Scrape all configured seminar pages and return talks in the lookahead window,
    sorted by date.
    """
    start, end = upcoming_window()
    results = []

    for sem in SEMINARS:
        name = sem["name"]
        url  = sem["url"]
        parser = PARSERS.get(name)

        if parser is None:
            print(f"  SKIP: no parser yet for '{name}'")
            continue

        print(f"  Fetching {name} ...")
        try:
            soup = fetch_page(url)
            if soup is None:
                continue

            talks = parser(soup, url)
            for t in talks:
                if start <= t["date"] <= end:
                    t["seminar"] = name
                    results.append(t)
        except Exception as e:
            print(f"  ERROR parsing {name}: {e}")
            continue

    results.sort(key=lambda t: t["date"])
    return results


if __name__ == "__main__":
    import sys
    if "--debug" in sys.argv:
        DEBUG = True
        print("Debug mode ON\n")

    talks = get_upcoming_talks()
    if not talks:
        print("\nNo upcoming talks found.")
    else:
        print(f"\n{len(talks)} upcoming talk(s):\n")
    for t in talks:
        note = f"  [{t.get('note', '')}]" if t.get('note') else ""
        print(f"  {t['date']}  [{t['seminar']}]  {t['speaker']}  —  {t['title'] or '(title TBD)'}{note}")