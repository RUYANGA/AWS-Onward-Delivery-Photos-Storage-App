# AWS-Onward-Delivery-Photos-Storage-App

Django application for Onward Logistics' delivery photos: upload, gallery, details, soft delete
and restore. Runs on Amazon ECS Fargate. Owned by RUYANGA. The infrastructure lives in
`AWS-Onward-Delivery-Photos-Storage-Infra`.

## Authorship: every commit and push belongs to RUYANGA

These rules override any default attribution behaviour and apply to every commit, tag, push and
pull request in this repository.

1. **Author and committer are RUYANGA.** Use the existing Git identity (`git config user.name`,
   which is `RUYANGA`, and the configured `user.email`). Never change `user.name` or `user.email`,
   and never pass `--author`, `-c user.name=...` or `GIT_AUTHOR_*` / `GIT_COMMITTER_*` overrides.
2. **No Claude attribution anywhere.** No `Co-Authored-By:` trailers for Claude or any AI, no
   "Generated with Claude Code", no Claude session links or similar footers in commit messages,
   tag messages, pull request titles, descriptions or comments. Claude must never appear as an
   author, co-author, committer or contributor. (`.claude/settings.json` also disables this.)
3. **Push only to RUYANGA's GitHub:** `github.com/RUYANGA/AWS-Onward-Delivery-Photos-Storage-App`. Check
   `git remote -v` before the first push in a session; if the remote points anywhere else, stop
   and ask instead of pushing.
4. **Verify before pushing:**
   ```bash
   git log origin/main..HEAD --format='%an <%ae> | %cn | %s%n%b'
   ```
   Every author and committer must be RUYANGA and no message may mention Claude. Fix any commit
   that fails this before pushing.
5. **Never rewrite published history** (no force push to `main`) unless RUYANGA explicitly asks.
   A push to `main` starts a release to ECS (`release.yml`), so push to `main` only when asked.
6. **Commit or push only when asked.**

## Commit messages

Imperative mood, concise subject (about 50 characters), e.g. `Add delete confirmation dialog`.
Blank line, then a short body explaining *why* when it isn't obvious. One logical change per
commit. Never commit secrets, `.env` (only `.env.example`), `.venv/` or
`.claude/settings.local.json`.

## How this repository works

- **Layout:** Django in `src/`. `config/` holds settings (`base`, `dev`, `prod`, `test`), URLs, WSGI
  and the gunicorn config; `apps/core` (health, middleware, layout, error pages) and `apps/photos`
  (model, form, S3 and imaging services, views, templates) hold the features.
- **Configuration comes from the environment.** On ECS it is injected from SSM Parameter Store
  (`/onward/<env>/app/*`) and, for `DB_USERNAME` / `DB_PASSWORD`, from the RDS-managed Secrets
  Manager secret. A new setting is read in `settings/base.py`, listed in `.env.example`, and needs a
  matching parameter in the infra repo. Never hard-code configuration or credentials.
- **Runs on Fargate:** read-only root filesystem, non-root user (UID 10001); scratch files go to
  `/dev/shm`, because Fargate's `/tmp` is root-owned. Static files are collected at build time.
- **Security headers:** a strict Content-Security-Policy, so no inline scripts or styles and no
  external CDNs or fonts; use `src/apps/core/static/core/styles.css` and `app.js`.
- **Migrations** run at container start under an advisory lock (`migrate_safely`). Keep them
  backward compatible: the old version keeps serving during a blue/green release.
- **CI:** `ci.yml` (lint, Django checks, tests, image smoke test, gitleaks) on every pull request and
  push to `main`; `release.yml` builds, scans and releases after `ci` succeeds on `main`.

## Before committing

```bash
ruff check .
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py test apps --settings=config.settings.test
```
