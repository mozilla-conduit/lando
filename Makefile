SHELL := /bin/bash
DOCKER := $(shell which docker)
DOCKER_COMPOSE := ${DOCKER} compose
ARGS_TEST ?=

ifeq ($(INSUITE), 1)
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
	@echo "    add-requirements     update requirements.txt with new requirements"
	@echo "    attach               attach for debugging (ctrl-p ctrl-q to detach)"
	@echo
	@echo "Set INSUITE=1 to run commands inside the suite stack"

.PHONY: test
test:
	$(BASE_COMMAND) lando tests $(ARGS_TESTS)

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

.PHONY: attach
attach:
ifeq ($(INSUITE), 1)
	-@docker attach suite-lando-1 ||:
else
	-@${DOCKER_COMPOSE} attach lando ||:
endif
