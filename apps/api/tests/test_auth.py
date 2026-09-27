"""Authentication: signup, login, tokens, session lifecycle."""

import pytest

from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
)

API = "/api/v1/auth"
SIGNUP = {
    "company_name": "Acme Ltd",
    "full_name": "Ada Lovelace",
    "email": "ada@acme.example.com",
    "password": "correct-horse-battery",
}


def test_signup_creates_admin(client):
    r = client.post(f"{API}/signup", json=SIGNUP)
    assert r.status_code == 201, r.text
    assert r.json()["data"]["role"] == "admin", "first user of a workspace is its admin"


def test_duplicate_email_is_409_not_500(client):
    client.post(f"{API}/signup", json=SIGNUP)
    r = client.post(f"{API}/signup", json={**SIGNUP, "company_name": "Other"})
    assert r.status_code == 409
    assert r.json()["error_code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize(
    "password,reason",
    [
        ("short", "under 8 characters"),
        ("a" * 73, "over bcrypt's 72-byte limit, which would be silently truncated"),
    ],
)
def test_password_rules(client, password, reason):
    r = client.post(f"{API}/signup", json={**SIGNUP, "email": "x@acme.example.com", "password": password})
    assert r.status_code == 422, f"should reject a password {reason}"


def test_login_failures_are_indistinguishable(client):
    """A wrong password and an unknown address must look identical, or the
    login form becomes a user-enumeration oracle."""

    client.post(f"{API}/signup", json=SIGNUP)
    wrong = client.post(f"{API}/login", json={"email": SIGNUP["email"], "password": "nope"})
    unknown = client.post(f"{API}/login", json={"email": "ghost@acme.example.com", "password": "nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]
    assert wrong.json()["error_code"] == unknown.json()["error_code"]


def test_login_sets_httponly_cookies_and_leaks_no_token(client):
    client.post(f"{API}/signup", json=SIGNUP)
    r = client.post(f"{API}/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})

    assert r.status_code == 200, r.text
    assert "access_token" not in r.text, "the raw token must never appear in the response body"

    cookies = r.headers.get_list("set-cookie")
    assert all("HttpOnly" in c for c in cookies), "JS must not be able to read the session"
    assert any(
        "refresh_token=" in c and "Path=/api/v1/auth/refresh-token" in c for c in cookies
    ), "the long-lived token must not ride along on every API call"


def test_me_requires_a_session(client):
    assert client.get(f"{API}/me").status_code == 401


def test_me_returns_the_logged_in_user(client):
    client.post(f"{API}/signup", json=SIGNUP)
    client.post(f"{API}/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    r = client.get(f"{API}/me")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["email"] == SIGNUP["email"]


class TestTokenSeparation:
    """Access and refresh tokens must not be interchangeable.

    They were previously the same string, so a stolen refresh cookie worked as
    an access token and the 7-day cookie expired after 1 hour.
    """

    ids = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "company_id": "00000000-0000-0000-0000-000000000002",
        "role": "admin",
    }

    def test_tokens_differ(self):
        assert create_access_token(**self.ids) != create_refresh_token(**self.ids)

    def test_access_token_rejected_at_refresh(self):
        token = create_access_token(**self.ids)
        with pytest.raises(ValueError):
            decode_token(token, expected_type=REFRESH_TOKEN_TYPE)

    def test_refresh_token_rejected_as_access(self):
        token = create_refresh_token(**self.ids)
        with pytest.raises(ValueError):
            decode_token(token, expected_type=ACCESS_TOKEN_TYPE)

    def test_refresh_outlives_access(self):
        access = decode_token(create_access_token(**self.ids), expected_type=ACCESS_TOKEN_TYPE)
        refresh = decode_token(create_refresh_token(**self.ids), expected_type=REFRESH_TOKEN_TYPE)
        assert refresh["exp"] > access["exp"]


def test_refresh_token_rejected_on_a_protected_route(client, tenant):
    token = create_refresh_token(
        user_id=tenant.exec_id, company_id=tenant.company_id, role="sales_executive"
    )
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_bearer_header_is_accepted_for_api_clients(client, tenant):
    r = client.get(f"{API}/me", headers=tenant.headers("sales_executive"))
    assert r.status_code == 200, r.text


def test_valid_signature_for_unknown_user_is_rejected(client, tenant):
    token = create_access_token(
        user_id="99999999-9999-9999-9999-999999999999",
        company_id=tenant.company_id,
        role="admin",
    )
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_password_reset_takes_a_body_not_query_params(client):
    """A reset token and a plaintext password in a URL end up in proxy logs,
    browser history, and Referer headers."""

    ok_body = client.post(
        f"{API}/reset-password", json={"token": "t", "new_password": "a-good-password"}
    )
    assert ok_body.status_code == 200, ok_body.text

    as_query = client.post(
        f"{API}/reset-password", params={"token": "t", "new_password": "a-good-password"}
    )
    assert as_query.status_code == 422
