#!/usr/bin/env bash
# Deploys one version of AirSight to production on the Mac (ADR 0014, issue #166).
#
# GitHub Actions runs this over SSH through Tailscale. The deploy key in ~/.ssh/authorized_keys
# can only run this script, so the SSH command is just its arguments:
#
#   ssh hammadhassan@airsight v0.8.0 <commit sha>   # a release
#   ssh hammadhassan@airsight main <commit sha>     # the latest main, for a test deploy
#
# It runs in the production checkout, a git worktree next to the development clone, so a
# deploy never touches the files you are working on. Steps: check out the exact commit CI
# built, pull its images from GHCR, run the database migrations, restart, then check the
# public front door. If the new version doesn't come up healthy, it goes back to the last one.
#
# Everything is inside main(), so bash has read the whole script before git checkout replaces
# this file with the new version's copy.
set -euo pipefail

main() {
  # SSH sessions get a bare PATH; Docker Desktop's CLI is in one of the first two
  export PATH="$HOME/.docker/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

  local repo="https://github.com/imhammad/airsight.git"
  local dir
  dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  cd "$dir"

  # The forced command puts the client's arguments in SSH_ORIGINAL_COMMAND; a direct run uses "$@"
  local args
  if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
    read -r -a args <<<"$SSH_ORIGINAL_COMMAND"
  else
    args=("$@")
  fi
  if [[ ${#args[@]} -ne 2 ]]; then
    fail "usage: deploy.sh <vX.Y.Z | main> <40-character commit sha>"
  fi
  local version="${args[0]}" sha="${args[1]}"
  [[ "$version" =~ ^(v[0-9]+\.[0-9]+\.[0-9]+|main)$ ]] || fail "not a release tag or main: $version"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || fail "not a full commit sha: $sha"

  # Docker over SSH: talk to Docker Desktop's socket directly, and use a config without the
  # macOS keychain helper, which an SSH session can't open. The images are public, so no login.
  export DOCKER_HOST="unix://$HOME/.docker/run/docker.sock"
  export DOCKER_CONFIG="$HOME/.docker-deploy"
  mkdir -p "$DOCKER_CONFIG"
  printf '{"cliPluginsExtraDirs": ["/Applications/Docker.app/Contents/Resources/cli-plugins"]}\n' \
    >"$DOCKER_CONFIG/config.json"

  local log="$HOME/Library/Logs/airsight-deploy.log"
  exec > >(tee -a "$log") 2>&1
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) deploying $version ($sha)"

  [[ -f .env.prod ]] || fail ".env.prod is missing in $dir"

  # What runs now, so a failed deploy can go back to it
  local prev_version="" prev_sha=""
  if [[ -f .deployed.env ]]; then
    prev_version="$(sed -n 's/^AIRSIGHT_VERSION=//p' .deployed.env)"
    prev_sha="$(sed -n 's/^AIRSIGHT_COMMIT=//p' .deployed.env)"
  fi

  # Exactly the commit CI built: fetch the ref and refuse if it has moved since
  local ref="refs/heads/main"
  [[ "$version" == main ]] || ref="refs/tags/$version"
  git fetch --quiet --force --no-tags "$repo" "$ref"
  [[ "$(git rev-parse 'FETCH_HEAD^{commit}')" == "$sha" ]] ||
    fail "$version is now at $(git rev-parse --short 'FETCH_HEAD^{commit}'), not ${sha:0:7}; nothing changed"

  if release "$version" "$sha"; then
    # The prod command reads this, so it always talks to what is running
    printf 'AIRSIGHT_VERSION=%s\nAIRSIGHT_COMMIT=%s\nAIRSIGHT_IMAGE_TAG=sha-%s\n' "$version" "$sha" "$sha" >.deployed.env
    echo "=== deployed $version"
    return 0
  fi

  if [[ -n "$prev_version" && -n "$prev_sha" ]]; then
    echo "=== $version is not healthy; going back to $prev_version"
    git fetch --quiet --force --no-tags "$repo" "$prev_sha" || true
    if release "$prev_version" "$prev_sha"; then
      fail "rolled back to $prev_version; see the log above for why $version failed"
    fi
    fail "the rollback to $prev_version failed too; check the stack on the Mac with: prod ps"
  fi
  fail "$version is not healthy and there is no earlier deploy to go back to"
}

# Check out one commit, pull its images, migrate, restart and check the front door
release() {
  local version="$1" sha="$2"
  git checkout --quiet --detach "$sha"
  # Images are tagged with the full commit sha, so a rollback gets exactly the old images
  export AIRSIGHT_IMAGE_TAG="sha-$sha"

  local compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod)
  # Only our own images; the database and tool images stay on what is already there.
  # A slow answer from GHCR fails the pull, so try three times before giving up.
  local try
  for try in 1 2 3; do
    "${compose[@]}" pull --quiet api worker beat exporter web && break
    [[ "$try" -lt 3 ]] || return 1
    echo "image pull failed (try $try of 3); trying again in 20 seconds"
    sleep 20
  done
  # Migrations only add, so the version still running keeps working while they apply
  "${compose[@]}" run --rm api python -c \
    "from airsight.core.config import get_settings; from airsight.core.db import upgrade_database; upgrade_database(get_settings().database_url)" ||
    return 1
  "${compose[@]}" up -d --wait --wait-timeout 300 --remove-orphans || return 1

  # The public path: Caddy, then the API. A release must also report its own version.
  local want='"status":"ok"' health=""
  [[ "$version" == main ]] || want="\"version\":\"${version#v}\""
  for _ in $(seq 1 20); do
    health="$(curl -fsS --max-time 5 http://127.0.0.1:8080/v1/health || true)"
    if [[ "$health" == *"$want"* ]]; then
      echo "health: $health"
      return 0
    fi
    sleep 3
  done
  echo "health check failed; last answer: ${health:-none}"
  return 1
}

fail() {
  echo "deploy failed: $*" >&2
  exit 1
}

main "$@"
exit $?
