-include .env
export
PYTHON ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
DB_URL = postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@db:5432/$(POSTGRES_DB)?sslmode=disable

.PHONY: up down migrate migrate-down collect abertas test psql

up:            ## Postgres + migrations
	docker compose up -d db migrate

down:
	docker compose down

migrate:
	docker compose run --rm migrate

migrate-down:  ## desfaz a última migration
	docker compose run --rm migrate -path=/migrations -database="$(DB_URL)" down 1

collect:       ## coleta incremental do PNCP
	docker compose run --rm collector

abertas:       ## radar de licitações com propostas abertas
	docker compose run --rm collector pncp abertas --saida postgres

test:          ## unitários + integração (banco descartável no Postgres do compose; pulados se ele estiver parado)
	cd services/collectors && $(PYTHON) -m pytest -q
	cd services/api && go vet ./... && go test ./...

psql:
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
