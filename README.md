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
3. A GitHub Actions workflow deploys `docs/` to the `gh-pages` branch
   nightly, making the table available at
   `https://slavakargin.github.io/seminar-scraper/`.
4. The wiki front page embeds this URL with DokuWiki's iframe plugin:
   `{{url>https://slavakargin.github.io/seminar-scraper/ 250px}}`.

## Supported seminars

| Seminar | Day & Time | Page format |
|---------|-----------|-------------|
| Algebra | Tue 2:45 | Positional list items |
| Analysis | Wed 4:00 | Labeled fields (Speaker/Topic) |
| Arithmetic | Tue 4:00 | Bold-italic labeled fields |
| Combinatorics | Tue 1:30 | Dash-list with labeled fields, M/D dates |
| Data Science | Tue 12:15 | Italic-labeled fields, full dates |
| Geometry/Topology | Thu 2:45 | Inline labels, handles special events |
| Statistics | Thu 1:30 | Bold-italic labeled fields |

Each seminar page uses a different DokuWiki markup format, so each has
its own parser in `scrape.py`.

## Setup

### 1. Enable GitHub Pages

Go to **Settings → Pages**, set source to **Deploy from a branch**,
select **`gh-pages`** / **`/ (root)`**.

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

## Adding or fixing a parser

Each DokuWiki seminar page uses a distinct markup format. To add or
fix a parser:

1. View the wiki page source to understand the markup structure.
2. Run `python scrape.py --debug` to see how text is being split.
3. Write or update the `parse_X(soup, url)` function in `scrape.py`.
4. Add the seminar to `SEMINARS` in `config.py` with its URL and
   default time.
5. Add the parser to the `PARSERS` dict in `scrape.py`.