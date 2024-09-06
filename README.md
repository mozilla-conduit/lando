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

* docker
* docker compose 

### Running the development server
It is recommended to use "conduit suite" to interact with Lando on your local machine, however, it can also be run using docker-compose if needed.

    docker-compose up

The above command will run any database migrations and start the development server and its dependencies.

    docker-compose down

The above command will shut down the containers running lando.

## Specifying Suite or Stand-alone
By default, make commands will assume you are running them in suite. This will run the commands in the lando container in the suite. If you want to explicitly run commands on a standalone Lando container (i.e., if you started the container via `docker-compose up` above), then set STANDALONE=1. For example:

    STANDALONE=1 make test

## Testing

To run the test suite, invoke the following command:

    make test

If you need to run specific tests, or pass additional arguments, use the `lando tests`
command from within the Lando container.

#### Add a new migration

    make migrations

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).
