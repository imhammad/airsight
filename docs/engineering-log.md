# Engineering Log

Every problem we hit and how we solved it. Newest first.

Format: symptom, cause, fix, lesson.

---

### 2026-11-02: `ModuleNotFoundError: No module named 'airsight'` in pytest

- **Symptom:** `ruff` and `mypy` passed, but `uv run pytest` failed to import `airsight`.
- **Cause:** `uv add` installed the project in editable mode while `src/airsight/` was still
  empty, so no `.pth` file pointing at `src/` was created. Ruff and mypy read files from disk
  and don't need the package installed, which is why they passed.
- **Fix:** `uv sync --reinstall-package airsight` once the code existed.
- **Lesson:** create the package files before the first `uv add` / `uv sync`. CI installs from
  a clean checkout, so it will catch this kind of problem automatically.

### 2026-11-02: Starlette TestClient deprecation warning

- **Symptom:** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`.
- **Cause:** Starlette 1.2+ supports `httpx2` in its test client and warns when the old `httpx` is used.
- **Fix:** replaced the dev dependency `httpx` with `httpx2`.
- **Lesson:** treat warnings as future errors. Fix them while they're cheap.

### 2026-11-02: `npm install` fails with `ERESOLVE` in a fresh Vite app

- **Symptom:** `npm install` in `web/` failed: `peer typescript@">=4.8.4 <6.1.0" from typescript-eslint@8.72.1`.
- **Cause:** the `create-vite` 9.3.3 React TS template pins TypeScript `~7.0.2`, but the latest
  `typescript-eslint` (8.72.1) only supports TypeScript below 6.1.
- **Fix:** pinned TypeScript to `~6.0.3`, the newest version both support. Did not use
  `--force` / `--legacy-peer-deps`, which would hide the conflict instead of solving it.
- **Lesson:** a new major version of a core tool often ships before its ecosystem catches up.
  Let Dependabot + CI propose the upgrade once the ecosystem supports it.

### 2026-11-02: `npm install` reports 12 moderate vulnerabilities

- **Symptom:** `npm install` in `web/` reported 12 moderate severity vulnerabilities.
- **Cause:** one advisory (GHSA-g3hv-75wg-m249) in `minimatch` < 11.0.1, used internally by the ESLint
  toolchain. The other 11 entries are ESLint packages that depend on it.
- **Fix:** none applied. It affects dev tooling only (`npm audit --omit=dev` finds 0), and the only
  input is our own lint config. `npm audit fix --force` would have downgraded `typescript-eslint`
  to 8.14. Added `npm audit --omit=dev` to CI so production dependencies must stay clean.
- **Lesson:** read the audit before "fixing" it. Separate what ships to users from what only runs
  on developer machines.
