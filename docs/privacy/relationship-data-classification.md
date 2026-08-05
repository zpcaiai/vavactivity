# Relationship Data Classification

| Data | Classification | Member visibility | Operator visibility | Storage |
| --- | --- | --- | --- | --- |
| Journey status/stage | confidential | both participants | pseudonymous process view | relational |
| Stage proposal direction/status | confidential | both participants | permitted process view | relational |
| Proposal/ending visible message | restricted | intended partner | sensitive-purpose only | encrypted |
| Pause/end private reason | highly restricted | author only | break-glass/safety only | encrypted |
| Shared milestone | confidential | both participants | process metadata only | encrypted description |
| Private milestone/reflection | highly restricted | author only | no routine access | encrypted |
| Check-in response | highly restricted | author unless explicitly shared | no routine access | encrypted |
| Status history/outbox | controlled | safe event summary | permitted process view | no free text |

AI processing is off by default. Supplying a consent identifier is insufficient: the record must
belong to the author, be active and unexpired, cover AI long-term memory, and the current privacy
preference must explicitly allow relationship context. Exports/erasure/holds use Batch 12 policy.

Do not log, trace, cache or place private text into outbox payloads. Do not expose decline reasons,
reports, blocks or the identity of a safety actor to the other participant.
