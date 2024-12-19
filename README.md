# Lando

Lando is an application that applies patches and pushes them to Git and Mercurial repositories.

## Development

### Contributing

- All contributors must abide by the Mozilla Code of Conduct.
- The [main repository](https://github.com/mozilla-conduit/lando) is hosted on GitHub. Pull requests should be submitted against the `main` branch.
- Bugs are tracked [on Bugzilla](https://bugzilla.mozilla.org), under the `Conduit :: Lando` component.
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

## Testing

To run the test suite, invoke the following command:

    make test

### Specifying test parameters

If you need to run specific tests, or pass additional arguments to `lando tests`,
you do so via the `ARGS_TESTS` parameter:

    make test ARGS_TESTS="-xk test_patch"

You can also pass arguments directly to pytest by placing them in the
`ARGS_TESTS` parameter, after a `--`:

    make test ARGS_TEST='-x -- --failed-first --verbose

### Specifying the test environment

By default, `make` commands will run a dedicated compose stack to run the tests.

Alternatively, you can run the `lando tests` command directly from n the Lando container.

    docker compose run --rm lando lando tests -x -- failed-first --verbose

It is also possible to run the tests in an existing stack from the
[Conduit suite](https://github.com/mozilla-conduit/suite), by specifying the
`INSUITE=1` parameter.

    make test INSUITE=1

You can instruct the system to run the tests in suite by default with

    make test-use-suite

and restore the default with

    make test-use-local

## General Tips

### Add a new migration

    make migrations

### Upgrade requirements

    make upgrade-requirements

### Add requirements

    make add-requirements

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).
