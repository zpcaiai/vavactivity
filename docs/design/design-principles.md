# VAV Design Principles

The interface exists to support clear, safe decisions. Prefer legible hierarchy, calm surfaces, explicit state, reversible action and privacy-minimized detail over novelty. Color is never the only status signal. Every critical action exposes its consequence, busy state, error recovery and durable outcome.

User experiences default to comfortable density and reading width. Administrator experiences may use compact density but retain 44px interactive targets. Locale, theme, reduced motion, keyboard use, safe-area insets and 360px width are first-class constraints.

Shared primitives live in `@vav/ui-core`; audience patterns live in `@vav/ui-user` and `@vav/ui-admin`. Product pages may compose them but must not fork token values or silently redefine interaction contracts.
