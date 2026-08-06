---
name: vav-safety-events-integrations-notifications
description: Publish idempotent safety events and expose only safe-output decisions to modules.
---

Business modules call the gateway and receive allow/action/reason/version only. Blocks invalidate
recommendations, interactions, grants, journeys and reminders transactionally; restrictions publish
versioned events. User notifications are minimal and never reveal reporter or investigator identity.
