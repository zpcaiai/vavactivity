# Profile schema and taxonomies

Version the field manifest and every controlled vocabulary. Value codes are the business
identifiers; localized labels live in `dating_taxonomy_localizations` and must never drive a
rule. Retire a value by disabling it so historical profiles stay interpretable. Activating a
schema release freezes its content — the trigger rejects edits to an active release.
