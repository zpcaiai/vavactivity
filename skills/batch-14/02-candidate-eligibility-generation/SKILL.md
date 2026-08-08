---
name: vav-batch-14-02-candidate-eligibility-generation
description: "Implement Candidate eligibility and generation for the VAV platform."
---

# Candidate eligibility and generation

The recommendation pool is built only from approved projections. A member enters
it with an active account, an active profile, an approved version, adult
eligibility, valid preferences and their own consent; anything else records a
reason code instead. Recall filters on normalised columns in SQL — mutual
relationship eligibility and the adult rule — so the full pool never lands in
memory. Safety, block, relationship and cooldown exclusions apply before
scoring, and a moderation failure fails closed. Every stage is counted so an
operator can see where candidates were lost without learning who excluded whom.
