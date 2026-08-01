def test_knowledge_admin_contract_is_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/admin/knowledge/spaces" in paths
    assert "/api/v1/admin/knowledge/sources/{source_id}/authorizations" in paths
    assert "/api/v1/admin/knowledge/sources/{source_id}/documents" in paths
    assert "/api/v1/admin/knowledge/uploads" in paths
    assert "/api/v1/admin/knowledge/uploads/{upload_id}/complete" in paths
    assert "/api/v1/admin/knowledge/documents/{document_id}/authorizations" in paths
    assert "/api/v1/admin/knowledge/document-versions/{version_id}/parsing" in paths
    assert "/api/v1/admin/knowledge/document-versions/{version_id}/chunks" in paths
    assert "/api/v1/admin/knowledge/document-versions/{version_id}/publish" in paths
    assert "/api/v1/admin/knowledge/retrieval/debug" in paths
    assert "/api/v1/admin/knowledge/citations/{citation_id}/verify" in paths
    assert "/api/v1/admin/knowledge/indexes/{index_id}/rollback" in paths
    assert "/api/v1/admin/knowledge/evaluation-runs" in paths
    assert "/api/v1/admin/knowledge/audit" in paths


def test_knowledge_endpoints_require_admin_authentication(client) -> None:
    response = client.get("/api/v1/admin/knowledge/spaces")
    assert response.status_code == 401
    assert "embedding" not in response.text
    assert "evidence_encrypted" not in response.text
