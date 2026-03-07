# Seminar pages to scrape
SEMINARS = [
    {"name": "Colloquium",          "url": "https://www2.math.binghamton.edu/p/seminars/colloquium"},
    {"name": "Algebra",             "url": "https://www2.math.binghamton.edu/p/seminars/alge"},
    {"name": "Analysis",            "url": "https://www2.math.binghamton.edu/p/seminars/anal"},
    {"name": "Arithmetic",          "url": "https://www2.math.binghamton.edu/p/seminars/arit"},
    {"name": "Combinatorics",       "url": "https://www2.math.binghamton.edu/p/seminars/comb/start"},
    {"name": "Data Science",        "url": "https://www2.math.binghamton.edu/p/seminars/datasci"},
    {"name": "Geometry/Topology",   "url": "https://www2.math.binghamton.edu/p/seminars/topsem"},
    {"name": "Statistics",          "url": "https://www2.math.binghamton.edu/p/seminars/stat"},
]

# DokuWiki XML-RPC endpoint
WIKI_XMLRPC_URL = "https://www2.math.binghamton.edu/lib/exe/xmlrpc.php"

# The wiki page that will be updated with the weekly table.
# This should be a small dedicated page that gets included on the front page
# via {{page>seminars:weekly_talks}} or similar.
WIKI_TARGET_PAGE = "seminars:weekly_talks"

# How many days ahead to include (7 = the coming week when run on Sunday)
LOOKAHEAD_DAYS = 7
