# Recommendation projections

Build projections only from the approved version, carrying normalised codes and nothing else.
An unexpected key fails closed. Names, contact details, exact birth dates, narratives, raw photo
locations and internal notes can never appear. Pause, suspension, privacy withdrawal, age
ineligibility and an inactive account all remove the member from the pool. Rebuilds are idempotent
and the checksum covers the profile, preference and privacy versions.
