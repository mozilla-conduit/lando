# Lando

Lando is an application that lands (merges) revisions to Git and Mercurial repositories.

Lando is comprised of many subcomponents, including:

* The user interface
* The API
* Landing workers
* A postgres database

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

    ```shell
    make start
    ```

The above command will run any database migrations and start the development server and its dependencies.

    ```shell
    make stop
    ```

The above command will shut down the containers running lando.

## Testing

To run the test suite, invoke the following command:

    ```shell
    make test
    ```

If you need to run specific tests, or pass additional arguments, use the `lando tests`
command from within the Lando container.

#### Add a new migration

    ```shell
    make migrations
    ```

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).
