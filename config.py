# How far ahead the web table looks (the version embedded on the wiki).
LOOKAHEAD_DAYS = 7

# How far ahead the hallway-TV image looks.  People walk past the screen and
# glance at it, so a longer horizon is more useful there than on the wiki.
TV_LOOKAHEAD_DAYS = 14

# "room" is shown on the TV image when known.  The values below were taken
# from the seminar pages themselves; the blank ones are simply unconfirmed —
# fill them in and they appear automatically.
SEMINARS = [
    {"name": "Algebra",           "url": "https://www2.math.binghamton.edu/p/seminars/alge",       "time": "Tue 2:45",  "room": "WH-100E"},
    {"name": "Analysis",          "url": "https://www2.math.binghamton.edu/p/seminars/anal",       "time": "Wed 4:00",  "room": "WH-100E"},
    {"name": "Arithmetic",        "url": "https://www2.math.binghamton.edu/p/seminars/arit",       "time": "Tue 4:00",  "room": ""},
    {"name": "Combinatorics",     "url": "https://www2.math.binghamton.edu/p/seminars/comb/start", "time": "Tue 1:30",  "room": "WH-100E"},
    {"name": "Data Science",      "url": "https://www2.math.binghamton.edu/p/seminars/datasci",    "time": "Tue 12:15", "room": ""},
    {"name": "Geometry/Topology", "url": "https://www2.math.binghamton.edu/p/seminars/topsem",     "time": "Thu 2:45",  "room": ""},
    {"name": "Statistics",        "url": "https://www2.math.binghamton.edu/p/seminars/stat",       "time": "Thu 1:30",  "room": "WH-100E"},
    # Not active this semester:
    # {"name": "Colloquium",      "url": "https://www2.math.binghamton.edu/p/seminars/colloq",     "time": "Thu 4:00",  "room": ""},
]
