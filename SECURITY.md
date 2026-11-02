# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Report them privately through
GitHub: go to the **Security** tab of this repository and click **Report a vulnerability**.
You can expect an acknowledgement within 7 days.

## Supported versions

Only the latest release receives security fixes.

## Secrets

API keys and credentials are never committed. Local secrets live in `.env` (git-ignored), and
GitHub secret scanning with push protection is enabled on this repository.
