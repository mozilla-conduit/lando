SHELL := /bin/bash
DOCKER := $(shell which docker)
DOCKER_COMPOSE := $(shell which docker-compose)


.PHONY: help
help:
	@$(DOCKER) --version
	@$(DOCKER_COMPOSE) --version
	@echo "usage: make <target>"
	@echo
	@echo "target is one of:"
	@echo "    help        show this message and exit"
	@echo "    build       build the docker image for lando"
	@echo "    format      run ruff and black on source code"
	@echo "    test        run the test suite"
	@echo "    migrations  generates migration files to reflect model changes in the database"
	@echo "    start       run the application"
	@echo "    stop        stop the application"
	@echo "    attach      attach for debugging (ctrl-p ctrl-q to detach)"

.PHONY: test
test:
	docker-compose run lando lando tests

.PHONY: format 
format:
	docker-compose run lando lando format

.PHONY: build 
build:
	docker-compose build

.PHONY: migrations
migrations:
	docker-compose run lando lando makemigrations

.PHONY: start
start:
	docker-compose up -d

.PHONY: stop
stop:
	docker-compose down

.PHONY: attach
attach:
	-@docker-compose attach lando ||:
