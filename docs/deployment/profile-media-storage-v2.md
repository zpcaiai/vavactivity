# Profile-media storage v2 release

Migration `20260813_0112` is an **expand** migration. It adds nullable storage
binding fields and a durable deletion queue. A database trigger binds writes
from a pre-0112 API to the legacy `profile-media/<token>` key before the
`active_storage_key` check runs. The trigger is intentionally retained for the
whole compatibility window.

The database compatibility does not make an old binary a valid reader for new
objects. Storage-v2 uploads use `profile-media/uploads/<token>` and inspected
objects use `profile-media/assets/<token>`; a pre-0112 binary always reads
`profile-media/<token>` and returns a storage 404. There is therefore no safe
single-step rollout with profile media left enabled.

## Required phases

1. Set `PROFILE_MEDIA_ENABLED=false` on the existing release and wait until
   every API replica returns `PROFILE_MEDIA_DISABLED` for a profile-media
   request. Keep the current image digest during this quiesce deployment.
2. Apply migration `20260813_0112`, then deploy the approved API and worker
   image digests while the flag remains false. The checked-in Compose,
   Kubernetes, production environment, and Render configurations all default
   to false for this reason.
3. Confirm the live database includes 0112 and has no unbound active rows:

   ```sql
   SELECT version_num FROM alembic_version;
   SELECT count(*) AS active_assets_without_storage_key
     FROM profile_media_assets
    WHERE state = 'active' AND storage_key IS NULL;
   ```

4. Confirm every API, worker, and scheduler replica is ready on the exact
   approved immutable backend image. Disable automatic rollback; after new
   objects exist, a pre-0112 image is not a rollback candidate.
5. Record those live facts in a JSON evidence file and run the activation gate:

   ```json
   {
     "database_revision": "20260813_0112",
     "profile_media_enabled": false,
     "automatic_rollback_enabled": false,
     "active_assets_without_storage_key": 0,
     "approved_workload_images": {
       "api": "registry.example/vav-api@sha256:<64 lowercase hex>",
       "worker-privacy": "registry.example/vav-worker@sha256:<64 lowercase hex>",
       "scheduler": "registry.example/vav-worker@sha256:<same worker digest>"
     },
     "workloads": [
       {"name": "api", "image": "registry.example/vav-api@sha256:<same api digest>", "ready_replicas": 2, "desired_replicas": 2},
       {"name": "worker-privacy", "image": "registry.example/vav-worker@sha256:<same worker digest>", "ready_replicas": 1, "desired_replicas": 1},
       {"name": "scheduler", "image": "registry.example/vav-worker@sha256:<same worker digest>", "ready_replicas": 1, "desired_replicas": 1}
     ]
   }
   ```

   ```bash
   uv run --package vav-platform-api python \
     scripts/release/profile_media_activation_gate.py \
     --evidence /secure/release/profile-media-activation.json \
     --required-workload api \
     --required-workload worker-privacy \
     --required-workload scheduler
   ```

   Add every backend workload present on the target platform as a repeated
   `--required-workload` argument. Do not omit a scaled-to-zero or unhealthy
   workload from the evidence to make the gate pass.
6. Change only `PROFILE_MEDIA_ENABLED` to true, retaining the same approved
   image digests, and roll all affected workloads. Then smoke register, storage
   POST, finalize, grant/read, delete, and physical deletion processing.

## Platform notes

For Docker Swarm, run the quiesce update as its own stack deployment before the
migration. `depends_on` is not a Swarm migration barrier. The production
reference uses `stop-first` plus `failure_action: pause`; it must not
automatically restore a pre-0112 task after activation. Plain Docker Compose
ignores `deploy.update_config`, so run the migration service explicitly and
wait for exit zero before recreating the API.

For Kubernetes/Argo CD, the 0112 migration is a `PreSync` hook and the base
ConfigMap keeps the feature false. The compatibility trigger makes the PreSync
window safe for old writers. Wait for every Deployment rollout, collect pod
image IDs/readiness for the evidence file, and only then patch the ConfigMap to
true and restart the same image. Kubernetes does not automatically roll back a
failed Deployment; do not use `kubectl rollout undo` to a pre-0112 revision.

For Render, leave the Blueprint value false while the Neon migration and exact
commit deployment complete. The only required workload is `api`, but its live
image identity and readiness still belong in the gate evidence. Enable the
environment value only after the gate passes.

## Containment and rollback

Before activation, keep the flag false and an old application may be restored
against the expanded schema. After activation, first set the flag false to
contain failures, then forward-fix or deploy another explicitly verified
storage-v2-compatible digest. Do not downgrade the database or restore a
pre-0112 image: neither action recreates the legacy object aliases that the old
reader expects.

Removing the legacy-binding trigger and making storage-v2 columns non-null are
contract-phase changes for a later release, after the old image and rollback
window have both been retired.
