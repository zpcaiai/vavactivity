def test_course_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/courses" in paths
    assert "/api/v1/courses/{slug}" in paths
    assert "/api/v1/public/courses" in paths
    assert "/api/v1/public/courses/{course_id}/curriculum" in paths
    assert "/api/v1/public/courses/{course_id}/access-summary" in paths
    assert "/api/v1/public/courses/{course_id}/lessons/{lesson_id}" in paths
    assert "/api/v1/courses/{course_id}/enroll" in paths
    assert "/api/v1/account/courses/{enrollment_id}" in paths
    assert (
        "/api/v1/account/courses/{enrollment_id}/exercises/{exercise_id}/attempts"
        in paths
    )
    assert "/api/v1/account/exercise-attempts/{attempt_id}/submit" in paths
    assert "/api/v1/account/exercise-attempts/{attempt_id}/draft" in paths
    assert "/api/v1/admin/courses" in paths
    assert "/api/v1/admin/courses/{course_id}" in paths
    assert "/api/v1/admin/courses/{course_id}/catalog-mappings" in paths
    assert "/api/v1/admin/courses/{course_id}/submit-review" in paths
    assert "/api/v1/admin/courses/{course_id}/publish" in paths
    assert "/api/v1/admin/course-instructors" in paths
    assert "/api/v1/admin/course-enrollments" in paths
    assert "/api/v1/admin/course-certificates" in paths
    assert "/api/v1/certificates/verify/{verification_token}" in paths
    assert "/api/v1/account/course-certificates" in paths


def test_seeded_public_course_has_curriculum_but_no_private_video_reference(client) -> None:
    response = client.get("/api/v1/courses/healthy-relationship-foundations?locale=zh-CN")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["title"] == "健康关系基础课"
    assert len(body["modules"]) == 1
    assert len(body["modules"][0]["lessons"]) == 2
    assert "private_reference" not in response.text
    assert "s3://" not in response.text
    assert body["free_enrollment"] is True
    assert body["prices"][0]["unit_amount_minor"] >= 0
    assert len(body["prices"][0]["currency"]) == 3


def test_only_explicit_public_preview_lessons_are_exposed(client) -> None:
    detail = client.get(
        "/api/v1/public/courses/healthy-relationship-foundations?locale=zh-CN"
    ).json()["data"]
    course_id = detail["id"]
    lessons = detail["modules"][0]["lessons"]
    public_lesson = next(item for item in lessons if item["preview_policy"] == "public")
    private_lesson = next(item for item in lessons if item["preview_policy"] == "none")

    preview = client.get(
        f"/api/v1/public/courses/{course_id}/lessons/{public_lesson['id']}?locale=zh-CN"
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["preview"] is True

    denied = client.get(
        f"/api/v1/public/courses/{course_id}/lessons/{private_lesson['id']}?locale=zh-CN"
    )
    assert denied.status_code == 404
    assert "private_reference" not in denied.text
