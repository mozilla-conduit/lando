# Lando

Lando is an application that applies patches and pushes them to Git and Mercurial repositories.

This application runs at: https://lando.moz.tools/

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

The container writes into the bind-mounted working copy, so it runs as the user
that owns it: `compose.yaml` builds its `app` user with the uid from `APP_UID`.
The `make` targets default it to your own uid, so they need no setup. If you
drive `docker compose` directly and your uid is not the usual 1000, set it in
`.env` and rebuild, otherwise the container cannot write to your checkout.

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

### Working on several branches at once

Each checkout runs as its own compose project, named after its directory, so
`git worktree` checkouts can be built and tested in parallel:

    git worktree add ../lando-bug-123456 -b bug-123456

Building and testing in `../lando-bug-123456` produces `lando-bug-123456-*`
images and its own database, Redis and volumes, leaving the ones belonging to
the main checkout untouched. Projects are named from the directory, so this
applies to `docker compose` invoked directly as much as to the `make` targets.
Create worktrees _beside_ the repository rather than inside it, so they stay out
of the Docker build context.

Three things are worth knowing about a new checkout:

- Only one checkout at a time can publish the proxy on port 443. Set
  `LANDO_PROXY_PORT` to something else in the others.
- The Vue bundle is built into the working copy rather than into the image, so
  run `make build-js` before serving the frontend.
- There is no git metadata in the Docker build context of a worktree, so the
  image reports the `fallback_version` from `pyproject.toml` rather than a
  version derived from the tags.

## General Tips

### Add a new migration

    make migrations

### Upgrade requirements

    make upgrade-requirements

### Add requirements

    make add-requirements

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).

[Conduit suite]: https://github.com/mozilla-conduit/suite
[github-app]: https://docs.github.com/en/enterprise-cloud@latest/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
[github-app-install]: https://docs.github.com/en/enterprise-cloud@latest/apps/using-github-apps/installing-your-own-github-app
