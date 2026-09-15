#!/usr/bin/env bash
# Deploy philippe to stolas.ts — bot + Postgres + pgweb, all from compose.yml.
# DB runs on the same host, so the bot reaches it over the compose network.
#
#   ./deploy.sh          full: ship code + forms, rebuild image, up -d
#   ./deploy.sh forms    fast: ship only examples/, restart bot (no rebuild)
#
# The bot token lives ONLY on the server (~/philippe/.env) and is never shipped,
# so deploying never clobbers it. Override host/dir with PHILIPPE_HOST / PHILIPPE_DIR.
set -euo pipefail
HOST=${PHILIPPE_HOST:-stolas.ts}
DIR=${PHILIPPE_DIR:-philippe}
cd "$(dirname "$0")"

# tar over ssh — rsync isn't installed in the editing container. Removed files
# aren't pruned on the remote (except examples, wiped below); rare and harmless.
ship() { tar -czf - "$@" | ssh "$HOST" "mkdir -p $DIR && tar -xzf - -C $DIR"; }

if [ "${1:-}" = forms ]; then
  ssh "$HOST" "rm -rf $DIR/examples"          # so deleted forms vanish too
  ship examples
  ssh "$HOST" "cd $DIR && docker compose restart bot"
  echo "forms updated on $HOST."
  exit 0
fi

ship src examples db pyproject.toml uv.lock README.md \
     Dockerfile compose.yml .env.example .dockerignore

# First deploy: seed .env from the example so compose's env_file exists.
ssh "$HOST" "cd $DIR && [ -f .env ] || cp .env.example .env"

# Refuse to start with the placeholder token (would crash-loop on Telegram).
if ssh "$HOST" "grep -q ABC-your-token-here $DIR/.env"; then
  echo ">> Set the new bot key first:"
  echo "   ssh $HOST \"cd $DIR && nano .env\"   # PHILIPPE_BOT_TOKEN=..."
  echo ">> then re-run: ./deploy.sh"
  exit 1
fi

ssh "$HOST" "cd $DIR && docker compose up -d --build"
echo "deployed to $HOST. logs: ssh $HOST 'cd $DIR && docker compose logs -f bot'"
