# Information architecture

Batch 23 owns a versioned, task-oriented information architecture. The canonical source is `config/experience/information-architecture.yaml`; activated versions are immutable projections in `experience_ia_versions` and `experience_ia_nodes`.

User navigation uses public, account, services, matchmaking, safety/privacy spaces. Administrator and Skill Console destinations remain separate. Every critical node has one primary route; shortcuts must resolve to that route. Retired nodes require a redirect or migration explanation.

The user home orders safety, privacy and payment tasks before owned services, suggestions, discovery and marketing. Navigation visibility is never authorization: direct URL requests remain backend guarded.
