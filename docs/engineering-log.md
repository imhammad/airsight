# Engineering Log

Every problem we hit and how we solved it. Newest first.

Format: symptom, cause, fix, lesson.

---

### 2026-11-04: Compose smoke test failed on beat with no health check
- **Symptom:** `docker compose up --wait` passed on the Mac but failed in CI with "container airsight-beat-1 has no healthcheck configured".
- **Cause:** beat's health check was disabled (the image's default check calls the API, which beat doesn't run). The Compose version in CI treats a service without a health check as a failure under `--wait`; the newer local version doesn't.
- **Fix:** beat now has its own check: it is healthy while it can ping Redis, where it puts each scheduled task.
- **Lesson:** local and CI tool versions differ. Give every long-running service a real health check rather than relying on how one version treats "none".

### 2026-11-04: Re-running an old step printed the AirNow key again
- **Symptom:** a 7-day backfill printed full AirNow URLs, API key included, and the output was pasted into the project chat.
- **Cause:** commands from an earlier step were re-run by mistake. They overwrote `backfill.py` with the version from before the logging fix, so httpx2 logged request URLs again.
- **Fix:** rotated the AirNow key, restored the files with `git restore .`, deleted the stray branch. The Celery worker re-applies the same protection after Celery sets up its own logging, with a test.
- **Lesson:** a fix that lives in one call site can be undone by old code. Check `git status` before running pasted commands, and treat any key that reaches a chat or log as exposed: rotate it, don't just delete the message.

### 2026-11-04: Backfill output printed the AirNow API key
- **Symptom:** the backfill's INFO output included full request URLs, and AirNow's URLs carry the API key.
- **Cause:** the httpx2 library logs every request URL at INFO level. AirNow only accepts its key as a URL parameter. The client already hid the key in error messages, but not in the library's own logs.
- **Fix:** one shared `configure_logging()` sets the httpx2 and httpcore loggers to WARNING. A test makes a request with logging at INFO and checks the key is absent; with the fix disabled, the test fails.
- **Lesson:** secrets in URLs leak through every layer that records URLs (logs, proxies, error trackers). Prefer headers, and when an API forces URL keys, test the logs, not only the error messages.

### 2026-11-03: Test cleanup fails with "database is being accessed by other users"
- **Symptom:** all tests passed, but the teardown of the test database failed: `DROP DATABASE airsight_test WITH (FORCE)` raised `ObjectInUse`, "There is 1 other session using the database". It happened only sometimes.
- **Cause:** TimescaleDB starts a background scheduler in every database that has the extension, checking for new databases about once a minute. When that check overlapped the end of a test run, the scheduler connected while the database was being dropped.
- **Fix:** the test fixture calls `_timescaledb_functions.stop_background_workers()` in the test database before dropping it, and retries the drop up to 5 times. Verified with a deliberately slow test, so the scheduler was connected.
- **Lesson:** extensions can run their own background processes. Intermittent failures are usually timing, so reproduce the timing, not just the command.

### 2026-11-02: `npm install` reports 12 moderate vulnerabilities

- **Symptom:** `npm install` in `web/` reported 12 moderate severity vulnerabilities.
- **Cause:** one advisory (GHSA-g3hv-75wg-m249) in `minimatch` < 11.0.1, used internally by the ESLint
  toolchain. The other 11 entries are ESLint packages that depend on it.
- **Fix:** none applied. It affects dev tooling only (`npm audit --omit=dev` finds 0), and the only
  input is our own lint config. `npm audit fix --force` would have downgraded `typescript-eslint`
  to 8.14. Added `npm audit --omit=dev` to CI so production dependencies must stay clean.
- **Lesson:** read the audit before "fixing" it. Separate what ships to users from what only runs
  on developer machines.

### 2026-11-02: `npm install` fails with `ERESOLVE` in a fresh Vite app

- **Symptom:** `npm install` in `web/` failed: `peer typescript@">=4.8.4 <6.1.0" from typescript-eslint@8.72.1`.
- **Cause:** the `create-vite` 9.3.3 React TS template pins TypeScript `~7.0.2`, but the latest
  `typescript-eslint` (8.72.1) only supports TypeScript below 6.1.
- **Fix:** pinned TypeScript to `~6.0.3`, the newest version both support. Did not use
  `--force` / `--legacy-peer-deps`, which would hide the conflict instead of solving it.
- **Lesson:** a new major version of a core tool often ships before its ecosystem catches up.
  Let Dependabot + CI propose the upgrade once the ecosystem supports it.

### 2026-11-02: Starlette TestClient deprecation warning

- **Symptom:** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`.
- **Cause:** Starlette 1.2+ supports `httpx2` in its test client and warns when the old `httpx` is used.
- **Fix:** replaced the dev dependency `httpx` with `httpx2`.
- **Lesson:** treat warnings as future errors. Fix them while they're cheap.

### 2026-11-02: `ModuleNotFoundError: No module named 'airsight'` in pytest

- **Symptom:** `ruff` and `mypy` passed, but `uv run pytest` failed to import `airsight`.
- **Cause:** `uv add` installed the project in editable mode while `src/airsight/` was still
  empty, so no `.pth` file pointing at `src/` was created. Ruff and mypy read files from disk
  and don't need the package installed, which is why they passed.
- **Fix:** `uv sync --reinstall-package airsight` once the code existed.
- **Lesson:** create the package files before the first `uv add` / `uv sync`. CI installs from
  a clean checkout, so it will catch this kind of problem automatically.
