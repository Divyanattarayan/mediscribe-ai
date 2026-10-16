# Spec: auth-and-ownership

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/auth.py, backend/main.py (auth + history routes), backend/models.py, backend/schemas.py
> Last verified: 2026-09-17 (commit 89807ef)

Scope: JWT registration and login, the `get_current_user` dependency, and
ownership enforcement on every history route. Clinical records belong to the
user who created them and to nobody else.

---

### Requirement: Registration issues a token immediately
<!-- id: main.register -->
<!-- entities: User -->
<!-- enforced: main.register(), auth.hash_password(), auth.create_access_token() -->
<!-- triggers: A bearer token identifies the caller on every protected route -->

`POST /api/auth/register` SHALL hash the password with bcrypt, persist the user,
and return 201 with an access token and the public user object, so the frontend
can log the user in without a separate login step.

#### Scenario: a new email
<!-- test: tests/test_auth.py::test_register_returns_token_and_public_user -->
- **WHEN** the email is not already registered
- **THEN** 201 is returned with `access_token` and a `UserPublic` body that
  never contains the password hash

#### Scenario: a duplicate email
<!-- test: tests/test_auth.py::test_duplicate_email_is_409_not_500 -->
- **WHEN** the email already exists
- **THEN** 409 is returned — including when two concurrent registrations both
  pass the pre-check and the unique index rejects the loser, which is caught as
  `IntegrityError`, rolled back, and reported as 409 rather than 500

#### Scenario: a weak password
<!-- test: tests/test_auth.py::test_short_password_is_rejected -->
- **WHEN** the password fails the `RegisterRequest` schema constraint
- **THEN** the request is rejected by validation

---

### Requirement: Login is deliberately vague about why it failed
<!-- id: main.login -->
<!-- entities: User -->
<!-- enforced: main.login(), auth.verify_password() -->

`POST /api/auth/login` SHALL return 401 with the identical detail "Incorrect
email or password" for both an unknown email and a wrong password, to prevent
email enumeration.

#### Scenario: correct credentials
<!-- test: tests/test_auth.py::test_login_happy_path -->
- **WHEN** email and password match
- **THEN** a token and the public user are returned

#### Scenario: wrong password
<!-- test: tests/test_auth.py::test_login_wrong_password_is_401 -->
- **WHEN** the password does not verify
- **THEN** 401 is returned

#### Scenario: unknown email
<!-- test: tests/test_auth.py::test_login_unknown_email_is_401_with_same_shape -->
- **WHEN** no user has that email
- **THEN** 401 is returned with the same body shape as a wrong password

---

### Requirement: A bearer token identifies the caller on every protected route
<!-- id: auth.get_current_user -->
<!-- entities: User -->
<!-- enforced: auth.get_current_user() -->

`get_current_user` SHALL read the `Authorization: Bearer` header, verify the
HS256 signature and expiry against `JWT_SECRET_KEY`, load the user by the `sub`
claim, and raise 401 with `WWW-Authenticate: Bearer` when the token is missing,
malformed, expired, carries no subject, names a user that does not exist, or
names a user that is not active. Tokens expire after 7 days.

#### Scenario: no token
<!-- test: tests/test_auth.py::test_me_requires_a_token -->
- **WHEN** the Authorization header is absent
- **THEN** the request is rejected as unauthenticated

#### Scenario: a garbage token
<!-- test: tests/test_auth.py::test_me_rejects_a_garbage_token -->
- **WHEN** the token does not decode
- **THEN** 401 "Invalid or expired token"

#### Scenario: a valid token
<!-- test: tests/test_auth.py::test_me_returns_the_authenticated_user -->
- **WHEN** the token is valid and the user is active
- **THEN** `GET /api/auth/me` returns that user's public profile

#### Scenario: the account was deleted
<!-- test: tests/test_auth.py::test_deleted_account_token_stops_working -->
- **WHEN** a still-unexpired token names a user row that no longer exists
- **THEN** 401 is returned — the token is not trusted on its own

---

### Requirement: History is scoped to the caller by query, not by assumption
<!-- id: main.get_history -->
<!-- entities: Transcription, User, MedicalEntity, SoapNote -->
<!-- enforced: main.get_history() -->
<!-- depends_on: A bearer token identifies the caller on every protected route -->

`GET /api/history` SHALL filter on `Transcription.user_id == current_user.id`,
order newest-first, and eagerly load entities and the soap note via
`selectinload`.

#### Scenario: two users with history
<!-- test: tests/test_history_ownership.py::test_history_list_only_returns_own_rows -->
- **WHEN** another user also has transcriptions
- **THEN** only the caller's rows are returned

