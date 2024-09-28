SHELL := /bin/bash
DOCKER := $(shell which docker)
DOCKER_COMPOSE := $(shell which docker-compose)

ifeq ($(STANDALONE), 1)
	BASE_COMMAND := docker-compose exec lando
else
	BASE_COMMAND := docker exec -ti suite-lando-1
endif

.PHONY: help
help:
	@"$(DOCKER)" --version
	@"$(DOCKER_COMPOSE)" --version
	@echo "usage: make <target>"
	@echo
	@echo "Set STANDALONE=1 to run commands outside of lando suite."
	@echo
	@echo
	@echo "target is one of:"
	@echo "    help        show this message and exit"
	@echo "    format      run ruff and black on source code"
	@echo "    test        run the test suite"
	@echo "    shell       execute a bash shell in the lando container"
	@echo "    migrations  generates migration files to reflect model changes in the database"
	@echo "    attach      attach for debugging (ctrl-p ctrl-q to detach)"

.PHONY: test
test:
	$(BASE_COMMAND) lando tests

.PHONY: format 
format:
	$(BASE_COMMAND) lando format

.PHONY: shell
shell:
	@echo "Run lando shell for a Python shell."
	@echo "Run lando --help for a list of additional commands."
	$(BASE_COMMAND) bash

.PHONY: setup
setup:
	ifeq ($(STANDALONE), 1)
		@echo "This command is not supported when in standalone mode."
	else
		$(BASE_COMMAND) lando setup_dev
	endif

.PHONY: migrations
migrations:
	$(BASE_COMMAND) lando makemigrations

.PHONY: attach
attach:
ifeq ($(INSUITE), 1)
	-@docker attach suite-lando-1 ||:
else
	-@docker-compose attach lando ||:
endif
