.PHONY: role-function-audit role-function-test role-identity-test role-function-web-test role-function-browser-test role-function-verify

role-function-audit:
	PYTHONPATH=services/api/src .venv/bin/python scripts/testing/role_function_matrix.py

role-function-test:
	PYTHONPATH=.:services/api/src .venv/bin/pytest -p no:cacheprovider -o addopts= tests/roles -q

role-identity-test:
	PYTHONPATH=services/api/src .venv/bin/pytest -p no:cacheprovider -o addopts= services/api/tests/identity -q

role-function-web-test:
	./scripts/web-pnpm --filter @vav/admin-web --filter @vav/user-web test
	./scripts/web-pnpm --filter @vav/admin-web --filter @vav/user-web typecheck

role-function-browser-test:
	./scripts/testing/run_role_browser_tests.sh

role-function-verify: role-function-audit role-function-test role-identity-test role-function-web-test