---

### Requirement: Reading or deleting one record checks ownership explicitly
<!-- id: main.get_transcription -->
<!-- entities: Transcription, User -->
<!-- enforced: main.get_transcription(), main.delete_history_item() -->
<!-- depends_on: A bearer token identifies the caller on every protected route -->

`GET /api/history/{id}` and `DELETE /api/history/{id}` SHALL fetch by id and
then compare `record.user_id` to the caller, returning 404 when the row does not
exist and 403 when it belongs to a different user. Deletion returns 204.

#### Scenario: another user's record
<!-- test: tests/test_history_ownership.py::test_cannot_read_another_users_transcription -->
- **WHEN** the id names a row owned by someone else
- **THEN** 403 "Not authorised" and no data is disclosed

#### Scenario: deleting another user's record
<!-- test: tests/test_history_ownership.py::test_cannot_delete_another_users_transcription -->
- **WHEN** a delete targets a row owned by someone else
- **THEN** 403 and the row survives

#### Scenario: an id that does not exist
<!-- test: tests/test_history_ownership.py::test_history_detail_unknown_id_is_404 -->
- **WHEN** no row has that id
- **THEN** 404 "Transcription not found"

---

### Requirement: Bulk deletion is scoped to the caller
<!-- id: main.delete_all_history -->
<!-- entities: Transcription, User -->
<!-- enforced: main.delete_all_history() -->

`DELETE /api/history` SHALL select only rows with the caller's `user_id`, delete
them individually so ORM cascades fire, and commit once. It returns 204.

#### Scenario: two users with history
<!-- test: tests/test_history_ownership.py::test_delete_all_history_is_scoped_to_the_caller -->
- **WHEN** the caller deletes all their history
- **THEN** the other user's rows are untouched

---

### Requirement: Account deletion removes all derived clinical data
<!-- id: main.delete_my_account -->
<!-- entities: User, Transcription, MedicalEntity, SoapNote -->
<!-- enforced: main.delete_my_account(), models.User.transcriptions -->

`DELETE /api/auth/me` SHALL delete the user row and rely on
`cascade="all, delete-orphan"` on `User.transcriptions`,
`Transcription.entities` and `Transcription.soap_note` to remove every
transcription, entity and note. It returns 204.

#### Scenario: an account with history
<!-- test: tests/test_auth.py::test_deleted_account_token_stops_working -->
- **WHEN** the account is deleted
- **THEN** the user's previously valid token no longer authenticates

---

### Requirement: The profile route updates only supplied fields
<!-- id: main.update_me -->
<!-- entities: User -->
<!-- enforced: main.update_me(), schemas.UpdateProfileRequest -->

`PUT /api/auth/me` SHALL apply `model_dump(exclude_unset=True)`, so fields the
request omits are left as they are.

#### Scenario: a partial update
- **WHEN** only `note_style_preset` is sent
- **THEN** only that column changes

---

### Invariant: Every /api route except register and login requires authentication
<!-- entities: User -->
<!-- enforced: auth.get_current_user(), main (route signatures) -->
<!-- verified_by: tests/test_upload_validation.py::test_transcribe_requires_authentication, tests/test_auth.py::test_me_requires_a_token -->

Every protected route SHALL declare `Depends(get_current_user)`; `/`, `/health`,
`/api/auth/register` and `/api/auth/login` are the only unauthenticated
endpoints.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Ownership is enforced by user_id, never assumed from the token alone
<!-- entities: Transcription, User -->
<!-- enforced: main.get_history(), main.get_transcription(), main.delete_history_item(), main.delete_all_history() -->
<!-- verified_by: tests/test_history_ownership.py -->

Possessing a valid token SHALL NOT be sufficient to read or delete a record. A
row is reachable only when its `user_id` equals the authenticated user's id.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: The password hash never leaves the server
<!-- entities: User -->
<!-- enforced: schemas.UserPublic -->
<!-- verified_by: tests/test_auth.py::test_register_returns_token_and_public_user -->

Every route returning a user SHALL serialise through `schemas.UserPublic`, which
has no `hashed_password` field.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: The application refuses to start without a JWT secret
<!-- entities: User -->
<!-- enforced: auth.SECRET_KEY -->

`auth.py` SHALL raise `RuntimeError` at import time when `JWT_SECRET_KEY` is
unset, rather than signing tokens with a default.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: Rotating JWT_SECRET_KEY invalidates every issued session token (noted in docs/CODEMAPS/dependencies.md). No code path handles rotation or key versioning; there is no refresh-token mechanism and a 7-day token cannot be revoked short of deactivating or deleting the user. -->
