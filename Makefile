.PHONY: doctor bootstrap up down dev stop reset reset-local migrate seed smoke lint test verify openapi \
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
	knowledge-admin-e2e knowledge-verify \
	ai-migrate ai-seed ai-test ai-safety-test ai-concurrency-test ai-eval \
	ai-user-e2e ai-admin-e2e ai-verify \
	notification-migrate notification-seed notification-seed-templates notification-test \
	notification-concurrency-test notification-security-test notification-provider-test \
	notification-user-e2e notification-admin-e2e notification-verify \
	dating-profile-migrate dating-profile-seed dating-profile-seed-taxonomies dating-profile-test \
	dating-profile-concurrency-test dating-profile-security-test dating-profile-user-e2e \
	dating-profile-admin-e2e dating-profile-verify \
	privacy-migrate privacy-seed privacy-seed-inventory privacy-test privacy-security-test \
	privacy-concurrency-test privacy-retention-test privacy-user-e2e privacy-admin-e2e privacy-verify

.PHONY: recommendation-migrate recommendation-seed recommendation-seed-evaluations \
	recommendation-build-pool recommendation-generate-fixtures recommendation-test \
	recommendation-concurrency-test recommendation-security-test recommendation-fairness-test \
	recommendation-eval recommendation-user-e2e recommendation-admin-e2e recommendation-verify \
	interaction-migrate interaction-seed interaction-test interaction-concurrency-test \
	interaction-security-test interaction-privacy-test interaction-user-e2e \
	interaction-admin-e2e interaction-verify

.PHONY: relationship-migrate relationship-seed relationship-seed-stages relationship-test \
	relationship-concurrency-test relationship-security-test relationship-privacy-test \
	relationship-user-e2e relationship-admin-e2e relationship-browser-local relationship-verify

.PHONY: membership-browser-local

.PHONY: safety-migrate safety-seed safety-seed-rules safety-test safety-concurrency-test \
	safety-security-test safety-privacy-test safety-red-team safety-user-e2e \
	safety-admin-e2e safety-verify

bootstrap:
	./scripts/vavctl bootstrap

doctor:
	./scripts/vavctl doctor

up:
	./scripts/vavctl up

down:
	./scripts/vavctl down

dev:
	./scripts/vavctl up

stop:
	./scripts/vavctl down

reset:
	./scripts/vavctl reset-local

reset-local:
	./scripts/vavctl reset-local

migrate:
	./scripts/vavctl migrate

seed:
	./scripts/vavctl seed

smoke:
	./scripts/vavctl smoke

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
	./scripts/web-pnpm exec playwright test e2e/auth.user.spec.ts e2e/auth.admin.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/cms.spec.ts

cms-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/cms.admin.spec.ts e2e/media.admin.spec.ts e2e/navigation.admin.spec.ts

i18n-check:
	./scripts/web-pnpm --recursive --if-present i18n:check

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
	./scripts/web-pnpm exec playwright test e2e/catalog.spec.ts

catalog-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/catalog.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/commerce.user.spec.ts

commerce-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/commerce.admin.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/activities.user.spec.ts

activity-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/activities.admin.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/courses.user.spec.ts

course-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/courses.admin.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/counseling.user.spec.ts

counseling-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/counseling.admin.spec.ts

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
	./scripts/web-pnpm exec playwright test e2e/knowledge.admin.spec.ts

knowledge-verify: knowledge-migrate knowledge-seed knowledge-ingest-fixtures knowledge-build-index knowledge-test knowledge-retrieval-test knowledge-security-test knowledge-eval knowledge-admin-e2e
	$(MAKE) counseling-verify

ai-migrate:
	docker compose exec -T api alembic upgrade head

ai-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_ai_assistant

ai-test:
	docker compose exec -T api pytest tests/ai_assistant/unit tests/ai_assistant/integration -q

ai-safety-test:
	docker compose exec -T api pytest tests/ai_assistant/safety tests/ai_assistant/security -q

ai-concurrency-test:
	docker compose exec -T api pytest tests/ai_assistant/concurrency -q

ai-eval:
	docker compose exec -T api python -m vav.cli.run_ai_evaluation

ai-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/ai.user.spec.ts

ai-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/ai.admin.spec.ts

ai-verify: ai-migrate ai-seed ai-test ai-safety-test ai-concurrency-test ai-eval ai-user-e2e ai-admin-e2e
	$(MAKE) knowledge-verify

