"""History endpoints must be strictly user-scoped.

These tests seed transcription rows directly through the ORM so they do not
depend on the (stubbed) transcription pipeline.
"""

import models
from tests.conftest import auth_header


def _seed_transcription(db_session, user_id: int, filename: str = "a.mp3") -> int:
    row = models.Transcription(
        user_id=user_id,
        patient_id="PT-00001",
        filename=filename,
        transcription="patient reports chest pain",
        medical_content_score=87.0,
        duration="1:23",
        status="complete",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row.id


def test_history_list_only_returns_own_rows(client, make_user, db_session):
    token_a, user_a = make_user("owner@example.com")
    _token_b, user_b = make_user("intruder@example.com")

    _seed_transcription(db_session, user_a["id"], "owned.mp3")
    _seed_transcription(db_session, user_b["id"], "other.mp3")

    response = client.get("/api/history", headers=auth_header(token_a))
    assert response.status_code == 200
    rows = response.json()
    assert [r["filename"] for r in rows] == ["owned.mp3"]


def test_cannot_read_another_users_transcription(client, make_user, db_session):
    _token_a, user_a = make_user("owner@example.com")
    token_b, _user_b = make_user("intruder@example.com")

    victim_id = _seed_transcription(db_session, user_a["id"])

    response = client.get(f"/api/history/{victim_id}", headers=auth_header(token_b))
    # The DB query filters by user_id, so the row is simply not found rather
    # than returning 403. 404 is the correct privacy-preserving response
    # because it does not confirm to the requester that the record exists.
    assert response.status_code == 404


def test_cannot_delete_another_users_transcription(client, make_user, db_session):
    _token_a, user_a = make_user("owner@example.com")
    token_b, _user_b = make_user("intruder@example.com")

    victim_id = _seed_transcription(db_session, user_a["id"])

    response = client.delete(f"/api/history/{victim_id}", headers=auth_header(token_b))
    assert response.status_code == 403

    # The row must still be present after the rejected delete.
    assert db_session.get(models.Transcription, victim_id) is not None


def test_delete_all_history_is_scoped_to_the_caller(client, make_user, db_session):
    token_a, user_a = make_user("owner@example.com")
    _token_b, user_b = make_user("bystander@example.com")

    _seed_transcription(db_session, user_a["id"], "a1.mp3")
    _seed_transcription(db_session, user_a["id"], "a2.mp3")
    keep_id = _seed_transcription(db_session, user_b["id"], "b1.mp3")

    assert client.delete("/api/history", headers=auth_header(token_a)).status_code == 204

    remaining = db_session.query(models.Transcription).all()
    assert [r.id for r in remaining] == [keep_id]


def test_history_detail_unknown_id_is_404(client, make_user):
    token, _ = make_user()
    assert client.get("/api/history/999999", headers=auth_header(token)).status_code == 404
