from vav.modules.courses.domain import monotonic_progress


def test_out_of_order_progress_candidates_converge_monotonically() -> None:
    value = 0
    for candidate in (3000, 7000, 2000, 10000, 9000):
        value = monotonic_progress(value, candidate)
    assert value == 10000
