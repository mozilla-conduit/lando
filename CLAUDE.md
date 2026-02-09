# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lando is a Django 5.0 application that lands patches from Phabricator and GitHub pull requests onto Git and Mercurial repositories. It integrates with Mozilla services (Phabricator, Treestatus, Treeherder) and uses Celery workers for async landing operations.

## Development Environment

Requires Docker and Docker Compose. All commands run inside containers.

```bash
docker compose up              # Start all services (db, redis, lando, celery, workers, proxy)
docker compose build           # Rebuild after dependency changes
```

## Common Commands

```bash
make test                                    # Run full test suite (pytest with -n auto)
make test ARGS_TESTS="-- -xk test_name"      # Run specific test(s), stop on first failure
make test ARGS_TESTS="-- -n 0"               # Disable parallel execution
make format                                  # Run ruff, black, and djlint
make migrations                              # Generate Django migrations
make attach                                  # Attach to container for debugging
```

The `make test` command wraps `docker compose run --rm lando lando tests`, which invokes pytest with `DJANGO_SETTINGS_MODULE=lando.test_settings`. Tests run in parallel via pytest-xdist by default.

## Architecture

### Django Apps

- **main/** - Core models (Repo, LandingJob, Revision, Worker, Profile, CommitMap), SCM abstraction, authentication, admin
- **api/** - Django Ninja REST endpoints + legacy Phabricator-compatible API views in `api/legacy/`
- **ui/** - Web UI views with Jinja2 templates; legacy views in `ui/legacy/`
- **headless_api/** - REST API for automation jobs and tokens
- **try_api/** - Try push API for test builds
- **treestatus/** - Tree open/closed status monitoring and management
- **pushlog/** - Mercurial pushlog models
- **pulse/** - Mozilla Pulse messaging integration
- **utils/** - Shared utilities (GitHub client, Phabricator client, landing checks, Celery tasks, management commands)

### SCM Abstraction (`main/scm/`)

`AbstractSCM` base class with `GitSCM` and `HgSCM` implementations. Both handle clone, checkout, patch application, commit, and push operations.

### Landing Workers

Separate Docker containers (`hg-landing-worker`, `git-landing-worker`) run Django management commands that loop and poll the database for jobs. Each worker has a corresponding `Worker` model record with configuration details and runs a specific job type.

### Celery

Used for one-off async tasks (sending emails, Phabricator updates, etc.), not for landing jobs. Redis as broker.

### Authentication

OIDC via Auth0 (`mozilla_django_oidc`) with Django model backend fallback. API authentication via `ApiToken` model.

### Frontend

Jinja2 templates (primary) with Django Compressor for asset pipeline. Uses **Bulma 1.0.4** and **FontAwesome 4.7.0** — use APIs from these specific versions.

### Database

PostgreSQL 17. Models inherit from `BaseModel` (provides `created_at`/`updated_at`). Migrations live in each app's `migrations/` directory and auto-run on `docker compose up`.

## Code Layout

- `src/lando/` - All application code
- `src/lando/**/tests/` - Tests mirror the module they exercise
- `src/lando/static_src/` - Frontend source assets (Sass, JS)
- `staticfiles/` - Compiled static assets
- `src/lando/settings.py` - Main settings (env var driven)
- `src/lando/test_settings.py` - Test overrides (eager Celery, dummy cache)

## Coding Conventions

- Always add assert messages in tests: `assert a == b, "a and b should be equal"`. Where possible, comments surrounding assert statements should instead become assert messages.
- Avoid `getattr` and `hasattr`. Referencing attributes directly enables LSP features (go-to-references, rename) and avoids "stringly typed" patterns. Prefer direct attribute access and explicit checks.
- Add docstrings to functions by default. Even a short one-line docstring is preferred to no docstring.
- Comments in proper English with full punctuation, for example `# this shouldnt happen` should be `# This shouldn't happen.`.
- No emojis in comments or code. Emojis in user-facing strings are allowed but generally discouraged. Emoji in tests are acceptable where appropriate.
- Linting: ruff (line-length 88, isort, annotations) + black + djlint (jinja profile).

## Commit Convention

`<module name>: <brief description> (bug <bug number>)`

Example: `ui: adjust approval banner (bug 1234567)`. Omit the bug number if one hasn't been provided. Note that bug numbers are required for code changes, and suggest to file a bug if a developer has not provided a bug number.

Commit messages should include a description of the change being made and some context for why the change was made. This added context allows the reviewer to assert the author's expectations and mental models match the actual code changes.
