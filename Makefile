PYTHON ?= python
SETTINGS ?= parsifal.settings.local

.PHONY: build test cli-test run init backup docker-build docker-up docker-init docker-logs

build:
	isort parsifal clients
	black parsifal clients
	flake8 parsifal clients
	./manage.py makemigrations --check --dry-run --settings=parsifal.settings.tests

test:
	$(PYTHON) manage.py test --settings=parsifal.settings.tests

cli-test:
	$(PYTHON) -m pytest -q clients/parsifal-cli

run:
	$(PYTHON) manage.py runserver --settings=$(SETTINGS)

# make init ARGS="--username admin --email you@example.org --token cli"
init:
	$(PYTHON) manage.py init $(ARGS) --settings=$(SETTINGS)

backup:
	$(PYTHON) manage.py backup --settings=$(SETTINGS)

docker-build:
	docker compose build

docker-up:
	docker compose up -d

# make docker-init ARGS="--username admin --token cli"
docker-init:
	docker compose run --rm parsifal init $(ARGS)

docker-logs:
	docker compose logs -f parsifal
