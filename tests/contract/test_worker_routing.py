from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

import vav_worker.tasks  # noqa: F401  # Register every production task.
from vav_worker.celery_app import celery_app
from vav_worker.tasks import PRIVACY_ERASURE_RUNNABLE_STATUSES

ROOT = Path(__file__).resolve().parents[2]


def _queue_arguments(command: list[str]) -> set[str]:
    queues: set[str] = set()
    for index, argument in enumerate(command):
        value: str | None = None
        if argument.startswith("--queues="):
            value = argument.removeprefix("--queues=")
        elif argument == "--queues" and index + 1 < len(command):
            value = command[index + 1]
        if value:
            queues.update(queue.strip() for queue in value.split(",") if queue.strip())
    return queues


def _compose_worker_queues(path: Path) -> set[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    services: dict[str, dict[str, Any]] = document["services"]
    queues: set[str] = set()
    for name, service in services.items():
        if name == "worker" or name.startswith("worker-"):
            queues.update(_queue_arguments(service.get("command", [])))
    return queues


def _kubernetes_worker_queues(path: Path) -> set[str]:
    queues: set[str] = set()
    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if not document or document.get("kind") != "Deployment":
            continue
        if not document.get("metadata", {}).get("name", "").startswith("worker-"):
            continue
        container = document["spec"]["template"]["spec"]["containers"][0]
        queues.update(_queue_arguments(container["args"]))
    return queues


def _route_queue(task_name: str) -> str:
    queue = celery_app.amqp.router.route({}, task_name)["queue"]
    return str(queue.name)


def test_every_registered_and_scheduled_task_routes_to_deployed_workers() -> None:
    registered = {name for name in celery_app.tasks if name.startswith("vav.")}
    scheduled = {
        definition["task"] for definition in celery_app.conf.beat_schedule.values()
    }
    assert scheduled <= registered

    routed_queues = {_route_queue(name) for name in registered | scheduled}
    assert "celery" not in routed_queues
    assert routed_queues <= _compose_worker_queues(
        ROOT / "deploy/compose/docker-compose.dev.yml"
    )
    assert routed_queues <= _compose_worker_queues(
        ROOT / "deploy/compose/docker-compose.prod.yml"
    )
    assert routed_queues <= _kubernetes_worker_queues(
        ROOT / "deploy/kubernetes/base/worker-deployments.yaml"
    )


def test_routing_keeps_sensitive_and_domain_workloads_isolated() -> None:
    assert celery_app.conf.task_default_queue == "default"
    assert _route_queue("vav.profile_media.maintain_storage") == "privacy"
    assert _route_queue("vav.privacy.erasures") == "privacy"
    assert _route_queue("vav.notifications.deliver") == "notifications"
    assert _route_queue("vav.safety.escalate_cases") == "safety"
    assert _route_queue("vav.recommendations.generate_batches") == "recommendations"
    assert _route_queue("vav.future.unmapped_task") == "default"


def test_development_workers_bound_database_connection_amplification() -> None:
    document = yaml.safe_load(
        (ROOT / "deploy/compose/docker-compose.dev.yml").read_text(encoding="utf-8")
    )
    services: dict[str, dict[str, Any]] = document["services"]
    worker_commands = {
        name: service.get("command", [])
        for name, service in services.items()
        if name == "worker" or name.startswith("worker-")
    }

    assert worker_commands
    for command in worker_commands.values():
        assert "--concurrency=1" in command


def test_privacy_worker_retries_incomplete_erasure_plans() -> None:
    assert PRIVACY_ERASURE_RUNNABLE_STATUSES == (
        "ready",
        "processing",
        "partially_completed",
    )
