# Email provider delivery

Keep Provider behavior behind an adapter. Development delivery uses Mailpit or Fake with no real
external send; production rejects both. Re-read verified destinations at send time, minimize
Provider metadata and retain stable idempotency and immutable rendering checksums.
