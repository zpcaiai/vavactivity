.PHONY: bootstrap dev stop reset migrate seed lint test verify openapi

bootstrap:
	./scripts/bootstrap.sh

dev:
	docker compose up --build

stop:
	docker compose down

reset:
	docker compose down -v

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m vav.cli.seed

lint:
	./scripts/lint.sh

test:
	./scripts/test.sh

verify:
	./scripts/verify.sh

openapi:
	./scripts/generate-openapi-client.sh

