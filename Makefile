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

.PHONY: help
help:
	@$(DOCKER) --version
	@$(DOCKER_COMPOSE) version
	@echo "usage: make <target>"
	@echo
	@echo "target is one of:"
	@echo "    help                 show this message and exit"
	@echo "    format               run ruff and black on source code"
	@echo "    test                 run the test suite"
	@echo "    migrations           generates migration files to reflect model changes in the database"
	@echo "    upgrade-requirements upgrade packages in requirements.txt"
	@echo "    upgrade-npm          update package-lock.json"
	@echo "    add-requirements     update requirements.txt with new requirements"
	@echo "    attach               attach for debugging (ctrl-p ctrl-q to detach)"
	@echo "    test-use-suite       run the testsuite using the conduit-suite environment"
	@echo "    test-use-local       run the testsuite using the local environment"

.PHONY: test
test:
	$(BASE_COMMAND) lando tests $(ARGS_TESTS)

.PHONY: test-use-suite
test-use-suite:
	echo 1 > ${SUITE_STAMP}

.PHONY: test-use-local
test-use-local:
	rm -f ${SUITE_STAMP}

.PHONY: format
format:
	$(BASE_COMMAND) lando format

.PHONY: migrations
migrations:
	$(BASE_COMMAND) lando makemigrations

.PHONY: upgrade-requirements
upgrade-requirements:
	$(BASE_COMMAND) lando generate_requirements --upgrade

.PHONY: add-requirements
add-requirements:
	$(BASE_COMMAND) lando generate_requirements

.PHONY: upgrade-npm
upgrade-npm:
	$(BASE_COMMAND) npm install

.PHONY: attach
attach:
ifeq ($(INSUITE), 1)
	-@docker attach suite-lando-1 ||:
else
	-@${DOCKER_COMPOSE} attach lando ||:
endif
