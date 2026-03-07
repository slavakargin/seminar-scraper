"""
post_to_wiki.py  –  format the upcoming talks as a DokuWiki table
                    and write it to the target page via XML-RPC.

Credentials are read from environment variables:
    WIKI_USER     DokuWiki username
    WIKI_PASS     DokuWiki password
"""

import os
import datetime
import xmlrpc.client

from config import WIKI_XMLRPC_URL, WIKI_TARGET_PAGE
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_wiki_table(talks):
    """
    Render a list of talk dicts as a DokuWiki table.
    Returns the full wiki markup string to be written to the target page.
    """
    today = datetime.date.today()
    week_end = today + datetime.timedelta(days=7)
    header = (
        f"===== Upcoming Seminars =====\n"
        f"//Week of {today.strftime('%B %-d')}–{week_end.strftime('%B %-d, %Y')}. "
        f"Updated automatically every Sunday.//"
        f"\n\n"
    )

    if not talks:
        return header + "No seminars scheduled this week.\n"

    # Table header
    table = "^ Date ^ Seminar ^ Speaker ^ Title ^\n"
    for t in talks:
        date_str = t["date"].strftime("%A, %b %-d")
        speaker = t["speaker"] or "TBA"
        if t.get("affiliation"):
            speaker += f" ({t['affiliation']})"
        title = t["title"] or "TBA"
        # Link title back to the seminar page
        title_cell = f"[[{t['url']}|{title}]]" if t.get("url") else title
        seminar = t.get("seminar", "")
        table += f"| {date_str} | {seminar} | {speaker} | {title_cell} |\n"

    return header + table + "\n"


# ---------------------------------------------------------------------------
# Writing to DokuWiki
# ---------------------------------------------------------------------------

def post_to_wiki(markup):
    """
    Write markup to WIKI_TARGET_PAGE using DokuWiki's XML-RPC API.
    Credentials come from environment variables WIKI_USER and WIKI_PASS.
    """
    user = os.environ.get("WIKI_USER")
    password = os.environ.get("WIKI_PASS")
    if not user or not password:
        raise EnvironmentError("WIKI_USER and WIKI_PASS environment variables must be set.")

    server = xmlrpc.client.ServerProxy(WIKI_XMLRPC_URL)

    # Log in and get an auth token
    token = server.dokuwiki.login(user, password)
    if not token:
        raise PermissionError("DokuWiki login failed – check WIKI_USER / WIKI_PASS.")

    # Write the page (summary shown in page history)
    summary = f"Auto-update: upcoming seminars {datetime.date.today().isoformat()}"
    server.wiki.putPage(WIKI_TARGET_PAGE, markup, {"sum": summary, "minor": False})
    print(f"  Posted to wiki page '{WIKI_TARGET_PAGE}'.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Allow testing the formatter without touching the wiki:
    # python post_to_wiki.py --dry-run
    import sys
    from scrape import get_upcoming_talks

    talks = get_upcoming_talks()
    markup = format_wiki_table(talks)

    if "--dry-run" in sys.argv:
        print("=== DRY RUN – markup that would be posted ===")
        print(markup)
    else:
        post_to_wiki(markup)
