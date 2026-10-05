"""Multipart file uploads and integration with the profile workflow."""

import pytest
from fastapi.testclient import TestClient

from jobscout.main import create_app
from jobscout.services.resume_service import MAX_RESUME_BYTES
from tests.test_resume_service import make_docx, make_pdf


@pytest.mark.parametrize(
    ("name", "content", "mime", "expected_text"),
    [
        ("resume.pdf", make_pdf("Skills: Python, SQL"), "application/pdf", "Skills: Python, SQL"),
        ("resume.txt", b"Skills\nPython", "text/plain", "Skills\nPython"),
        ("简历.docx", make_docx(), "application/octet-stream", "求职推荐系统"),
    ],
    ids=lambda value: "file-bytes" if isinstance(value, bytes) else None,
)
def test_upload_returns_existing_resume_contract(
    name: str, content: bytes, mime: str, expected_text: str
) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/resumes/parse", files={"file": (name, content, mime)})
    assert response.status_code == 200
    assert set(response.json()) == {"name", "text"}
    assert response.json()["name"] == name
    assert expected_text in response.json()["text"]


@pytest.mark.parametrize(
    ("name", "content", "status", "code"),
    [
        ("resume.doc", b"legacy", 415, "unsupported_format"),
        ("resume.docx", b"word", 422, "invalid_file"),
        ("resume.pdf", b"not a PDF", 422, "invalid_file"),
        ("resume.pdf", make_pdf(""), 422, "no_extractable_text"),
        ("resume.pdf", make_pdf("Python", encrypted=True), 422, "encrypted_file"),
        ("resume.txt", b"x" * (MAX_RESUME_BYTES + 1), 413, "file_too_large"),
    ],
    ids=lambda value: "file-bytes" if isinstance(value, bytes) else None,
)
def test_upload_errors_include_machine_code_and_user_message(
    name: str, content: bytes, status: int, code: str
) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/resumes/parse", files={"file": (name, content)})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["message"]


def test_upload_requires_file_field() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/resumes/parse", json={"name": "resume.pdf"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("name", "content"),
    [("resume.pdf", make_pdf("Skills: Python, SQL")), ("简历.docx", make_docx())],
    ids=["pdf", "docx"],
)
def test_parsed_resume_enters_profile_flow_without_contract_changes(
    name: str, content: bytes
) -> None:
    from jobscout.services.replay_service import ReplayProvider
    from tests.test_web_scaffold import settled

    with TestClient(create_app(provider=ReplayProvider())) as client:
        parsed = client.post("/api/v1/resumes/parse", files={"file": (name, content)})
        response = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "parsed-resume",
                "description": "",
                "resume": parsed.json(),
                "target_directions": ["backend engineer"],
                "preferences": {
                    "location": None,
                    "location_unrestricted": False,
                    "employment_type": None,
                    "salary_range": None,
                    "work_mode": None,
                    "industry": None,
                },
            },
        )
        assert response.status_code == 202
        snapshot = settled(client, response.json()["session_id"])
    assert snapshot["outcome"] == "paused"
    assert snapshot["profile"]["source"]["resume"] is True
    assert set(snapshot["profile"]["skills"]) >= {"Python", "SQL"}
    assert "input_data" not in snapshot
