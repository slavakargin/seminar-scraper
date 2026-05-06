#!/bin/bash
set -e

cd "$(dirname "$0")"

# Pull any changes from the laptop
git pull --rebase

# Build the HTML
/opt/anaconda3/bin/python3 build_html.py

# Stage the file (creates it in the index if new), then check the staged diff
git add docs/index.html
if ! git diff --cached --quiet docs/index.html; then
    git commit -m "Update seminar table $(date +%Y-%m-%d)"
    git push
else
    echo "No changes."
fi