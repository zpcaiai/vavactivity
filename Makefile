.PHONY: bootstrap dev stop reset migrate seed lint test verify openapi \
	auth-migrate auth-seed create-super-admin auth-test auth-security-test auth-e2e auth-verify \
	cms-migrate cms-seed cms-test cms-security-test cms-user-e2e cms-admin-e2e i18n-check cms-verify \
	catalog-migrate catalog-seed catalog-test catalog-concurrency-test catalog-security-test \
	catalog-user-e2e catalog-admin-e2e catalog-verify \
	commerce-migrate commerce-seed commerce-test commerce-webhook-test \
	commerce-concurrency-test commerce-security-test commerce-user-e2e \
	commerce-admin-e2e commerce-reconcile commerce-verify \
	activity-migrate activity-seed activity-test activity-concurrency-test \
	activity-security-test activity-user-e2e activity-admin-e2e activity-verify \
	course-migrate course-seed course-test course-concurrency-test course-security-test \
	course-user-e2e course-admin-e2e course-verify \
	counseling-migrate counseling-seed counseling-test counseling-concurrency-test \
	counseling-security-test counseling-user-e2e counseling-admin-e2e counseling-verify \
	knowledge-migrate knowledge-seed knowledge-ingest-fixtures knowledge-build-index \
	knowledge-test knowledge-retrieval-test knowledge-security-test knowledge-eval \
	knowledge-admin-e2e knowledge-verify

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

auth-migrate:
	docker compose exec -T api alembic upgrade head

auth-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions

create-super-admin:
	docker compose exec api python -m vav.cli.create_super_admin $(if $(EMAIL),--email $(EMAIL),)

auth-test:
	docker compose exec -T api pytest tests/identity -q

auth-security-test:
	docker compose exec -T api pytest tests/identity/security -q

auth-e2e:
	corepack pnpm exec playwright test e2e/auth.user.spec.ts e2e/auth.admin.spec.ts

auth-verify: auth-migrate auth-seed auth-test auth-security-test auth-e2e
	$(MAKE) verify

cms-migrate:
	docker compose exec -T api alembic upgrade head

cms-seed:
	docker compose exec -T api python -m vav.cli.seed_cms

cms-test:
	docker compose exec -T api pytest tests/content -q

cms-security-test:
	docker compose exec -T api pytest tests/content/security -q

cms-user-e2e:
	corepack pnpm exec playwright test e2e/cms.spec.ts

cms-admin-e2e:
	corepack pnpm exec playwright test e2e/cms.admin.spec.ts e2e/media.admin.spec.ts e2e/navigation.admin.spec.ts

i18n-check:
	corepack pnpm --recursive --if-present i18n:check

cms-verify: cms-migrate cms-seed i18n-check cms-test cms-security-test cms-user-e2e cms-admin-e2e
	$(MAKE) auth-verify

catalog-migrate:
	docker compose exec -T api alembic upgrade head

catalog-seed:
	docker compose exec -T api python -m vav.cli.seed_catalog

catalog-test:
	docker compose exec -T api pytest tests/catalog/unit tests/catalog/integration -q

catalog-concurrency-test:
	docker compose exec -T api pytest tests/catalog/concurrency -q

catalog-security-test:
	docker compose exec -T api pytest tests/catalog/security -q

catalog-user-e2e:
	corepack pnpm exec playwright test e2e/catalog.spec.ts

catalog-admin-e2e:
	corepack pnpm exec playwright test e2e/catalog.spec.ts

catalog-verify: catalog-migrate catalog-seed catalog-test catalog-concurrency-test catalog-security-test catalog-user-e2e catalog-admin-e2e
	$(MAKE) cms-verify

commerce-migrate:
	docker compose exec -T api alembic upgrade head

commerce-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_commerce

commerce-test:
	docker compose exec -T api pytest tests/commerce/unit tests/commerce/integration -q

commerce-webhook-test:
	docker compose exec -T api pytest tests/commerce/webhook -q

commerce-concurrency-test:
	docker compose exec -T api pytest tests/commerce/concurrency -q