notification-migrate:
	docker compose exec -T api alembic upgrade head

notification-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_notifications

notification-seed-templates:
	docker compose exec -T api python -m vav.cli.seed_notification_templates

notification-test:
	docker compose exec -T api pytest tests/notifications/unit tests/notifications/integration -q

notification-concurrency-test:
	docker compose exec -T api pytest tests/notifications/concurrency -q

notification-security-test:
	docker compose exec -T api pytest tests/notifications/security -q

notification-provider-test:
	docker compose exec -T api pytest tests/notifications/providers -q

notification-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/notifications.user.spec.ts

notification-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/notifications.admin.spec.ts

notification-verify: notification-migrate notification-seed-templates notification-seed notification-test notification-concurrency-test notification-security-test notification-provider-test notification-user-e2e notification-admin-e2e
	$(MAKE) ai-verify

privacy-migrate:
	docker compose exec -T api alembic upgrade head

privacy-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_privacy

privacy-seed-inventory:
	docker compose exec -T api python -m vav.cli.seed_privacy_inventory

privacy-test:
	docker compose exec -T api pytest tests/privacy/unit tests/privacy/integration -q

privacy-security-test:
	docker compose exec -T api pytest tests/privacy/security -q

privacy-concurrency-test:
	docker compose exec -T api pytest tests/privacy/concurrency -q

privacy-retention-test:
	docker compose exec -T api pytest tests/privacy/retention -q

privacy-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-privacy

privacy-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-privacy

privacy-verify: privacy-migrate privacy-seed privacy-seed-inventory privacy-test privacy-security-test privacy-concurrency-test privacy-retention-test privacy-user-e2e privacy-admin-e2e
	$(MAKE) notification-verify

dating-profile-migrate:
	docker compose exec -T api alembic upgrade head

dating-profile-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_dating_profiles

dating-profile-seed-taxonomies:
	docker compose exec -T api python -m vav.cli.seed_dating_taxonomies

dating-profile-test:
	docker compose exec -T api pytest tests/matchmaking_profiles/unit tests/matchmaking_profiles/integration -q

dating-profile-concurrency-test:
	docker compose exec -T api pytest tests/matchmaking_profiles/concurrency -q

dating-profile-security-test:
	docker compose exec -T api pytest tests/matchmaking_profiles/security -q

dating-profile-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-dating-profile

dating-profile-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-dating-profile

dating-profile-verify:
	$(MAKE) dating-profile-migrate
	$(MAKE) dating-profile-seed-taxonomies
	$(MAKE) dating-profile-seed
	$(MAKE) dating-profile-test
	$(MAKE) dating-profile-concurrency-test
	$(MAKE) dating-profile-security-test
	$(MAKE) dating-profile-user-e2e
	$(MAKE) dating-profile-admin-e2e

recommendation-migrate:
	docker compose exec -T api alembic upgrade head

recommendation-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_recommendations

recommendation-seed-evaluations:
	docker compose exec -T api python -m vav.cli.seed_recommendation_evaluations

recommendation-build-pool:
	docker compose exec -T api python -m vav.cli.seed_recommendation_fixtures
	docker compose exec -T api python -m vav.cli.build_recommendation_pool

recommendation-generate-fixtures:
	docker compose exec -T api python -m vav.cli.generate_recommendation_fixture_batches

recommendation-test:
	docker compose exec -T api pytest tests/recommendations/unit tests/recommendations/integration -q

recommendation-concurrency-test:
	docker compose exec -T api pytest tests/recommendations/concurrency -q

recommendation-security-test:
	docker compose exec -T api pytest tests/recommendations/security -q

recommendation-fairness-test:
	docker compose exec -T api pytest tests/recommendations/fairness -q

recommendation-eval:
	docker compose exec -T api python -m vav.cli.run_recommendation_evaluation

recommendation-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-recommendations

recommendation-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-recommendations

recommendation-verify:
	$(MAKE) recommendation-migrate
	$(MAKE) recommendation-seed
	$(MAKE) recommendation-seed-evaluations
	$(MAKE) recommendation-build-pool
	$(MAKE) recommendation-generate-fixtures
	$(MAKE) recommendation-test
	$(MAKE) recommendation-concurrency-test
	$(MAKE) recommendation-security-test
	$(MAKE) recommendation-fairness-test
	$(MAKE) recommendation-eval
	$(MAKE) recommendation-user-e2e
	$(MAKE) recommendation-admin-e2e

