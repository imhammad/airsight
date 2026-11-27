# Deploying AirSight

How production runs, how to set it up from scratch, and how to operate it. The decision behind
this setup is [ADR 0014](adr/0014-production-hosting.md). What to do when something breaks is in
the [runbook](RUNBOOK.md).

Live: <https://airsight.tailbcc5c4.ts.net>

## How production works

~~~text
visitor ──HTTPS──▶ Tailscale Funnel ──▶ Caddy (127.0.0.1:8080) ──▶ web app files
                   (TLS, public name)         │
                                              └── /v1, /docs ──▶ API ──▶ TimescaleDB, Redis
                                                                 worker + beat (jobs), MLflow
release tag ──▶ GitHub Actions ──▶ images on GHCR
                       │
                       └──▶ joins the tailnet as tag:ci ──SSH──▶ scripts/deploy.sh on the Mac
backup service ──pg_dump daily──▶ iCloud Drive
~~~

- **The server is a Mac** (Apple Silicon) running Docker Desktop. It costs nothing, but the site
  is only up while the Mac is awake and online. The uptime monitor records that honestly.
- **Tailscale Funnel** gives the site a public HTTPS address and handles TLS. Nothing on the Mac
  listens on a public port: Caddy is bound to `127.0.0.1:8080`, and Funnel forwards to it.
- **Caddy** serves the built web app and passes `/v1` and the API docs to the API. It never
  passes `/metrics`. Grafana (3001), MLflow (5002), Prometheus (9091) and Alertmanager (9094)
  listen only on `127.0.0.1`, so they can be opened on the Mac and nowhere else.
- **`docker-compose.prod.yml`** layers production settings over `docker-compose.yml`: its own
  Compose project (`airsight-prod`, own volumes), restart policies, memory limits, secrets from
  `.env.prod`, and the images CI built instead of local builds.
- **Releases deploy themselves.** A push to `main` builds multi-arch images and pushes them to
  GHCR, tagged with the commit sha. A release tag (`vX.Y.Z`) also deploys: the runner joins the
  tailnet as a throwaway `tag:ci` machine that may only reach the Mac's SSH port, and its key can
  only run `scripts/deploy.sh`. That script checks out the exact commit in a separate checkout,
  pulls its images, migrates, restarts, checks the health page, and rolls back if it fails.