commerce-security-test:
	docker compose exec -T api pytest tests/commerce/security -q

commerce-user-e2e:
	corepack pnpm exec playwright test e2e/commerce.user.spec.ts

commerce-admin-e2e:
	corepack pnpm exec playwright test e2e/commerce.admin.spec.ts

commerce-reconcile:
	docker compose exec -T api python -m vav.cli.reconcile_payments

commerce-verify: commerce-migrate commerce-seed commerce-test commerce-webhook-test commerce-concurrency-test commerce-security-test commerce-user-e2e commerce-admin-e2e commerce-reconcile
	$(MAKE) catalog-verify

activity-migrate:
	docker compose exec -T api alembic upgrade head

activity-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_catalog
	docker compose exec -T api python -m vav.cli.seed_activities

activity-test:
	docker compose exec -T api pytest tests/activities/unit tests/activities/integration -q

activity-concurrency-test:
	docker compose exec -T api pytest tests/activities/concurrency -q

activity-security-test:
	docker compose exec -T api pytest tests/activities/security -q

activity-user-e2e:
	corepack pnpm exec playwright test e2e/activities.user.spec.ts

activity-admin-e2e:
	corepack pnpm exec playwright test e2e/activities.admin.spec.ts

activity-verify: activity-migrate activity-seed activity-test activity-concurrency-test activity-security-test activity-user-e2e activity-admin-e2e
	$(MAKE) commerce-verify

course-migrate:
	docker compose exec -T api alembic upgrade head

course-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_catalog
	docker compose exec -T api python -m vav.cli.seed_courses

course-test:
	docker compose exec -T api pytest tests/courses/unit tests/courses/integration -q

course-concurrency-test:
	docker compose exec -T api pytest tests/courses/concurrency -q

course-security-test:
	docker compose exec -T api pytest tests/courses/security -q

course-user-e2e:
	corepack pnpm exec playwright test e2e/courses.user.spec.ts

course-admin-e2e:
	corepack pnpm exec playwright test e2e/courses.admin.spec.ts

course-verify: course-migrate course-seed course-test course-concurrency-test course-security-test course-user-e2e course-admin-e2e
	$(MAKE) activity-verify

counseling-migrate:
	docker compose exec -T api alembic upgrade head

counseling-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_catalog
	docker compose exec -T api python -m vav.cli.seed_counseling

counseling-test:
	docker compose exec -T api pytest tests/counseling/unit tests/counseling/integration -q

counseling-concurrency-test:
	docker compose exec -T api pytest tests/counseling/concurrency -q

counseling-security-test:
	docker compose exec -T api pytest tests/counseling/security -q

counseling-user-e2e:
	corepack pnpm exec playwright test e2e/counseling.user.spec.ts

counseling-admin-e2e:
	corepack pnpm exec playwright test e2e/counseling.admin.spec.ts

counseling-verify: counseling-migrate counseling-seed counseling-test counseling-concurrency-test counseling-security-test counseling-user-e2e counseling-admin-e2e
	$(MAKE) course-verify

knowledge-migrate:
	docker compose exec -T api alembic upgrade head

knowledge-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_knowledge

knowledge-ingest-fixtures:
	docker compose exec -T api python -m vav.cli.ingest_knowledge_fixtures

knowledge-build-index:
	docker compose exec -T api python -m vav.cli.build_knowledge_index

knowledge-test:
	docker compose exec -T api pytest tests/knowledge/unit tests/knowledge/integration -q

knowledge-retrieval-test:
	docker compose exec -T api pytest tests/knowledge/retrieval -q

knowledge-security-test:
	docker compose exec -T api pytest tests/knowledge/security -q

knowledge-eval:
	docker compose exec -T api python -m vav.cli.run_knowledge_evaluation

knowledge-admin-e2e:
	corepack pnpm exec playwright test e2e/knowledge.admin.spec.ts

knowledge-verify: knowledge-migrate knowledge-seed knowledge-ingest-fixtures knowledge-build-index knowledge-test knowledge-retrieval-test knowledge-security-test knowledge-eval knowledge-admin-e2e
	$(MAKE) counseling-verify
