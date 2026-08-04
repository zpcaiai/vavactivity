# Viewer-specific projections

The backend decides what each viewer receives. Every context — self, admin review,
recommendation card, profile detail, activity directory, mutual match, introduction accepted and
AI context — has its own section allow-list and sensitivity ceiling. Frontend hiding is not
field-level privacy. Contact details are never released by any context, mutual match included.
AI context additionally requires the Batch 12 profile-access consent.
