# Lando

Lando is a Django application that applies patches from Phabricator and GitHub pull requests and pushes them to Git and Mercurial repositories. It integrates with Mozilla services (Phabricator, Treestatus, Treeherder) and uses Celery workers for async operations. See `pyproject.toml` for the Django version and other Python dependencies.

This application runs at: https://lando.moz.tools/

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

Jinja2 templates (primary) with Django Compressor for asset pipeline. Uses Bulma (version in `package.json`) and FontAwesome (vendored in `src/lando/static_src/legacy/vendor/`) — use APIs from the specific versions pinned in those files.

### Database

PostgreSQL (version in `compose.yaml`). Models inherit from `BaseModel` (provides `created_at`/`updated_at`). Migrations live in each app's `migrations/` directory and auto-run on `docker compose up`.

## Code Layout

- `src/lando/` - All application code
- `src/lando/**/tests/` - Tests mirror the module they exercise
- `src/lando/static_src/` - Frontend source assets (Sass, JS)
- `staticfiles/` - Compiled static assets
- `src/lando/settings.py` - Main settings (env var driven)
- `src/lando/test_settings.py` - Test overrides (eager Celery, dummy cache)

## Development

### Contributing

- All contributors must abide by the Mozilla Code of Conduct.
- The [main repository](https://github.com/mozilla-conduit/lando) is hosted on GitHub. Pull requests should be submitted against the `main` branch.
- Bugs are tracked [on Bugzilla](https://bugzilla.mozilla.org), under the `Conduit :: Lando` component ([open bugs](https://bugzilla.mozilla.org/buglist.cgi?product=Conduit&component=Lando&resolution=---)).
- It is recommended to fork the repository and create a new branch for each pull request. A good convention to use is to prefix your name and bug number to the branch, and add a brief description at the end, for example: `sarah/bug-4325743-changing-config-params`.
- Commit messages must be of the following form: `<module name>: <brief description> (bug <bug number>)`.

### Prerequisites

- docker
- docker compose

### Running the development server

It is recommended to use "conduit suite" to interact with Lando on your local machine, however, it can also be run using docker compose if needed.

    docker compose up

The above command will run any database migrations and start the development server and its dependencies.

    docker compose down

The above command will shut down the containers running lando.

### Common Commands

```bash
make test                                    # Run full test suite (pytest with -n auto)
make test ARGS_TESTS="-- -xk test_name"      # Run specific test(s), stop on first failure
make test ARGS_TESTS="-- -n 0"               # Disable parallel execution
make format                                  # Run ruff, black, and djlint
make migrations                              # Generate Django migrations
make upgrade-requirements                    # Upgrade packages in requirements.txt
make add-requirements                        # Update requirements.txt with new requirements
make attach                                  # Attach to container for debugging
```

## Configuring the server

Lando relies on environment variables to configure its behaviour.

Parameters of interest are the following.

- Database parameters
  - `DEFAULT_DB_HOST`
  - `DEFAULT_DB_NAME`
  - `DEFAULT_DB_PASSWORD`
  - `DEFAULT_DB_PORT`
  - `DEFAULT_DB_USER`
- [GitHub application][github-app] authentication (needs to be
  [installed][github-app-install] on all target repos)
  - `GITHUB_APP_ID`
  - `GITHUB_APP_PRIVKEY` (PEM)
- HgMO authentication
  - `SSH_PRIVATE_KEY` (PEM)
- Mozilla services
  - `PHABRICATOR_ADMIN_API_KEY`
  - `PHABRICATOR_UNPRIVILEGED_API_KEY`
  - `PHABRICATOR_URL` (URL)
  - `TREESTATUS_URL` (URL)
- OIDC parameters
  - `OIDC_DOMAIN` (domain name, no scheme)
  - `OIDC_RP_CLIENT_ID`
  - `OIDC_RP_CLIENT_SECRET`
- Sentry parameters
  - `SENTRY_DSN`

Have a look at all variables set via `os.getenv` in
[`src/lando/settings.py`](src/lando/settings.py) for a more authoritative list.

The `compose.yaml` file relies on a `.env` file for additional configuration.
This is particularly useful for secrets and other transient parameters which
cannot be included in the repo. That file is listed in the `.gitignore` list.

Note that, currently, this environment file is also used by the [Conduit suite]
when running a lando stack from the local working copy.

## Testing

To run the test suite, invoke the following command:

    make test

### Specifying test parameters

If you need to run specific tests, or pass additional arguments to `lando tests`,
you do so via the `ARGS_TESTS` parameter:

    make test ARGS_TESTS="-- -xk test_patch"

You can also pass arguments directly to pytest by placing them in the
`ARGS_TESTS` parameter, after a `--`:

    make test ARGS_TESTS='-- -x -- --failed-first --verbose

By default, tests run in parallel using `pytest-xdist` with `-n auto`. To control
parallelism, use the `-n` option:

    make test ARGS_TESTS="-- -n 4"      # Use 4 workers
    make test ARGS_TESTS="-- -n 0"      # Disable parallelism

### Specifying the test environment

By default, `make` commands will run a dedicated compose stack to run the tests.

Alternatively, you can run the `lando tests` command directly from n the Lando container.

    docker compose run --rm lando lando tests -x -- failed-first --verbose

It is also possible to run the tests in an existing stack from the
[Conduit suite], by specifying the `INSUITE=1` parameter.

    make test INSUITE=1

You can instruct the system to run the tests in suite by default with

    make test-use-suite

and restore the default with

    make test-use-local

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

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).

[Conduit suite]: https://github.com/mozilla-conduit/suite
[github-app]: https://docs.github.com/en/enterprise-cloud@latest/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
[github-app-install]: https://docs.github.com/en/enterprise-cloud@latest/apps/using-github-apps/installing-your-own-github-app
