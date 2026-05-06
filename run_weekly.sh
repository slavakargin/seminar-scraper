#!/bin/bash
set -e

cd "$(dirname "$0")"

# Pull any changes from the laptop
git pull --rebase

# Build the HTML
/opt/anaconda3/bin/python3 build_html.py

# Commit and push only if docs/index.html changed
if ! git diff --quiet docs/index.html; then
    git add docs/index.html
    git commit -m "Update seminar table $(date +%Y-%m-%d)"
    git push
else
    echo "No changes."
fi