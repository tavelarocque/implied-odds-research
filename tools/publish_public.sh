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
#   FORCE=1 bash tools/publish_public.sh  replace the public history (only after changing what gets filtered)
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
PRIVATE_EMAIL="$(git log -1 --format=%ae)"
git update-ref -d refs/remotes/pushed/main
git remote remove origin
PRIVATE_EMAIL="${PRIVATE_EMAIL:-$(git -C "$ROOT" config user.email)}"   # read from git, never written in this file
[ -n "$PRIVATE_EMAIL" ] || { echo "ABORT: could not determine the private email"; exit 1; }
printf 'Tave Larocque <%s> <%s>\n' "$PUBLIC_EMAIL" "$PRIVATE_EMAIL" > "$TMP/mailmap"
printf '%s==>[email removed]\n' "$PRIVATE_EMAIL" > "$TMP/replace"
"$FILTER" --force --quiet --mailmap "$TMP/mailmap" --replace-text "$TMP/replace" \
  --invert-paths --path HANDOFF.md --path scratch/ --path .vscode/ \
  --message-callback 'import re
return re.sub(rb"\n*Claude-Session: \S+\n?", b"\n", message)'

echo "checking the public copy..."
if git log --all --format='%an %ae %cn %ce%n%B' | grep -qiE 'claude\.ai/code/session'; then
  echo "ABORT: a session link is still present"; exit 1; fi
if git log --all -p --format='%an %ae %cn %ce%n%B' | grep -qiF "$PRIVATE_EMAIL"; then
  echo "ABORT: the private email is still present (metadata or file contents)"; exit 1; fi
if git log --all -p | grep -qE 'xai-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|BEGIN [A-Z ]*PRIVATE KEY'; then
  echo "ABORT: something that looks like a secret is in the history"; exit 1; fi
if git ls-tree -r --name-only HEAD | grep -qE '^(HANDOFF\.md|scratch/|\.vscode/|data/)'; then
  echo "ABORT: an excluded path is still present"; exit 1; fi
echo "ok: head $(git rev-parse --short HEAD), $(git rev-list --count HEAD) commits, $(git ls-tree -r --name-only HEAD | wc -l | tr -d ' ') files, author $(git log -1 --format='%an <%ae>')"

if [ "${DRY:-0}" = "1" ]; then echo "DRY=1: not pushing"; exit 0; fi
if [ "${FORCE:-0}" = "1" ]; then git push --force "$PUBLIC_URL" HEAD:main; else git push "$PUBLIC_URL" HEAD:main; fi
echo "published to $PUBLIC_URL"