interaction-migrate:
	docker compose exec -T api alembic upgrade head

interaction-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_matchmaking_interactions

interaction-test:
	docker compose exec -T api pytest tests/matchmaking_interactions/unit tests/matchmaking_interactions/integration -q

interaction-concurrency-test:
	docker compose exec -T api pytest tests/matchmaking_interactions/concurrency -q

interaction-security-test:
	docker compose exec -T api pytest tests/matchmaking_interactions/security -q

interaction-privacy-test:
	docker compose exec -T api pytest tests/matchmaking_interactions/privacy -q

interaction-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-matchmaking-interactions

interaction-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-matchmaking-interactions

interaction-verify:
	$(MAKE) interaction-migrate
	$(MAKE) interaction-seed
	$(MAKE) interaction-test
	$(MAKE) interaction-concurrency-test
	$(MAKE) interaction-security-test
	$(MAKE) interaction-privacy-test
	$(MAKE) interaction-user-e2e
	$(MAKE) interaction-admin-e2e

relationship-migrate:
	docker compose exec -T api alembic upgrade head

relationship-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_relationships

relationship-seed-stages:
	docker compose exec -T api python -m vav.cli.seed_relationships

relationship-test:
	docker compose exec -T api pytest tests/relationships/unit tests/relationships/integration -q

relationship-concurrency-test:
	docker compose exec -T api pytest tests/relationships/concurrency -q

relationship-security-test:
	docker compose exec -T api pytest tests/relationships/security -q

relationship-privacy-test:
	docker compose exec -T api pytest tests/relationships/privacy -q

relationship-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-relationships

relationship-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-relationships

relationship-browser-local:
	VAV_E2E_SEED_MODE=local ./scripts/web-pnpm run test:e2e:batch16

relationship-verify:
	$(MAKE) relationship-migrate
	$(MAKE) relationship-seed
	$(MAKE) relationship-test
	$(MAKE) relationship-concurrency-test
	$(MAKE) relationship-security-test
	$(MAKE) relationship-privacy-test
	$(MAKE) relationship-user-e2e
	$(MAKE) relationship-admin-e2e

membership-migrate:
	docker compose exec -T api alembic upgrade head

membership-seed:
	docker compose exec -T api python -m vav.cli.seed_permissions
	docker compose exec -T api python -m vav.cli.seed_memberships

membership-seed-benefits:
	docker compose exec -T api python -m vav.cli.seed_memberships

membership-test:
	docker compose exec -T api pytest tests/memberships/unit tests/memberships/integration -q

membership-concurrency-test:
	docker compose exec -T api pytest tests/memberships/concurrency -q

membership-security-test:
	docker compose exec -T api pytest tests/memberships/security -q

membership-reconciliation-test:
	docker compose exec -T api pytest tests/memberships/reconciliation -q

membership-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-memberships

membership-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-memberships

membership-browser-local:
	VAV_E2E_SEED_MODE=local ./scripts/web-pnpm run test:e2e:batch17

membership-verify:
	$(MAKE) membership-migrate
	$(MAKE) membership-seed
	$(MAKE) membership-test
	$(MAKE) membership-concurrency-test
	$(MAKE) membership-security-test
	$(MAKE) membership-reconciliation-test
	$(MAKE) membership-user-e2e
	$(MAKE) membership-admin-e2e

safety-migrate:
	docker compose exec api alembic upgrade head

safety-seed:
	docker compose exec api python -m vav.cli.seed_trust_safety

safety-seed-rules:
	docker compose exec api python -m vav.cli.seed_trust_safety

safety-test:
	docker compose exec api pytest tests/trust_safety/unit tests/trust_safety/integration -q

safety-concurrency-test:
	docker compose exec api pytest tests/trust_safety/concurrency -q

safety-security-test:
	docker compose exec api pytest tests/trust_safety/security -q

safety-privacy-test:
	docker compose exec api pytest tests/trust_safety/privacy -q

safety-red-team:
	docker compose exec api pytest tests/trust_safety/red_team -q

safety-user-e2e:
	./scripts/web-pnpm exec playwright test e2e/user-trust-safety

safety-admin-e2e:
	./scripts/web-pnpm exec playwright test e2e/admin-trust-safety

safety-verify:
	$(MAKE) safety-migrate
	$(MAKE) safety-seed
	$(MAKE) safety-seed-rules
	$(MAKE) safety-test
	$(MAKE) safety-concurrency-test
	$(MAKE) safety-security-test
	$(MAKE) safety-privacy-test
	$(MAKE) safety-red-team
	$(MAKE) safety-user-e2e
	$(MAKE) safety-admin-e2e

