# Experience orchestration architecture

The experience module is a projection and routing control plane over existing domain modules. Versioned manifests seed IA, routes, tasks, journeys, handoffs and help. Runtime services apply identity/RBAC, restriction, ownership, expiry and integrity policies before returning destinations.

Search indexes approved projections only. Public, personal and administrator visibility are distinct; backend filters enforce ownership and permissions, while block and erasure flags remove results. Prohibited source types include one-sided likes, private reflections, evidence and payment secrets.

Support descriptions and handoff contexts are encrypted. Analytics accepts safe codes and allowlisted dimensions, never free-form private content. Audit events record governance and resolution decisions.
