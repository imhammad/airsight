# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog (https://keepachangelog.com/en/1.1.0/), and the project uses
Semantic Versioning (https://semver.org/).

## Unreleased

## 0.1.0 - 2026-11-02

Foundations: the repository, tooling and delivery pipeline every later feature builds on.

### Added

- Issue forms and pull request template (#2).
- Data coverage check confirming the San Francisco Bay Area as the training region (ADR 0001) (#4).
- Backend Python package `airsight` (uv, FastAPI) with `GET /v1/health`, and ADR 0002 on the
  single-package layout (#11).
- Multi-stage, non-root Docker image for the backend and a docker compose stack with
  PostgreSQL (TimescaleDB + PostGIS) and Redis, all with health checks (#12).
- Pre-commit hooks: ruff, mypy, file hygiene and private key detection (#13).
- CI on every pull request: lint, backend tests, a docker compose smoke test and web checks,
  plus Dependabot for uv, npm, GitHub Actions and Docker (#14, #17).
- Web app scaffold (Vite, React, TypeScript) with ESLint, Prettier and Vitest (#17).
- README, contributing guide, security policy and engineering log (#21).
