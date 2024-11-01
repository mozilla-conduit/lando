SHELL := /bin/bash
DOCKER := $(shell which docker)
DOCKER_COMPOSE := $(shell which docker-compose)

ifeq ($(STANDALONE), 1)
	BASE_COMMAND := docker-compose run lando
else
	BASE_COMMAND := docker exec -ti suite-lando-1
endif

.PHONY: help
help:
	@"$(DOCKER)" --version
	@"$(DOCKER_COMPOSE)" --version
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

.PHONY: test
test:
	$(BASE_COMMAND) lando tests

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
	-@docker-compose attach lando ||:
endif
