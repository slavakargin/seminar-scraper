# seminar-scraper

Scrapes the department seminar pages and posts a table of upcoming
talks to the DokuWiki front page every Sunday via GitHub Actions.

## How it works

1. `scrape.py` fetches each seminar page, parses the current semester's
   talk list, and filters to talks in the next 7 days.
2. `post_to_wiki.py` formats the results as a DokuWiki table and writes
   it to the page `seminars:weekly_talks` via DokuWiki's XML-RPC API.
3. The front page includes that page with `{{page>seminars:weekly_talks}}`.
4. A GitHub Actions cron job runs the script every Sunday at 8 AM UTC.

## Setup

### 1. GitHub repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `WIKI_USER` | Your DokuWiki username |
| `WIKI_PASS` | Your DokuWiki password |

### 2. DokuWiki XML-RPC

Make sure XML-RPC is enabled on the wiki:
**Admin → Configuration Settings → Advanced → Remote API (XML-RPC)** → enable.

### 3. Front page include

Add this line to the front page (`start`) where you want the table to appear:

```
{{page>seminars:weekly_talks}}
```

The page `seminars:weekly_talks` will be created automatically on the
first run. You can also create it manually as a placeholder.

### 4. Running locally

```bash
pip install -r requirements.txt

# Dry run (prints the wiki markup without posting):
python post_to_wiki.py --dry-run

# Live run (posts to the wiki):
WIKI_USER=youruser WIKI_PASS=yourpass python post_to_wiki.py
```

## Adding parsers for remaining seminars

`scrape.py` has parsers for Algebra, Analysis, and Geometry/Topology.
The remaining seminars (Colloquium, Arithmetic, Combinatorics, Data Science,
Statistics) have stubs. To add a parser:

1. Check the page format by viewing the wiki source.
2. Write a `parse_X(soup, url)` function following the existing examples.
3. Add it to the `PARSERS` dict in `scrape.py`.
4. Add the seminar URL to `SEMINARS` in `config.py` (already listed).
