SHELL := /bin/bash
DOCKER := $(shell which docker)
DOCKER_COMPOSE := ${DOCKER} compose
ARGS_TESTS ?=

SUITE_STAMP=.test-use-suite

INSUITE=$(shell cat ${SUITE_STAMP} 2>/dev/null)

ifeq (${INSUITE}, 1)
	BASE_COMMAND := docker exec -ti suite-lando-1
else
	BASE_COMMAND := ${DOCKER_COMPOSE} run --rm lando
endif

# This target needs to be the first in the file, so it's called by default.
.PHONY: help
help:
	@$(DOCKER) --version
	@$(DOCKER_COMPOSE) version
	@echo "usage: make <target>"
	@echo
	@echo "target is one of:"
	@echo "    add-requirements     update requirements.txt with new requirements"
	@echo "    attach               attach for debugging (ctrl-p ctrl-q to detach)"
	@echo "    build                build the container images"
	@echo "    format               run ruff and djLint on source code"
	@echo "    help                 show this message and exit"
	@echo "    migrations           generates migration files to reflect model changes in the database"
	@echo "    test                 run the Python and JavaScript test suites"
	@echo "    test-py              run the Python test suite"
	@echo "    test-js              run the JavaScript test suite (Vitest)"
	@echo "    test-use-local       run the testsuite using the local environment"
	@echo "    test-use-suite       run the testsuite using the conduit-suite environment"
	@echo "    upgrade-npm-packages update package-lock.json"
	@echo "    upgrade-requirements upgrade packages in requirements.txt"

.PHONY: add-requirements
add-requirements:
	$(BASE_COMMAND) lando generate_requirements

.PHONY: attach
attach:
ifeq ($(INSUITE), 1)
	-@docker attach suite-lando-1 ||:
else
	-@${DOCKER_COMPOSE} attach lando ||:
endif

.PHONY: build
build:
	$(DOCKER_COMPOSE) build

.PHONY: format
format:
	$(BASE_COMMAND) lando format

.PHONY: migrations
migrations:
	$(BASE_COMMAND) lando makemigrations

.PHONY: test
test: test-py test-js

.PHONY: test-js
test-js:
	$(BASE_COMMAND) npm test

.PHONY: test-py
test-py:
	$(BASE_COMMAND) lando tests $(ARGS_TESTS)

.PHONY: test-use-local
test-use-local:
	rm -f ${SUITE_STAMP}

.PHONY: test-use-suite
test-use-suite:
	echo 1 > ${SUITE_STAMP}

.PHONY: upgrade-npm-packages
upgrade-npm-packages:
	$(BASE_COMMAND) npm install

.PHONY: upgrade-requirements
upgrade-requirements:
	$(BASE_COMMAND) lando generate_requirements --upgrade
