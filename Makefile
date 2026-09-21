.PHONY: help up down build migrate makemigrations seed shell superuser test lint fmt logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up:              ## Spustí vývojové prostředí
	docker compose up

build:           ## Sestaví obrazy
	docker compose build

down:            ## Zastaví a uklidí
	docker compose down

migrate:         ## Aplikuje migrace
	docker compose run --rm web python manage.py migrate

makemigrations:  ## Vygeneruje migrace
	docker compose run --rm web python manage.py makemigrations

seed:            ## Naplní databázi fiktivními daty
	docker compose run --rm web python manage.py seed_demo

superuser:       ## Vytvoří správce
	docker compose run --rm web python manage.py createsuperuser

shell:           ## Django shell
	docker compose run --rm web python manage.py shell

test:            ## Spustí testy
	docker compose run --rm web pytest

lint:            ## Kontrola stylu
	docker compose run --rm web ruff check .

fmt:             ## Formátování
	docker compose run --rm web ruff format .

logs:            ## Logy
	docker compose logs -f web worker
