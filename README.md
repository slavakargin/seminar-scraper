# seminar-scraper

Scrapes the Binghamton Math department seminar pages and publishes a
styled HTML table of upcoming talks to GitHub Pages. The table is
embedded on the department wiki front page via an iframe.

## How it works

1. `scrape.py` fetches each seminar page from the department DokuWiki,
   parses the current semester's talk list, and filters to talks in
   the next 7 days.
2. `build_html.py` generates a styled HTML table and writes it to
   `docs/index.html`.
3. The GitHub Actions workflow `.github/workflows/weekly.yml` runs this
   nightly (08:00 UTC) and commits the regenerated `docs/index.html`
   back to `main`. GitHub Pages serves `main` / `docs`, so the table is
   live at `https://slavakargin.github.io/seminar-scraper/`.
4. The wiki front page embeds this URL with DokuWiki's iframe plugin:
   `{{url>https://slavakargin.github.io/seminar-scraper/ 250px}}`.

Nothing runs on a personal machine — see "History" below.

## Supported seminars

| Seminar | Day & Time | Page format |
|---------|-----------|-------------|
| Algebra | Tue 2:45 | Positional list items, month-name dates |
| Analysis | Wed 4:00 | Labeled fields (Speaker/Topic), month-name dates |
| Arithmetic | Tue 4:00 | Bold-italic labeled fields |
| Combinatorics | Tue 1:30 | Dash-list with labeled fields, M/D dates |
| Data Science | Tue 12:15 | Italic-labeled fields, full dates |
| Geometry/Topology | Thu 2:45 | Inline labels, M/D/YYYY dates, special events |
| Statistics | Thu 1:30 | Bold-italic labeled fields |

Each seminar page uses a different DokuWiki markup format, so each has
its own parser in `scrape.py`.  Organizers also edit these pages by hand,
so a format can change without warning — see "Health check" below.

## Health check

When a page's markup changes, its parser quietly returns nothing and the
seminar simply stops appearing in the table.  To make that visible,
`scrape.py` prints a warning for every seminar that yielded zero talks
for the whole current semester, e.g.:

```
  HEALTH CHECK — these seminars produced nothing:
    ! Statistics: 0 talks parsed from the Fall 2026 section
```

An empty section is normal at the start of a semester, but a seminar
that was working and suddenly reports zero usually means its parser
needs updating.  Run `python scrape.py --debug` to see where parsing
stops.

## Setup

### 1. Enable GitHub Pages

Go to **Settings → Pages**, set source to **Deploy from a branch**,
select **`main`** / **`/docs`**.

Settings → Actions → General → Workflow permissions must be
**Read and write**, otherwise the nightly job cannot push the updated
table.

### 2. Running locally

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# See what the scraper finds:
python scrape.py

# With debug output:
python scrape.py --debug

# Build the HTML page locally:
python build_html.py
# Output: docs/index.html
```

### 3. Manual workflow trigger

Go to **Actions → Daily seminar update → Run workflow**.

## Files

| File | Purpose |
|------|---------|
| `config.py` | Seminar URLs, default times, lookahead window |
| `scrape.py` | Page fetching and per-seminar parsers |
| `build_html.py` | Generates `docs/index.html` from scraped data |
| `template.html` | HTML/CSS template for the output page |
| `post_to_wiki.py` | Posts to wiki via XML-RPC (requires admin to enable) |
| `.github/workflows/weekly.yml` | GitHub Actions workflow (runs nightly) |
| `run_weekly.sh`, `*.plist` | Dormant local fallback, see "History" |

## History: the local-Mac detour

From May to August 2026 the department site was not reachable from
outside the campus network, so the GitHub Actions schedule was disabled
and the job ran from a Mac instead (`run_weekly.sh` driven by
`edu.binghamton.seminar-scraper.plist` via launchd), pushing the result
to `main`.

The site is publicly reachable again, so the nightly build is back on
GitHub Actions.  `run_weekly.sh` and the plist are kept in the repo as a
fallback but are **not** installed; running both at once would make the
two jobs race on `main`.  To take the launchd job off a Mac:

```
launchctl unload ~/Library/LaunchAgents/edu.binghamton.seminar-scraper.plist
rm ~/Library/LaunchAgents/edu.binghamton.seminar-scraper.plist
```

If campus ever firewalls the site again, re-enable it by reversing those
steps and commenting out the `schedule:` block in `weekly.yml`.

## Robustness

If a seminar page cannot be fetched at all and no talks are found,
`build_html.py` exits non-zero **without** rewriting `docs/index.html`,
so a network failure leaves yesterday's table up instead of publishing
an empty "No seminars scheduled this week".

## Adding or fixing a parser

Each DokuWiki seminar page uses a distinct markup format. To add or
fix a parser:

1. View the wiki page source to understand the markup structure.
2. Run `python scrape.py --debug` to see how text is being split.
3. Write or update the `parse_X(soup, url)` function in `scrape.py`.
4. Add the seminar to `SEMINARS` in `config.py` with its URL and
   default time.
5. Add the parser to the `PARSERS` dict in `scrape.py`.