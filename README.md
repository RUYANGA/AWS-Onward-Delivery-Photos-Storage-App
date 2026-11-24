# Onward Logistics: delivery photos application

A single full-stack Python application built with **Django 5.2 (LTS)**. Administrators upload a delivery photo with its title, description, merchant, rider, city and time taken (the app assigns each photo a delivery reference such as `ONW-2026-3F9A1C`); customers and merchants browse the gallery without signing in. Infrastructure lives in [AWS-Onward-Delivery-Photos-Storage-Infra](https://github.com/RUYANGA/AWS-Onward-Delivery-Photos-Storage-Infra).

## How it works

- **Roles:** anyone can view the gallery and live photos. Uploading, editing, deleting, restoring and Deleted photos need an administrator, who signs in with an email and password (`/sign-in`). Viewers who open a management page are sent to sign in; signed-in accounts without the permission get 403. Deleted photos and the change history are shown to administrators only. The app records who uploaded, edited and deleted each photo, in the database and in the sidecar.
- **Upload:** the app checks the file is a real JPEG, PNG or WebP image, stores the **original bytes unchanged** in S3, creates a 480 px WebP thumbnail and writes a JSON sidecar of the details. Keys are random UUIDs and cached as immutable.
- **Catalogue:** one row per photo in PostgreSQL with the S3 key, version ID and SHA-256 checksum, which link the record to the exact evidence file. No image bytes are stored in the database.
- **Viewing:** pages come from the app; `/media/*` is served by CloudFront directly from S3. The `/media` route in the app is only a local-development fallback.
- **Edit:** a live photo's details can be corrected and the photo itself replaced (`/photos/<id>/edit`). Because the photo is evidence, nothing is overwritten: every edit needs a reason and is saved as a numbered revision in the photo's change history (`PhotoChange`), showing each detail before and after. A replacement photo is stored under new keys; the previous original and thumbnail stay in S3 and are listed in the history with their checksum. The delivery reference and upload time never change. If someone else saved the photo first, the edit is refused (409) and the latest details are shown, so no change is silently overwritten. Deleted photos must be restored before they can be edited. The history is also written to the sidecar, so `rebuild_catalogue` restores it.
- **Delete and restore:** deleting hides a photo (soft delete) and keeps its files, so it can be restored from Deleted photos. **Delete permanently** (only for photos already in Deleted photos) removes the row and its change history, and whenever a photo's row is deleted the app also removes its photo, thumbnail, sidecar and any earlier replaced photos from S3 (`signals.py`). S3 keeps the old versions until the lifecycle rule expires them (the bucket policy stops anyone erasing them sooner), and the replica in the recovery Region keeps its copy.
- **Security:** sessions stored in PostgreSQL that end after 8 hours, a new session key at sign-in, passwords hashed with PBKDF2 and checked by Django's validators (12 characters minimum), sign-in paused for 15 minutes after 5 failures for an account or 20 from one address, the same error for a wrong email or password, CSRF tokens on every form, a strict Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, and uploads larger than `MAX_UPLOAD_MB` refused (413) before the body is read.
- **Pages:** gallery with search (`/`), upload (`/upload`), photo details (`/photos/<id>`), edit (`/photos/<id>/edit`), deleted photos (`/deleted`), sign in and out (`/sign-in`, `/sign-out`), about page with student and lab name (`/about`), health checks (`/healthz`, `/readyz`).

## Project layout

```
manage.py                  Django command line (puts src/ on the path)
src/
  config/                  project configuration
    settings/                base.py (shared), dev.py, prod.py (ECS Fargate), test.py
    urls.py                  root URLs and error handlers
    wsgi.py                  entry point: gunicorn config.wsgi:application
    gunicorn.py              gunicorn settings (workers, timeouts tied to the ALB, /dev/shm)
  apps/                    one Django app per feature
    core/                    health checks (/healthz, /readyz), middleware (health, upload limit,
                             CSP), JSON logging, About and error pages, shared layout and stylesheet,
                             migrate_safely command, tests/
    accounts/                sign-in and sign-out, permission checks, failed sign-in throttling,
                             ensure_admin command (creates the administrator), tests/
    photos/                  models.py (photos table), migrations/, forms.py (upload validation),
                             services/ (storage.py: S3, imaging.py: validation and thumbnails),
                             views.py, urls.py, templates/photos/, rebuild_catalogue command, tests/
requirements/              base.txt, prod.txt (+ gunicorn), dev.txt (+ moto, ruff)
scripts/build-deploy-bundle.sh   release hand-off to CodeDeploy
scripts/rollback.sh        list releases and roll back to one
scripts/db-query.sh        read-only SQL against the private RDS database
deploy/appspec.yaml        CodeDeploy appspec
```

## Configuration

All settings come from environment variables. In AWS they are kept in SSM Parameter Store under `/onward/dev/app/` (one parameter per variable, created by the infra repository) and ECS injects them when a task starts; `DB_USERNAME` and `DB_PASSWORD` come from the RDS-managed secret in Secrets Manager. Nothing is configured in the image or in this repository. For local runs without Docker, copy `.env.example` to `.env`; it uses the same variable names.

| Variable | Purpose |
|---|---|
| `PHOTO_BUCKET`, `AWS_REGION` | S3 bucket and Region (Parameter Store) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SSLMODE` | Database location, `sslmode=require` in AWS (Parameter Store) |
| `DB_USERNAME`, `DB_PASSWORD` | Injected from Secrets Manager |
| `DATABASE_URL` | Local alternative to the `DB_*` variables, e.g. `postgres://user:pass@host:5432/photos` |
| `MAX_UPLOAD_MB` | Upload limit, default 15 (Parameter Store) |
| `STUDENT_NAME`, `LAB_NAME` | About page (Parameter Store) |
| `APP_ENV` | Environment name (Parameter Store) |
| `S3_ENDPOINT_URL` | Local S3 emulator only |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` in the image, `config.settings.dev` for `manage.py` |
| `CSRF_TRUSTED_ORIGINS` | Defaults to `https://*.cloudfront.net` in production (CloudFront sends the ALB's host name) |
| `SECRET_KEY` | Signs sessions; every task must share it. Required in production (Secrets Manager); local runs fall back to a fixed or generated key |
| `ADMIN_EMAIL`, `ADMIN_NAME` | The administrator's sign-in email and name (Parameter Store) |
| `ADMIN_PASSWORD` | The administrator's password (Secrets Manager). Never put it in the code or the repositories |
| `SESSION_COOKIE_SECURE` | `true` in production; `false` only for local `http://localhost` |

## Run locally

```bash
docker compose up --build
# open http://localhost:8000
```

This starts PostgreSQL and LocalStack S3 with a versioned bucket, using local-only dummy values. To sign in locally, put `ADMIN_EMAIL`, `ADMIN_NAME` and `ADMIN_PASSWORD` in your git-ignored `.env` before starting; each start creates or updates that administrator. Without Docker:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py ensure_admin   # reads ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD from .env or the environment
python manage.py runserver      # needs DATABASE_URL, PHOTO_BUCKET (and S3_ENDPOINT_URL for LocalStack)
```

## Test

```bash
pip install -r requirements/dev.txt
ruff check .
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py check --deploy --settings=config.settings.prod
python manage.py test apps --settings=config.settings.test
```

Tests use an in-memory SQLite database and a mocked S3 (moto). They cover upload to gallery, bytes in S3 and not in the database, checksum and versioning, sidecars, soft delete and restore, permanent delete removing the S3 files, validation, CSRF, upload limits, media key filtering, search, health checks behind the load balancer, security headers, error pages and the catalogue rebuild.

## Pipeline

Three GitHub Actions workflows:

- **`ci.yml`** (every pull request to `main`; not repeated on the merge): ruff, the tests, a missing-migrations check, Django's deployment checks, a Docker build with a smoke test that runs the image the way ECS does (read-only filesystem, `/healthz`, `/readyz`, About page, non-root user), and gitleaks. No AWS access.
- **`release.yml`** (every merge to `main`, or *Run workflow* by hand): builds the image of the merged commit and fails on critical vulnerabilities (Trivy). It then assumes an AWS role through GitHub OIDC (no stored keys) and:

1. pushes a tag equal to the commit SHA (re-running a release for the same commit pushes the same image again);
2. uploads `deploy/deploy-bundle.zip` (`taskdef.json` rendered from the live task definition by `scripts/build-deploy-bundle.sh`, which also adds the container health check, plus `deploy/appspec.yaml`);
3. moves `latest` to this build. That push starts the CodePipeline `onward-dev-photos-release` (infra repository, `templates/pipeline.yaml`), which runs a CodeDeploy blue/green release with automatic rollback on alarm.

- **`rollback.yml`** (*Run workflow* by hand): lists the releases you can roll back to, or redeploys one of them. See below.

The task definition itself (CPU, memory, roles, secrets) is owned by the infra repository; this repository only swaps the image.

### Versions and rollback

Every release is the git SHA of the commit merged to `main`. It is the image's tag in ECR, it is baked into the image (`APP_VERSION`), and the running version is shown on the **About** page and in `/readyz` (`"version"`). ECR keeps the **last 10 releases**; older ones are deleted automatically.

Each pipeline run is named by its version: the deploy bundle is uploaded with the label `Version <sha>: <pull request title>` (`scripts/release-label.sh`), which CodePipeline shows as the *DeployBundle* source revision in the run history and in the Deploy stage's **Rollback** dialog. A rollback run is labelled `Version <sha>: rollback: <reason>`. The run's *Variables* show `Version` and `Reason` too.

To roll back from the pipeline console, open the Deploy stage's **Rollback**, choose the version by its label and *Start rollback*. The dialog lists successful runs made since the pipeline definition last changed; for any of the 10 releases kept in ECR, use the workflow below.

To roll back to a specific version:

1. *Actions > rollback > Run workflow* with **version** empty. The run summary lists the 10 releases, newest first, with the live one marked.
2. Run it again with the **version** (7 or more characters of the git SHA) and a **reason**.

The pipeline then redeploys that exact image blue/green, with the same alarms and automatic rollback as a release. `latest` is not moved, so the next merge to `main` releases normally; to stay on the old version, revert the bad commit in a pull request. From a terminal with AWS access, `AWS_REGION=eu-west-1 ./scripts/rollback.sh [<version> "<reason>"]` does the same.

During the minutes after a release while the old version is still running, *Stop and roll back* in CodeDeploy is faster: traffic returns to the old tasks at once.

Repository variables: `AWS_REGION` and `AWS_ROLE_ARN` (the infra bootstrap output `AppCiRoleArn`). `ECR_REPOSITORY`, `TASK_FAMILY`, `DEPLOY_BUCKET` and `PIPELINE_NAME` default to the names the infra repository creates.

## Container

Multi-stage `python:3.12-slim` image, runs as UID 10001, no compilers or secrets, served by gunicorn on port 8000. Static files are collected at build time and served by WhiteNoise (CloudFront caches `/static/*`). ECS Fargate runs it with a read-only root filesystem; on Fargate `/tmp` is root-owned, so gunicorn's heartbeat files and any temporary files go to `/dev/shm` (`TMPDIR`).

ECS checks each task's health by running `GET /healthz` inside the container every 30 seconds (Python, as the image has no curl), so the console shows **Healthy**; a task that fails 3 checks in a row is replaced. The check is added to the task definition by `scripts/build-deploy-bundle.sh` on every release.

On start, each task runs `python manage.py migrate_safely`, which applies pending migrations under a PostgreSQL advisory lock, so tasks starting together during a blue/green release or scale-out never race; then `ensure_admin --if-configured` creates or updates the administrator from `ADMIN_EMAIL`, `ADMIN_NAME` and `ADMIN_PASSWORD`; then gunicorn starts. The password secret is the source of truth: change it in Secrets Manager and the next task start applies it. Keep migrations backward compatible (add columns before using them), because the old version keeps serving until CodeDeploy shifts traffic.

## Query the database

The database is private: only the app tasks can reach it. To look at the data, run a read-only query from a terminal with AWS access:

```bash
./scripts/db-query.sh "SELECT delivery_reference, title, deleted_at FROM photos ORDER BY created_at DESC"
```

It starts a one-off copy of the app task (same subnets, security group and Secrets Manager credentials), runs the query in a `READ ONLY` transaction, prints the rows and stops, in about a minute. Writes are refused. Needs the AWS CLI and `jq`; `AWS_REGION` defaults to `eu-west-1`.

## Disaster recovery

`python manage.py rebuild_catalogue --bucket <bucket>` rebuilds the photo table from the replicated `meta/*.json` sidecars (`--dry-run` to preview, `--report-orphans` to list photos with no catalogue row). See the infra repository's `docs/runbook.md`.
