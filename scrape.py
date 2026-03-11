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
    Parse a string like 'March 10', 'March 10th', 'March 10h' (typo-tolerant),
    or 'February 10, 2026' into a datetime.date.
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
    # Check if year is explicit (e.g. "February 10, 2026")
    y = re.search(r'(\d{4})', text)
    if y:
        year = int(y.group(1))
    else:
        # Infer year: if month < current month by more than 6, use next year
        today = datetime.date.today()
        year = CURRENT_YEAR
        if month < today.month - 6:
            year += 1
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def parse_short_date(text):
    """
    Parse 'Tuesday, 3/10' or 'Thursday, 9/4' or '3/10' into a datetime.date.
    Also handles 'Tuesday, 1/20' with leading day-of-week.
    Returns None if parsing fails.
    """
    m = re.search(r'(\d{1,2})/(\d{1,2})', text)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
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
    Format: The Analysis page uses literal '*' in <p> tags (not proper <li> elements).
    Each talk is a <p> block containing:
      * **Date, Wednesday** (4-5pm)
      **//Speaker//**: Name (Affiliation)
      **//Topic//**: Title
    followed by a <div class="wrap_box"> with the abstract.

    We find the Spring 2026 section and iterate over its <p> children.
    """
    talks = []

    # Find the Spring 2026 heading and its content div
    today = datetime.date.today()
    season = "Spring" if today.month <= 7 else "Fall"
    semester_label = f"{season} {today.year}".lower()

    target = None
    for tag in soup.find_all(re.compile(r'^h[1-5]$')):
        if semester_label in tag.get_text(strip=True).lower():
            target = tag
            break

    if not target:
        debug(f"Anly: no heading found for '{semester_label}'")
        return talks

    # Get the content div that follows the heading
    section_div = None
    for sib in target.find_next_siblings():
        if sib.name and re.match(r'^h[1-5]$', sib.name):
            break
        if sib.name == 'div':
            section_div = sib
            break

    if not section_div:
        debug("Anly: no content div found after heading")
        return talks

    # Each talk is in a <p> that starts with "* Date"
    for p in section_div.find_all('p'):
        text = p.get_text("\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue

        # Skip leading "*" and "(4-5pm)" type lines to find the date
        date = None
        date_idx = 0
        for idx, line in enumerate(lines):
            cleaned = line.lstrip("* ").strip()
            if cleaned in ("*", "") or re.match(r'^\(\d', cleaned):
                continue
            date = parse_month_day(cleaned)
            if date:
                date_idx = idx
                break

        if not date:
            continue

        # Skip organizational / no-meeting entries
        full_text = " ".join(lines).lower()
        if "organizational" in full_text or "no meeting" in full_text:
            debug(f"Anly: skipping non-talk entry for {date}")
            continue

        speaker, affiliation, title, note = _extract_speaker_title(lines[date_idx + 1:])

        if speaker or title:
            debug(f"Anly: {date} | {speaker} | {title[:40] if title else '(no title)'}")
            talks.append({
                "date": date,
                "speaker": speaker,
                "affiliation": affiliation,
                "title": title,
                "url": url,
                **({"note": note} if note else {}),
            })
        else:
            debug(f"Anly: no speaker/title for {date}: {lines[1:3]}")

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
    for tag in soup.find_all(re.compile(r'^h[1-5]$')):
        heading_text = tag.get_text(strip=True).lower()
        if semester_label in heading_text:
            debug(f"Found semester heading: '{tag.get_text(strip=True)}'")
            # Collect all <li> from sibling <ul> elements until the next heading
            items = []
            for sib in tag.find_next_siblings():
                if sib.name and re.match(r'^h[1-5]$', sib.name):
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

        # Skip blanks, abstract lines, and metadata labels
        if not ll or ll.startswith("abstract") or ll.startswith("time") or ll.startswith("location"):
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
            val = re.sub(r'(?i)^speaker\s*:?\s*', '', line).strip()
            # If the label was alone on its line, the name is on the next line
            if not val and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                next_ll = next_line.lower()
                # Handle ": Name (Aff)" pattern (colon split from label)
                if next_line.startswith(":"):
                    i += 1
                    val = next_line.lstrip(": ").strip()
                elif not (next_ll.startswith("title") or next_ll.startswith("abstract")
                        or next_ll.startswith("topic") or next_ll.startswith("time")
                        or next_ll.startswith("location")):
                    i += 1
                    val = next_line
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
        elif ll.startswith("title") or ll.startswith("topic"):
            val = re.sub(r'(?i)^(title|topic)\s*:?\s*', '', line).strip()
            # Same: title text might be on the next line
            if not val and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                next_ll = next_line.lower()
                if next_line.startswith(":"):
                    i += 1
                    val = next_line.lstrip(": ").strip()
                elif not (next_ll.startswith("speaker") or next_ll.startswith("abstract")
                        or next_ll.startswith("time") or next_ll.startswith("location")):
                    i += 1
                    val = next_line
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
# Statistics and Data Science parsers
# ---------------------------------------------------------------------------

def parse_statistics(soup, url):
    """
    Format (DokuWiki rendered):
      **Date**
      Speaker: **Name (Affiliation)**
      Title: text
      Abstract link

    Same split-line pattern as Geometry/Topology.
    """
    talks = []
    items = _find_current_semester_section(soup)

    for li in items:
        raw = li.get_text("\n")
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            continue

        date = parse_month_day(lines[0])
        if not date:
            debug(f"Stat: no date in: {lines[0][:60]}")
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
            debug(f"Stat: {date} | {speaker} | {title[:40] if title else '(no title)'}")
            talks.append(entry)

    return talks


def parse_datasci(soup, url):
    """
    Format (DokuWiki rendered):
      **Date, Year**
      //Speaker//: Dr. Name (Affiliation)
      //Topic//: text

    The italic labels cause text splitting issues with get_text("\n"),
    so we use the full text and regex instead.
    """
    talks = []
    content_div = soup.find("div", class_="dokuwiki")
    if not content_div:
        return talks

    for li in content_div.find_all("li"):
        text = li.get_text(" ", strip=True)

        # Skip cancelled entries
        if "cancelled" in text.lower():
            continue

        # Find date
        date_m = re.search(r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4})', text, re.IGNORECASE)
        if not date_m:
            continue
        date = parse_month_day(date_m.group(1))
        if not date:
            continue

        # Extract speaker — between "Speaker :" and either "Topic" or end
        speaker, affiliation, title = "", "", ""
        sp_m = re.search(r'Speaker\s*:\s*(.+?)(?:\s*Topic\s*:|$)', text, re.IGNORECASE)
        if sp_m:
            speaker_raw = sp_m.group(1).strip()
            # Strip "Dr." prefix and link artifacts
            speaker_raw = re.sub(r'^Dr\.\s*', '', speaker_raw).strip()
            aff_m = re.search(r'\(([^)]+)\)', speaker_raw)
            if aff_m:
                affiliation = aff_m.group(1)
                speaker = re.sub(r'\s*\([^)]*\)', '', speaker_raw).strip()
            else:
                speaker = speaker_raw

        # Extract topic/title
        tp_m = re.search(r'Topic\s*:\s*(.+?)(?:\s*Abstract|$)', text, re.IGNORECASE)
        if tp_m:
            title_raw = tp_m.group(1).strip().rstrip(".")
            if not is_placeholder(title_raw):
                title = title_raw

        if speaker or title:
            debug(f"DS: {date} | {speaker} | {title[:40] if title else '(no title)'}")
            talks.append({
                "date": date,
                "speaker": speaker,
                "affiliation": affiliation,
                "title": title,
                "url": url,
            })

    return talks


def parse_combinatorics(soup, url):
    """
    Format: dash-list items with labeled fields.
      **Tuesday, M/D**
      Speaker: Name (Affiliation)
      Title: text
      Time: 1:30-2:30
      Location: WH 100E

    DokuWiki's nested indentation makes DOM traversal unreliable,
    so we extract the full section text and split by date patterns.
    """
    talks = []

    # Find the current semester heading
    today = datetime.date.today()
    season = "Spring" if today.month <= 7 else "Fall"
    semester_label = f"{season} {today.year}".lower()

    target_section = None
    for tag in soup.find_all(re.compile(r'^h[1-5]$')):
        if semester_label in tag.get_text(strip=True).lower():
            target_section = tag
            break

    if not target_section:
        debug(f"Comb: no heading found for '{semester_label}'")
        return talks

    # Get all text between this heading and the next one
    section_parts = []
    for sib in target_section.find_next_siblings():
        if sib.name and re.match(r'^h[1-5]$', sib.name):
            break
        section_parts.append(sib.get_text("\n"))
    section_text = "\n".join(section_parts)

    # Split by date patterns: "Tuesday, M/D" or "Thursday, M/D" etc.
    day_pattern = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,\s*\d{1,2}/\d{1,2}'
    chunks = re.split(f'({day_pattern})', section_text, flags=re.IGNORECASE)

    # chunks alternates: [preamble, date1, text1, date2, text2, ...]
    i = 1  # skip preamble
    while i < len(chunks) - 1:
        date_str = chunks[i].strip()
        body = chunks[i + 1].strip()
        i += 2

        date = parse_short_date(date_str)
        if not date:
            continue

        # Skip no-seminar / holiday / cancelled / organizational entries
        full_text = (date_str + " " + body).lower()
        skip_phrases = ["no seminar", "organizational meeting", "holiday",
                        "cancelled", "no meeting", "it's \"monday\"",
                        "it is \"friday\"", "it is \"monday\"",
                        "closed for repairs", "takes a holiday",
                        "working holiday", "m. seminaire takes a holiday"]
        if any(phrase in full_text for phrase in skip_phrases):
            debug(f"Comb: skipping non-talk entry for {date}")
            continue

        # Parse speaker and title from the body text
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        speaker, affiliation, title, note = _extract_speaker_title(lines)

        if speaker or title:
            debug(f"Comb: {date} | {speaker} | {title[:40] if title else '(no title)'}")
            talks.append({
                "date": date,
                "speaker": speaker,
                "affiliation": affiliation,
                "title": title,
                "url": url,
                **({"note": note} if note else {}),
            })

    return talks


def parse_arithmetic(soup, url):
    """
    Format (DokuWiki rendered):
      **Date**
      **//Speaker//**: Name (Affiliation)
      **//Title//**: text
      **//Abstract//**: ...

    Same split-line pattern as Geometry/Topology and Statistics.
    """
    talks = []
    items = _find_current_semester_section(soup)

    for li in items:
        raw = li.get_text("\n")
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            continue

        date = parse_month_day(lines[0])
        if not date:
            debug(f"Arit: no date in: {lines[0][:60]}")
            continue

        # Skip organizational meetings
        full_text = " ".join(lines).lower()
        if "organizational meeting" in full_text:
            debug(f"Arit: skipping org meeting for {date}")
            continue

        speaker, affiliation, title, note = _extract_speaker_title(lines[1:])

        # Skip "NA" or "TBA" speakers
        if speaker.upper() in ("NA", "TBA", ""):
            if not title or is_placeholder(title):
                continue

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
            debug(f"Arit: {date} | {speaker} | {title[:40] if title else '(no title)'}")
            talks.append(entry)

    return talks


# Map seminar name → parser function
PARSERS = {
    "Algebra":           parse_algebra,
    "Analysis":          parse_analysis,
    "Arithmetic":        parse_arithmetic,
    "Combinatorics":     parse_combinatorics,
    "Data Science":      parse_datasci,
    "Geometry/Topology": parse_geom_topology,
    "Statistics":        parse_statistics,
    # "Colloquium":      parse_colloquium,      # not active this semester
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
            default_time = sem.get("time", "")
            for t in talks:
                if start <= t["date"] <= end:
                    t["seminar"] = name
                    t["default_time"] = default_time
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