"""Authentication endpoint behaviour: register, login, /me, and token handling."""

from tests.conftest import auth_header, register


def test_register_returns_token_and_public_user(client):
    response = register(client, "alice@example.com")
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "alice@example.com"
    # The hashed password must never be serialised back to the client.
    assert "hashed_password" not in body["user"]
    assert "password" not in body["user"]


def test_login_happy_path(client):
    register(client, "bob@example.com", password="a-good-passphrase")

    response = client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "a-good-passphrase"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_login_wrong_password_is_401(client):
    register(client, "carol@example.com", password="the-right-one")

    response = client.post(
        "/api/auth/login",
        json={"email": "carol@example.com", "password": "the-wrong-one"},
    )
    assert response.status_code == 401


def test_login_unknown_email_is_401_with_same_shape(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-here"},
    )
    assert response.status_code == 401
    # Deliberately vague so it cannot be used for email enumeration.
    assert response.json()["detail"] == "Incorrect email or password"


def test_duplicate_email_is_409_not_500(client):
    assert register(client, "dupe@example.com").status_code == 201
    second = register(client, "dupe@example.com")
    assert second.status_code == 409


def test_short_password_is_rejected(client):
    """Server-side password policy — client-side checks are not a control."""
    response = register(client, "weak@example.com", password="short")
    assert response.status_code == 422


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code in (401, 403)


def test_me_rejects_a_garbage_token(client):
    response = client.get("/api/auth/me", headers=auth_header("not-a-real-jwt"))
    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client, make_user):
    token, user = make_user("dave@example.com")
    response = client.get("/api/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == "dave@example.com"
    assert response.json()["id"] == user["id"]


def test_deleted_account_token_stops_working(client, make_user):
    token, _ = make_user("erin@example.com")
    assert client.delete("/api/auth/me", headers=auth_header(token)).status_code == 204
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
