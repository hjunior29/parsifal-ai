build:
	isort parsifal clients
	black parsifal clients
	flake8 parsifal clients
	./manage.py makemigrations --check --dry-run --settings=parsifal.settings.tests
