# Ranking, adjustments and diversification

Ranking is deterministic for a fixed (strategy, candidate snapshot, seed), so refreshing a page
never reshuffles a batch. Novelty, repeat-exposure and popularity adjustments are reported
separately from the raw compatibility score — an exposure penalty must never masquerade as a
lower match. Diversification is maximal marginal relevance over candidates that already passed
eligibility, hard constraints and the score floors: it reorders, it never admits. A policy that
claims it may bypass hard constraints is refused outright. A per-city cap must never produce an
under-filled batch.
