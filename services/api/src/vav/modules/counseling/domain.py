from enum import StrEnum

from vav.common.exceptions import VavError


class AppointmentStatus(StrEnum):
    REQUESTED = "requested"
    PENDING_REVIEW = "pending_review"
    TIME_PROPOSED = "time_proposed"
    APPROVED_PENDING_PAYMENT = "approved_pending_payment"
    CONFIRMED = "confirmed"
    RESCHEDULE_REQUESTED = "reschedule_requested"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    MANUAL_REVIEW = "manual_review"


TRANSITIONS = {
    AppointmentStatus.REQUESTED: {AppointmentStatus.PENDING_REVIEW, AppointmentStatus.CANCELLED},
    AppointmentStatus.PENDING_REVIEW: {
        AppointmentStatus.TIME_PROPOSED,
        AppointmentStatus.APPROVED_PENDING_PAYMENT,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.REJECTED,
        AppointmentStatus.MANUAL_REVIEW,
    },
    AppointmentStatus.TIME_PROPOSED: {
        AppointmentStatus.APPROVED_PENDING_PAYMENT,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.PENDING_REVIEW,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.APPROVED_PENDING_PAYMENT: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.EXPIRED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.CONFIRMED: {
        AppointmentStatus.RESCHEDULE_REQUESTED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.RESCHEDULE_REQUESTED: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.MANUAL_REVIEW: {
        AppointmentStatus.PENDING_REVIEW,
        AppointmentStatus.REJECTED,
    },
    AppointmentStatus.REJECTED: set(),
    AppointmentStatus.CANCELLED: set(),
    AppointmentStatus.EXPIRED: set(),
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.NO_SHOW: set(),
}


def ensure_appointment_transition(current: str, target: str) -> None:
    try:
        source = AppointmentStatus(current)
        destination = AppointmentStatus(target)
    except ValueError as error:
        raise VavError(
            "APPOINTMENT_STATUS_INVALID", "Appointment status is invalid.", status_code=422
        ) from error
    if destination not in TRANSITIONS[source]:
        raise VavError(
            "APPOINTMENT_TRANSITION_INVALID",
            f"Appointment cannot transition from {source.value} to {destination.value}.",
            status_code=409,
        )
