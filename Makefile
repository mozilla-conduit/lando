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
# Any target with an inline comment introduced with `##` will be shown here.
# Keeping `##` markers aligned in this file will ensure the output is aligned, too.
.PHONY: help
help:                 ## show this message and exit
	@$(DOCKER) --version
	@$(DOCKER_COMPOSE) version
	@echo "usage: make <target>"
	@echo
	@echo "target is one of:"
	@sed -n 's/\(^[^	:]*\+\):\(\s*\)##\s*\(.*\)$$/    \1\2\3/p' Makefile

.PHONY: add-requirements
add-requirements:     ## add-requirements
	$(BASE_COMMAND) lando generate_requirements

.PHONY: attach
attach:               ## attach for debugging (ctrl-p ctrl-q to detach)
ifeq ($(INSUITE), 1)
	-@docker attach suite-lando-1 ||:
else
	-@${DOCKER_COMPOSE} attach lando ||:
endif

.PHONY: build
build:                ## build the container images
	$(DOCKER_COMPOSE) build

.PHONY: format
format:               ## run ruff and djLint on source code
	$(BASE_COMMAND) lando format
.PHONY: migrations
migrations:           ## generates migration files to reflect model changes in the database
	$(BASE_COMMAND) lando makemigrations

.PHONY: test
test:                 ## run the Python and JavaScript test suites
test: test-py test-js

.PHONY: test-js
test-js:              ## run the JavaScript test suite (Vitest)
	$(BASE_COMMAND) npm test

.PHONY: test-py
test-py:              ##run the Python test suite
	$(BASE_COMMAND) lando tests $(ARGS_TESTS)

.PHONY: test-use-local
test-use-local:       ## run the testsuite using the local environment
	rm -f ${SUITE_STAMP}

.PHONY: test-use-suite
test-use-suite:       ## run the testsuite using the conduit-suite environment
	echo 1 > ${SUITE_STAMP}

.PHONY: upgrade-npm-packages
upgrade-npm-packages: ## upgrade-npm-packages update package-lock.json
	$(BASE_COMMAND) npm install

.PHONY: upgrade-requirements
upgrade-requirements: ## upgrade-requirements upgrade packages in requirements.txt
	$(BASE_COMMAND) lando generate_requirements --upgrade
