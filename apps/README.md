# `apps/` in this repository is a retired mirror

The deployed C-end and admin front ends live in the sibling repository
**`vavactivityWeb`** (`git remote -v` here lists it as `web`). That is what
Vercel builds and what members and operators actually load.

The `apps/` tree in this backend repository is a historical copy. It is no
longer built, tested, or deployed from here.

## Do not edit anything under `apps/` in this repository

A change made here reaches nobody. Worse, it looks like it worked: the files
are real, the imports resolve, and an editor will happily typecheck them
against this repository's copy of `packages/`.

That is not a hypothetical. Six complete features — post-event closure,
matchmaking access, discovery, couples/SCOPE, paid assessments and the member
dashboard — were built here against live backend endpoints and sat unreachable
because the pages only ever existed in this mirror. They were ported to
`vavactivityWeb` on 2026-08-14; as of that date the two trees carry the same
feature set.

## Where to make a front-end change

```
git clone https://github.com/zpcaiai/vavactivityWeb.git
```

Then edit `apps/user-web` or `apps/admin-web` there.

## Why this mirror still exists

It is kept, rather than deleted, so the history of the split stays readable:
several features were authored here before the repository split and `git log`
on these paths is still the only record of that. Treat it as read-only
history, not as source.
