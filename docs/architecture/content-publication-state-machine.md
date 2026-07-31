# Content publication state machine

`draft -> in_review -> published`

`draft|in_review -> scheduled -> published`

`published -> draft` creates a new revision while the last published snapshot remains public.
`published|scheduled|draft -> archived -> draft` preserves all history. Publishing, archive
and restore operations require backend permissions and produce append-only security events.
