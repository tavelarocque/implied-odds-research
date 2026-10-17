#!/usr/bin/env bash
# Publish a filtered copy of main to the public repository (implied-odds-research).
#
# The private repo keeps running everything. This builds a throwaway clone of main, rewrites it so the public copy has
#   - the owner's email replaced by GitHub's noreply address (dates and messages otherwise unchanged),
#   - no HANDOFF.md (operations manual), scratch/ or .vscode/, in any commit,
#   - no Claude-Session lines in commit messages,
# scans the result for secrets and the private email, and pushes it. The rewrite is deterministic, so later runs only
# add the new commits (a normal fast-forward push). The data branch is never published.
#
#   bash tools/publish_public.sh          build, check and push
#   DRY=1 bash tools/publish_public.sh    build and check only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_URL="${PUBLIC_URL:-https://github.com/tavelarocque/implied-odds-research.git}"
PUBLIC_EMAIL="${PUBLIC_EMAIL:-269324844+tavelarocque@users.noreply.github.com}"   # GitHub noreply (user id 269324844, from api.github.com/users/tavelarocque)
FILTER="$ROOT/.venv/bin/git-filter-repo"
[ -x "$FILTER" ] || { echo "installing git-filter-repo into .venv"; "$ROOT/.venv/bin/pip" install --quiet git-filter-repo; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git -C "$ROOT" fetch --quiet origin main
git clone --quiet --no-local --single-branch --branch main "$ROOT" "$TMP/repo"
cd "$TMP/repo"
git fetch --quiet "$ROOT" "+refs/remotes/origin/main:refs/remotes/pushed/main"   # publish only what is pushed to GitHub
git reset --quiet --hard pushed/main
git update-ref -d refs/remotes/pushed/main
git remote remove origin
printf 'Tave Larocque <%s> <[email removed]>\n' "$PUBLIC_EMAIL" > "$TMP/mailmap"
"$FILTER" --force --quiet --mailmap "$TMP/mailmap" \
  --invert-paths --path HANDOFF.md --path scratch/ --path .vscode/ \
  --message-callback 'import re
return re.sub(rb"\n*Claude-Session: \S+\n?", b"\n", message)'

echo "checking the public copy..."
if git log --all --format='%an %ae %cn %ce%n%B' | grep -qiE '[removed]|[removed]\.com|claude\.ai/code/session'; then
  echo "ABORT: private email or session link still present"; exit 1; fi
if git log --all -p | grep -qE 'xai-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|BEGIN [A-Z ]*PRIVATE KEY'; then
  echo "ABORT: something that looks like a secret is in the history"; exit 1; fi
if git ls-tree -r --name-only HEAD | grep -qE '^(HANDOFF\.md|scratch/|\.vscode/|data/)'; then
  echo "ABORT: an excluded path is still present"; exit 1; fi
echo "ok: head $(git rev-parse --short HEAD), $(git rev-list --count HEAD) commits, $(git ls-tree -r --name-only HEAD | wc -l | tr -d ' ') files, author $(git log -1 --format='%an <%ae>')"

if [ "${DRY:-0}" = "1" ]; then echo "DRY=1: not pushing"; exit 0; fi
git push "$PUBLIC_URL" HEAD:main
echo "published to $PUBLIC_URL"
