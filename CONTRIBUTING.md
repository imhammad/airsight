# Contributing to AirSight

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 for you)
- Node.js 24 (see `web/.nvmrc`)
- pre-commit: `uv tool install pre-commit`

## Setup

```bash
git clone https://github.com/imhammad/airsight.git
cd airsight
pre-commit install
cp .env.example .env        # then add your own API keys; .env is never committed
(cd backend && uv sync)
(cd web && npm ci)
```

## Running

| What | Command |
|---|---|
| Database only, for tests | `docker compose up -d --wait db` |
| Whole stack (not on the production Mac) | `docker compose up -d --build --wait` |
| API with auto-reload | `cd backend && uv run uvicorn airsight.api.main:app --reload` |
| Web dev server | `cd web && npm run dev` |

On the Mac that runs production, start only the database: a whole development stack would run
the ingestion jobs a second time and spend the PurpleAir points twice.

## Checks (the same ones CI runs)

```bash
pre-commit run --all-files                    # formatting, lint, types, file hygiene
(cd backend && uv run pytest)                 # backend tests
(cd web && npm run lint && npm test && npm run build)
(cd web && npm run e2e && npm run lighthouse)  # browser tests; once first: npx playwright install chromium
```

## Workflow

1. **Issue first.** Every change starts as an issue with context and acceptance criteria.
2. **Branch** from `main`: `<type>/<issue-number>-<short-description>`, e.g. `feat/12-openaq-client`.
3. **Commit** in small steps using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `perf`, with a scope such as
   `api`, `worker`, `ingestion`, `ml`, `web`, `infra`, `db`. Example: `feat(api): add sensors endpoint`.
4. **Open a PR** using the template, with `Closes #<issue>` in the description.
5. **CI must be green.** `main` is protected: PRs only, required checks, squash merge.

## Recording decisions and problems

- Choosing between real options? Write an ADR in `docs/adr/` (next number, same format).
- Hit a problem worth remembering? Add an entry to `docs/engineering-log.md`.

## Releasing

Follow [Semantic Versioning](https://semver.org/) and keep `CHANGELOG.md` in the
[Keep a Changelog](https://keepachangelog.com/) format. A release PR moves the Unreleased entries
under the new version and bumps the version in `backend/pyproject.toml`, `web/package.json`, their
lock files and `docs/openapi.json`. After it merges, pushing the tag (`git push origin vX.Y.Z`)
builds the images and deploys production by itself ([deployment guide](docs/DEPLOYMENT.md)).
