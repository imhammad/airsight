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
