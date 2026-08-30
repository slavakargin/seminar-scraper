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

# Filled in by get_upcoming_talks(): [(seminar_name, reason), ...] for every
# seminar that produced nothing on the last run.  build_html.py reads this so
# an unreachable department site can't silently publish an empty table.
LAST_RUN_HEALTH = []


def unreachable_seminars():
    """Seminars whose page could not be fetched on the last run."""
    return [name for name, reason in LAST_RUN_HEALTH if "could not be fetched" in reason]


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
    Parse 'Tuesday, 3/10', 'Thursday, 9/4', '3/10', or '8/20/2026'
    into a datetime.date.  Returns None if parsing fails.
    """
    # With explicit year first: M/D/YYYY
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None

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


def parse_any_date(text):
    """
    Parse whichever date format a page happens to use:
    'March 10', 'February 10, 2026', 'Tuesday, 3/10', '8/20/2026'.
    Returns None if parsing fails.
    """
    if not text:
        return None
    if re.search(r'\d{1,2}/\d{1,2}', text):
        d = parse_short_date(text)
        if d:
            return d
    return parse_month_day(text)


def current_semester_label():
    """'fall 2026' / 'spring 2026' – the heading text to look for."""
    today = datetime.date.today()
    season = "Spring" if today.month <= 7 else "Fall"
    return f"{season} {today.year}".lower()


# Entries that occupy a date slot but are not talks.
NON_TALK_PATTERNS = (
    "no meeting", "no seminar", "organizational meeting", "organizing meeting",
    "organizational", "cancelled", "canceled", "spring break", "fall break",
    "thanksgiving", "holiday", "monday classes meet", "classes meet",
    "closed for repairs", "takes a holiday", "working holiday",
    "no class", "reading day",
)


def is_non_talk(text):
    """Return True if this entry is a break / org meeting / cancellation."""
    t = (text or "").lower()
    return any(p in t for p in NON_TALK_PATTERNS)


# Values that mean "this field has not been filled in yet".
PLACEHOLDER_VALUES = {
    "", "title", "topic", "speaker", "tbd", "tba", "t.b.a.", "t.b.d.",
    "text of abstract", "abstract", "n/a", "na", "none",
    "name of speaker", "speaker name", "university", "affiliation",
    "???", "??", "?",
}


def is_placeholder(text):
    """Return True if the text is an unfilled placeholder."""
    if not text:
        return True
    t = text.strip().lower().rstrip(":").strip()
    if t in PLACEHOLDER_VALUES:
        return True
    # Rows still holding the template, e.g. "??? ??? (??? University)"
    if re.fullmatch(r'[?\s\.\-–—]*', t):
        return True
    return False


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

        date = parse_any_date(lines[0])
        if not date:
            continue

        speaker_aff = lines[1] if len(lines) > 1 else ""

        # Skip 'No Meeting' / org meeting / 'Monday classes meet' entries.
        # On this page the notice sits in the speaker slot, so check it too.
        if is_non_talk(" ".join(lines)) or is_non_talk(speaker_aff):
            debug(f"Alge: skipping non-talk entry for {date}")
            continue

        aff_m = re.search(r'\(([^)]+)\)', speaker_aff)
        affiliation = aff_m.group(1) if aff_m else ""
        speaker = re.sub(r'\s*\([^)]*\)', '', speaker_aff).strip()
        if is_placeholder(speaker):
            speaker = ""

        title = lines[2] if len(lines) > 2 else ""
        if is_placeholder(title):
            title = ""

        if not (speaker or title):
            debug(f"Alge: no speaker/title for {date}")
            continue

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
    Format (DokuWiki rendered):
      **Date, Wednesday** (4:00-5:00pm)
      **//Speaker//**: Name (Affiliation)
      **//Topic//**: Title
      **//Abstract//**: ...

    Same split-line pattern as Geometry/Topology and Statistics.
    (Until Fall 2026 this page used literal '*' inside <p> tags; it now
    uses proper list items, so we go through _find_current_semester_section.)
    """
    talks = []
    items = _find_current_semester_section(soup)

    for li in items:
        lines = [l.strip() for l in li.get_text("\n").split("\n") if l.strip()]
        if not lines:
            continue

        # The date is on the first non-time line
        date, date_idx = None, 0
        for idx, line in enumerate(lines[:3]):
            cleaned = line.lstrip("* ").strip()
            if not cleaned or re.match(r'^\(\d', cleaned):
                continue
            date = parse_any_date(cleaned)
            if date:
                date_idx = idx
                break

        if not date:
            debug(f"Anly: no date in: {lines[0][:60]}")
            continue

        if is_non_talk(" ".join(lines)):
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
            debug(f"Anly: no speaker/title for {date}")

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
    semester_label = current_semester_label()

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


