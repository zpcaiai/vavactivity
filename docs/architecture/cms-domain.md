# CMS domain

Pages, articles and testimonials share a versioned `content_entries` lifecycle. Locale data
is stored separately and UI translation files remain independent from editorial content.
Content is accepted only as discriminated, schema-validated blocks; arbitrary executable
HTML and unsafe link schemes are rejected.

Every mutation records an immutable snapshot. Public reads return only public published
content, or the most recent published snapshot while editors prepare a later draft.
Testimonials additionally require an approved consent record before publication.
