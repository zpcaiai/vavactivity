# Privacy Data Inventory

The executable inventory schema and module-provider contract cover Identity, Commerce,
Activities, Courses, Counseling, Knowledge, AI and Notifications with sensitivity,
purpose, export support, correction support, erasure mode and retention-policy references.
`vav.cli.seed_privacy_inventory` idempotently maintains the baseline rows for
`privacy_data_assets`, `privacy_processing_activities`, field classifications and bounded
retention policies. Batch 12 remains `foundation_in_progress` until the governed workflows
pass the named local and production gates; seeded policy placeholders are not legal approval.

No inventory entry is itself permission to process or disclose data. Undecided production
retention and external-processor policies remain release gates.
