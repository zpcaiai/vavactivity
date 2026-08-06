# Kubernetes deployment

Render before application:

```bash
kubectl kustomize deploy/kubernetes/overlays/staging
kubectl kustomize deploy/kubernetes/overlays/production
```

The base contains restricted namespace policy, config references, ExternalSecret references, read-only JWT key mounts, migration job, API and specialized workers, web services, TLS ingress, default-deny network policies, disruption budgets, and autoscalers. Overlays set isolated environment namespaces and secret-store paths. Release rendering binds every workload to the approved immutable image identities.

The all-zero digest in the checked-in reference is a non-deployable placeholder. Release automation verifies the release-manifest checksum and release/commit identity, replaces every image with a verified digest, and rejects `latest`. It applies configuration plus the migration job first, waits for completion, and only then applies application workloads. Never expose worker, scheduler, PostgreSQL, Redis, or object-storage administrative ports through ingress.
