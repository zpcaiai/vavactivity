# AI provider failure

## Symptoms and impact

AI turns, embeddings, or retrieval time out or produce invalid responses; core platform functions remain available.

## Detect

Check provider latency/errors, circuit breaker, evaluation regressions, referral/safety outcomes, and AI queue age.

## Immediate containment

Open the circuit, use only approved compatible fallback, or return a safe unavailable response. Never skip risk detection, consent, tool authorization, or human referral.

## Recovery

Restore provider access, validate model/version/tool contracts with synthetic prompts, drain non-urgent work gradually, and preserve conversation privacy controls.

## Verification and rollback

Run deterministic safety, citation, tool-confirmation, prompt-injection, and high-risk referral tests. Disable the provider again if any guard fails.

## Communication and review

Describe AI degradation without claiming human support occurred. Review provider change, prompts, evaluations, fallbacks, and privacy impact.
