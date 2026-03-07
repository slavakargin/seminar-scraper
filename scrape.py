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

def parse_month_day(text):
    """
    Parse a string like 'March 10', 'March 10th', 'March 10th, Wednesday'
    into a datetime.date, inferring the year from context.
    Returns None if parsing fails.
    """
    text = text.strip().lower()
    # Strip ordinal suffixes
    text = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', text)
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
    t = text.strip().lower()
    return t in {"", "title", "tbd", "text of abstract", "tba"}


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
    # The current semester is under an <h2> like 'Spring 2026'
    content_div = soup.find("div", class_="dokuwiki")
    if not content_div:
        return talks

    in_current = False
    for li in content_div.find_all("li"):
        text = li.get_text(" ", strip=True)

        # Detect semester heading proximity – skip past semesters
        # (list items appear under the current <h2>; we stop at the next <hr>)
        # Simple approach: look for bold-only first line as date
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
        # Affiliation is in parentheses
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


def parse_geom_topology(soup, url):
    """
    Format: inline labels within list items.
      **Date**
      Speaker: **Name (Affiliation)**
      Title: **Title**
      <WRAP box>Abstract</WRAP>
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
            elif ll.startswith("title"):
                val = re.sub(r'(?i)^title\s*:\s*', '', line).strip()
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
        soup = fetch_page(url)
        if soup is None:
            continue

        talks = parser(soup, url)
        for t in talks:
            if start <= t["date"] <= end:
                t["seminar"] = name
                results.append(t)

    results.sort(key=lambda t: t["date"])
    return results


if __name__ == "__main__":
    talks = get_upcoming_talks()
    if not talks:
        print("No upcoming talks found.")
    for t in talks:
        print(f"{t['date']}  [{t['seminar']}]  {t['speaker']}  —  {t['title'] or '(title TBD)'}")