- **Backups** run daily in their own service and are copied to iCloud Drive
  ([runbook](RUNBOOK.md#backups)).

Two folders on the Mac, side by side:

| Folder | What it is |
|---|---|
| `AirSight_Project/airsight` | the development clone you work in |
| `AirSight_Project/airsight-prod` | the production checkout (a git worktree), managed by `deploy.sh`; holds `.env.prod` and `.deployed.env` |

## Set up production from scratch

Every command runs in a terminal on the Mac, in the development clone, unless a step says
otherwise. The commands use this project's names (user `hammadhassan`, repo `imhammad/airsight`,
tailnet `tailbcc5c4.ts.net`); change them for your own copy.

### 1. Prerequisites

- macOS on Apple Silicon, [Docker Desktop](https://www.docker.com/products/docker-desktop/),
  git, and the [GitHub CLI](https://cli.github.com/) signed in (`gh auth status`).
- iCloud Drive turned on (System Settings → your name → iCloud → iCloud Drive).
- The repo cloned to `/Users/Professional_Projects/AirSight_Project/airsight`, with `.env`
  holding the API keys (see `.env.example`).

### 2. Keep the Mac awake on the charger

A sleeping Mac takes the site offline, and a MacBook always sleeps when its lid closes. Keep the
lid open and the charger in, and stop the Mac sleeping on the charger while the screen can turn
off:

~~~bash
sudo pmset -c sleep 0 displaysleep 10 powernap 0
pmset -g custom | sed -n '/AC Power/,$p' | grep -E '^ (sleep|displaysleep|powernap) '
~~~

Lock the screen with Control + Command + Q when you leave; locking doesn't stop the site.

### 3. Tailscale

1. Install Tailscale from <https://tailscale.com/download/mac> and sign in (this project uses a
   GitHub login).
2. In the [admin console](https://login.tailscale.com/admin/machines), rename the Mac to
   `airsight` (machine menu → **Edit machine name**).
3. On the [DNS page](https://login.tailscale.com/admin/dns), turn on **MagicDNS** and
   **HTTPS Certificates**.
4. Add a shell shortcut for the command-line tool that ships inside the app:

   ~~~bash
   echo "alias tailscale=/Applications/Tailscale.app/Contents/MacOS/Tailscale" >> ~/.zshrc
   ~~~

   Then open a new terminal, so the shortcut is loaded.

### 4. The production checkout and its secrets

~~~bash
git worktree add --detach ../airsight-prod main
ln -s ../airsight/.env ../airsight-prod/.env
cd ../airsight-prod
cp .env.prod.example .env.prod
sed -i '' "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env.prod
sed -i '' "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)/" .env.prod
mkdir -p "$HOME/Library/Mobile Documents/com~apple~CloudDocs/AirSight Backups"
grep -c '=..' .env.prod
cd ../airsight
~~~

`grep -c` prints `4`: both passwords, `BACKUP_DIR` and `BACKUP_KEEP` are set. Save the Grafana
password in your password manager. `.env.prod` is in `.gitignore` and must never be committed.

Then add the `prod` command, which runs Compose in the production checkout on whatever is
deployed:

~~~bash
cat >> ~/.zshrc <<'EOF'
# AirSight production (ADR 0014): Compose in the production checkout, on what is deployed
prod() {
  (cd /Users/Professional_Projects/AirSight_Project/airsight-prod &&
    docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod --env-file .deployed.env "$@")
}
EOF
~~~

Open a new terminal afterwards. If an older `prod` alias exists, delete its line from
`~/.zshrc` first: an alias left in an open shell wins over the function (see the
[engineering log](engineering-log.md)).

### 5. Check that Docker may write to iCloud Drive

~~~bash
docker run --rm --entrypoint touch -v "$HOME/Library/Mobile Documents/com~apple~CloudDocs/AirSight Backups:/backups" timescale/timescaledb-ha:pg17 /backups/.docker-write-test && rm "$HOME/Library/Mobile Documents/com~apple~CloudDocs/AirSight Backups/.docker-write-test" && echo "Docker can write backups"
~~~

If macOS asks whether Docker may access iCloud Drive, allow it. If it fails with
`Operation not permitted`, turn on iCloud Drive for Docker in System Settings → Privacy &
Security → Files & Folders.

### 6. Images

Images are built by the **Images and deploy** workflow on every push to `main`. GitHub makes new
packages private, and the Mac pulls without logging in, so after the first run make both public:
<https://github.com/users/imhammad/packages/container/airsight-backend/settings> and
`…/airsight-web/settings`, **Danger Zone** → **Change visibility** → **Public**. Check:

~~~bash
for i in airsight-backend airsight-web; do DOCKER_CONFIG="$(mktemp -d)" docker manifest inspect "ghcr.io/imhammad/${i}:sha-$(git rev-parse origin/main)" >/dev/null && echo "${i} public"; done
~~~

### 7. Data

Production starts with whatever is in its volumes. Pick one:

- **From a backup** (moving to a new Mac): deploy once (step 9), then follow
  [Restore the database](RUNBOOK.md#restore-the-database) with the newest dump from iCloud Drive.
- **From the development stack** (how this project first went live): stop development, copy its
  volumes into the production ones, then give the copied database the production password.
  `prod` needs `.deployed.env`, which the first deploy normally writes, so the first line creates
  it by hand for this one-off copy.

  ~~~bash
  printf 'AIRSIGHT_IMAGE_TAG=sha-%s\n' "$(git rev-parse origin/main)" > ../airsight-prod/.deployed.env
  docker compose stop
  prod create db mlflow prometheus
  for v in db-data mlflow-data prometheus-data; do docker run --rm -v "airsight_${v}:/from:ro" -v "airsight-prod_${v}:/to" alpine sh -c 'cp -a /from/. /to/' && echo "copied ${v}"; done
  prod up -d --wait db
  PW=$(grep '^POSTGRES_PASSWORD=' ../airsight-prod/.env.prod | cut -d= -f2); printf "ALTER USER airsight PASSWORD '%s';\n" "$PW" | prod exec -T db psql -U airsight -d airsight; unset PW
  docker compose down
  ~~~

Afterwards, run only the database from the development stack (`docker compose up -d --wait db`)
for tests. A full development stack would run the ingestion jobs a second time and spend the
PurpleAir points twice.

The backups cover the database only. The registered models live in MLflow's volume, which is
copied in the second option but not backed up yet.

### 8. SSH for deploys

1. System Settings → General → **Sharing** → turn on **Remote Login**. In its (i) panel, allow
   **Only these users** (just you), and leave **Allow full disk access for remote users** off.
2. Create the host keys (macOS only makes them on the first connection), turn password logins
   off, and check:

   ~~~bash
   sudo ssh-keygen -A
   printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nAllowUsers hammadhassan\n' | sudo tee /etc/ssh/sshd_config.d/010-airsight.conf >/dev/null
   sudo sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|allowusers) '
   ~~~

   Expected: `passwordauthentication no`, `kbdinteractiveauthentication no`,
   `allowusers hammadhassan`.
3. Create the deploy key. `restrict` blocks shells, tunnels and forwarding; the key can only run
   the deploy script.

   ~~~bash
   ssh-keygen -t ed25519 -N "" -C airsight-deploy -f ~/.ssh/airsight_deploy
   printf 'restrict,command="/Users/Professional_Projects/AirSight_Project/airsight-prod/scripts/deploy.sh" %s\n' "$(cat ~/.ssh/airsight_deploy.pub)" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ~~~

### 9. First deploy, from the Mac itself

Deploying locally first separates Mac problems from GitHub or Tailscale problems.

~~~bash
ssh -i ~/.ssh/airsight_deploy -o IdentitiesOnly=yes hammadhassan@localhost main "$(git rev-parse origin/main)"
prod ps --format '{{.Service}} {{.Status}}' | sort
~~~

It ends with `=== deployed main`, and all 12 services are `Up`, with health checks passing.

### 10. Go public

~~~bash
tailscale funnel --bg 8080
curl -s https://airsight.tailbcc5c4.ts.net/v1/health; echo
~~~

The first time, Funnel prints a link to allow Funnel for the tailnet; open it, approve, and run
the command again.

### 11. Automatic deploys from GitHub

1. **Tailscale access rules** ([policy file](https://login.tailscale.com/admin/acls/file)). The
   runner gets its own tag, which may reach only port 22 on the Mac. The `tests` block makes
   Tailscale refuse any later edit that would let it reach more.

   ~~~json
   {
     "tagOwners": {"tag:ci": ["autogroup:admin"]},
     "hosts": {"airsight": "100.126.10.72"},
     "grants": [
       {"src": ["autogroup:member"], "dst": ["*"], "ip": ["*"]},
       {"src": ["tag:ci"], "dst": ["airsight"], "ip": ["tcp:22"]}
     ],
     "ssh": [{"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}],
     "nodeAttrs": [{"target": ["autogroup:member"], "attr": ["funnel"]}],
     "tests": [{"src": "tag:ci", "accept": ["airsight:22"], "deny": ["airsight:443", "airsight:8080"]}]
   }
   ~~~

   Use the Mac's own Tailscale address in `hosts` (`tailscale ip -4`).
2. **A credential for GitHub** ([Trust credentials](https://login.tailscale.com/admin/settings/trust-credentials)):
   **+ Credential** → **OAuth** → tick **Write** on **Auth Keys** (not OAuth Keys) → choose
   `tag:ci` in the Tags box that appears → **Generate credential**. Copy the Client ID and the
   secret; the secret is shown once.
3. **The GitHub environment and its secrets:**

   ~~~bash
   gh api -X PUT repos/imhammad/airsight/environments/production -F "deployment_branch_policy[protected_branches]=false" -F "deployment_branch_policy[custom_branch_policies]=true" --jq .name
   gh api -X POST repos/imhammad/airsight/environments/production/deployment-branch-policies -f name=main -f type=branch --jq .name
   gh api -X POST repos/imhammad/airsight/environments/production/deployment-branch-policies -f name='v*.*.*' -f type=tag --jq .name
   gh secret set TS_OAUTH_CLIENT_ID --env production
   gh secret set TS_OAUTH_SECRET --env production
   gh secret set DEPLOY_SSH_KEY --env production < ~/.ssh/airsight_deploy
   printf 'airsight.tailbcc5c4.ts.net %s\n' "$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)" | gh secret set DEPLOY_KNOWN_HOSTS --env production
   rm ~/.ssh/airsight_deploy
   ~~~

   The two `TS_` commands ask for the values from the credential. The private key is deleted
   because only GitHub needs it.
4. **Test it:**

   ~~~bash
   run="$(gh workflow run deploy.yml --ref main 2>&1 | grep -oE 'runs/[0-9]+' | cut -d/ -f2)" && gh run watch "$run" --exit-status
   ~~~

### 12. Uptime monitoring

An outside check that tells anyone whether the site is up: a free
[UptimeRobot](https://uptimerobot.com) HTTP(S) monitor on
`https://airsight.tailbcc5c4.ts.net/v1/health` every 5 minutes, with a public status page.

### 13. Alerts on your phone

Alertmanager sends every alert, and its all-clear, to Telegram through a bot of your own.

1. In Telegram, open a chat with **@BotFather**, send `/newbot`, name it `AirSight alerts`, and
   give it a username ending in `bot`. BotFather replies with the bot's token. Treat it like a
   password.
2. Open your bot's chat (search for its username), press **Start** and send it any message. A
   bot can only write to people who wrote to it first.
3. Run this line on its own and paste the whole token at the prompt, the numbers before the
   colon included. `read -rs` keeps it off the screen and out of your shell history. Run it
   alone: pasted together with the next block, `read` would take the next line as the token.

   ~~~bash
   read -rs "token?Bot token: "; echo
   ~~~

4. Check the token, find your chat id and save both:

   ~~~bash
   curl -s "https://api.telegram.org/bot${token}/getMe" | python3 -c 'import json,sys; r=json.load(sys.stdin); print("token ok:", r["ok"], r.get("result", {}).get("username", r.get("description")))'
   chat="$(curl -s "https://api.telegram.org/bot${token}/getUpdates" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"][-1]["message"]["chat"]["id"])')"
   echo "chat id: ${chat}"
   env_prod=../airsight-prod/.env.prod
   updated="$(grep -v '^TELEGRAM_' "$env_prod"; printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$token" "$chat")"
   printf '%s\n' "$updated" > "$env_prod"
   unset token updated
   grep -c '^TELEGRAM_[A-Z_]*=..' ../airsight-prod/.env.prod
   ~~~

   It prints `token ok: True` with the bot's username, the chat id, then `2`. `token ok: False`
   means the token was copied incompletely. An `IndexError` means the bot has no message from
   you yet: send it one and run this block again (redo step 3 first, since the block clears the
   token). Set both before the next deploy: every `prod` command refuses to run without them.
5. After a deploy, send a test alert. It arrives within a minute, and an all-clear about five
   minutes later:

   ~~~bash
   prod exec alertmanager amtool alert add AirSightTest severity=info --annotation='summary="Test alert from the deployment guide"' --alertmanager.url=http://localhost:9093
   ~~~

## Operating production

| Task | Command |
|---|---|
| See what runs | `prod ps` |
| Follow a service's logs | `prod logs -f api` |
| Restart a service | `prod restart worker`, then `prod up -d --wait worker` |
| What is deployed | `cat ../airsight-prod/.deployed.env` |
| Deploy logs on the Mac | `tail -50 ~/Library/Logs/airsight-deploy.log` |
| Dashboards | Grafana at <http://localhost:3001>, MLflow at <http://localhost:5002> |
| Backups | [runbook: Backups](RUNBOOK.md#backups) |

**Release:** the usual release steps end with pushing the tag (`git push origin vX.Y.Z`), and
the tag deploys itself. Watch it with `gh run watch` and check the version:
`curl -s https://airsight.tailbcc5c4.ts.net/v1/health`.

**Deploy `main` without a release** (to try something on production):
`gh workflow run deploy.yml --ref main`.

**Roll back:** if a deploy fails its health check, `deploy.sh` puts the previous version back on
its own and the run goes red. To go back to an earlier release by hand, deploy its tag:
`gh workflow run deploy.yml --ref v0.8.0`. This works for v0.8.0 and later, which contain the
workflow. Migrations only add tables and columns, so older code keeps working on a newer schema.

**Take the site offline** (for example, before moving the Mac): `tailscale funnel --https=443 off`.
Bring it back with `tailscale funnel --bg 8080`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The site doesn't load, but `curl localhost:8080/v1/health` works | Funnel is off or the Mac lost its network. `tailscale funnel status`; start it with `tailscale funnel --bg 8080`. |
| `prod` says `couldn't find env file` | An old `prod` alias is still loaded. Delete it from `~/.zshrc` and open a new terminal. |
| `prod` says `required variable AIRSIGHT_IMAGE_TAG is missing` | Nothing has been deployed yet, so `.deployed.env` is missing. Run the first deploy (step 9). |
| The deploy run fails at the Tailscale step with `requested tags [tag:ci] are invalid` | The credential lacks the Auth Keys write scope or the `tag:ci` tag, or the tag is missing from `tagOwners`. |
| The deploy run fails at SSH with `Host key verification failed` | The Mac's host key changed. Set `DEPLOY_KNOWN_HOSTS` again (step 11.3). |
| `sshd -T` prints `no hostkeys available` | macOS hasn't made host keys yet: `sudo ssh-keygen -A`. |
| `deploy failed: main is now at …` | Something was pushed to `main` after the run started. Run the deploy again. |
| `backup` is unhealthy | The newest backup is over 26 hours old. See [runbook: Backups](RUNBOOK.md#backups). |
| `zsh: bad substitution` in a command | zsh reads `$name:x` as a modifier. Write `${name}:x`. |

Every problem met while building this is in the [engineering log](engineering-log.md).
