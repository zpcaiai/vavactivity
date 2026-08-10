// Reuse the production-facing browser journey so the complete matrix cannot drift from module E2E.
import { installRateLimitReset } from "./rate-limit.fixture";
import "../../e2e/auth.user.spec";
installRateLimitReset();