.PHONY: manifest-check config-check config-diff migration-check contract-test system-test \
	complete-e2e performance-smoke performance-k6-baseline backup backup-verify restore-drill \
	restore-smoke production-readiness verify-all acceptance external-browser-uat \
	external-performance-local external-security-local external-resilience-local external-observation-sample

manifest-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/validate_project_manifest.py

config-check:
	PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/validate_environment_config.py

config-diff:
	PYTHONPATH=services/api/src .venv/bin/python scripts/diagnostics/config_diff.py $(or $(ENVIRONMENT),staging)

migration-check:
	./scripts/database/check-migrations.sh

contract-test:
	.venv/bin/pytest tests/contract -q

system-test:
	.venv/bin/pytest services/api/tests/system -q

complete-e2e:
	./scripts/web-pnpm exec playwright test --config playwright.config.ts --workers=1

performance-smoke:
	./scripts/performance/run-k6.sh tests/performance/smoke.js

performance-k6-baseline:
	./scripts/performance/run-k6.sh tests/performance/baseline.js

external-browser-uat:
	cd ../vavactivityWeb && env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY NO_PROXY=127.0.0.1,localhost pnpm test:e2e:external-uat

external-performance-local:
	K6_PROFILE=local EVIDENCE_SCOPE=local_compose ./scripts/performance/run-external-suite.sh

external-security-local:
	.venv/bin/python scripts/security/run_blackbox_security.py

external-resilience-local:
	./scripts/resilience/run-local-resilience-suite.sh

external-observation-sample:
	.venv/bin/python scripts/observability/observe_release.py sample

backup:
	./scripts/vavctl backup

backup-verify:
	./scripts/vavctl backup-verify

restore-drill:
	./scripts/vavctl restore-drill

restore-smoke:
	./scripts/restore/restore-smoke.sh

production-readiness:
	./scripts/release/production-readiness.sh

verify-all: manifest-check config-check migration-check verify safety-verify contract-test system-test complete-e2e performance-smoke

acceptance: bootstrap smoke verify-all production-readiness

.PHONY: skill-catalog-check skill-sdk-test skill-schema-test skill-runtime-test skill-registry-test skill-security-test \
	skill-marketplace-test skill-complete-e2e skill-verify

skill-catalog-check:
	.venv/bin/python scripts/skill/validate_catalog.py

skill-sdk-test:
	.venv/bin/pytest tests/skill-sdk -q
	./scripts/web-pnpm --filter @vav/skill-sdk test
	./scripts/web-pnpm --filter @vav/skill-sdk typecheck
	./scripts/web-pnpm --filter @vav/skill-ui-sdk test
	./scripts/web-pnpm --filter @vav/skill-ui-sdk typecheck

skill-schema-test:
	PYTHONPATH=packages/skill-sdk-python/src .venv/bin/python scripts/skill/validate_all_schemas.py

skill-runtime-test:
	.venv/bin/pytest tests/skill-runtime -q

skill-registry-test:
	.venv/bin/pytest tests/skill-registry -q

skill-security-test:
	.venv/bin/pytest tests/skill-security -q

skill-marketplace-test:
	docker compose exec -T api pytest tests/skills_platform -q
	.venv/bin/pytest tests/skill-marketplace -q

skill-complete-e2e:
	./scripts/web-pnpm exec playwright test e2e/skills.admin.spec.ts

skill-verify: skill-sdk-test skill-schema-test skill-runtime-test skill-registry-test skill-security-test skill-marketplace-test skill-complete-e2e

.PHONY: final-certification final-release

final-certification:
	.venv/bin/python scripts/certification/skill_platform.py \
		--mode "$${SKILL_CERTIFICATION_MODE:-architecture}" \
		$${SKILL_CERTIFICATION_EVIDENCE_DIR:+--evidence-dir "$$SKILL_CERTIFICATION_EVIDENCE_DIR"}

final-release: acceptance skill-verify final-certification
	@echo "Final release evidence generated; inspect production_certification before deployment."

# ---------------------------------------------------------------------------
# Batch 21-32 quality-governance targets. Each batch owns one fragment file so
# that batches can be developed independently without editing this Makefile.
# ---------------------------------------------------------------------------
-include make/batch-*.mk