# Field labels used on the seminar pages.  A line only counts as a label if
# the word is followed by a colon, or is alone on its line — otherwise a real
# title like "Time series and topological data analysis..." is swallowed as if
# it were a "Time:" field.
_ALL_LABELS = r'(?:speakers?|titles?|topics?|abstract|time|location|biography|bio|affiliation)'
_META_LABELS = r'(?:abstract|time|location|biography|bio)'


def _is_label_line(text, labels=_ALL_LABELS):
    t = (text or "").strip().lower()
    if not t:
        return False
    if re.match(rf'^{labels}\s*:', t):
        return True
    return bool(re.fullmatch(rf'{labels}\s*:?', t))


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
        if not ll or _is_label_line(ll, _META_LABELS):
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
            val = re.sub(r'(?i)^speakers?\s*:?\s*', '', line).strip()
            # If the label was alone on its line, the name is on the next line
            if not val and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Handle ": Name (Aff)" pattern (colon split from label)
                if next_line.startswith(":"):
                    i += 1
                    val = next_line.lstrip(": ").strip()
                elif not _is_label_line(next_line):
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
                if next_line.startswith(":"):
                    i += 1
                    val = next_line.lstrip(": ").strip()
                elif not _is_label_line(next_line):
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

    # Drop values that are still page-template placeholders
    if is_placeholder(speaker):
        speaker = ""
    if is_placeholder(affiliation) or "?" in affiliation:
        affiliation = ""
    if is_placeholder(title):
        title = ""

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

        # Try to find a date in the first line (this page has used both
        # 'August 20' and '8/20/2026' styles)
        date = parse_any_date(lines[0])
        if not date:
            debug(f"No date in: {lines[0][:60]}")
            continue

        # Skip 'no seminar' / break entries
        if is_non_talk(" ".join(lines)):
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

        date = parse_any_date(lines[0])
        if not date:
            debug(f"Stat: no date in: {lines[0][:60]}")
            continue

        if is_non_talk(" ".join(lines)):
            debug(f"Stat: skipping non-talk entry for {date}")
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

        # Skip cancelled / break / organizational entries
        if is_non_talk(text):
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
        sp_m = re.search(r'Speakers?\s*:\s*(.+?)(?:\s*Topic\s*:|$)', text, re.IGNORECASE)
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
            if is_placeholder(speaker):
                speaker = ""
            if is_placeholder(affiliation) or "?" in affiliation:
                affiliation = ""

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
    semester_label = current_semester_label()

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
        extra_skips = ["it's \"monday\"", "it is \"friday\"", "it is \"monday\"",
                       "m. seminaire takes a holiday"]
        if is_non_talk(full_text) or any(p in full_text for p in extra_skips):
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

        date = parse_any_date(lines[0])
        if not date:
            debug(f"Arit: no date in: {lines[0][:60]}")
            continue

        # Skip organizational meetings / breaks / cancellations
        if is_non_talk(" ".join(lines)):
            debug(f"Arit: skipping non-talk entry for {date}")
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

    Also prints a health warning for any seminar whose page yielded no talks
    at all for the whole semester — that almost always means the page's
    markup changed and its parser needs updating, which otherwise fails
    silently (the talks just quietly stop appearing).
    """
    global LAST_RUN_HEALTH
    start, end = upcoming_window()
    results = []
    health = []

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
                health.append((name, "page could not be fetched"))
                continue

            talks = parser(soup, url)
            if not talks:
                # Does the page even have a current-semester section?
                has_section = any(
                    current_semester_label() in tag.get_text(strip=True).lower()
                    for tag in soup.find_all(re.compile(r'^h[1-5]$'))
                )
                if has_section:
                    health.append((name, "0 talks parsed from the "
                                         f"{current_semester_label().title()} section"))
                else:
                    health.append((name, f"no '{current_semester_label().title()}' "
                                         "heading on the page"))

            default_time = sem.get("time", "")
            for t in talks:
                if start <= t["date"] <= end:
                    t["seminar"] = name
                    t["default_time"] = default_time
                    results.append(t)
        except Exception as e:
            print(f"  ERROR parsing {name}: {e}")
            health.append((name, f"parser raised {type(e).__name__}: {e}"))
            continue

    LAST_RUN_HEALTH = health

    if health:
        print("\n  HEALTH CHECK — these seminars produced nothing:")
        for name, reason in health:
            print(f"    ! {name}: {reason}")
        print("    (An empty semester section is normal early on; a page whose"
              "\n     format changed looks exactly the same, so verify by eye.)")

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