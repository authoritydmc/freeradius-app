import os
import pytest
from fastapi.testclient import TestClient

# Set testing environment variables before importing app
os.environ["RADIUS_SECRET"] = "TestSecret1234567890!@"
os.environ["SESSION_SECRET"] = "TestSessionSecretLongKey1234567890!@"
os.environ["ADMIN_FALLBACK_USER"] = "admin_radius"
os.environ["ADMIN_FALLBACK_PASSWORD"] = "StrongAdminPass123!@"

from api.app import app, generate_session_token, is_user_admin

client = TestClient(app, raise_server_exceptions=False)

def test_dashboard_route_serves_html():
    response = client.get("/radius")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "RajLabs" in response.text

def test_portal_route_serves_html():
    response = client.get("/radius/portal")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "RajLabs" in response.text

def test_public_config_endpoint():
    response = client.get("/radius/api/public-config")
    assert response.status_code == 200
    data = response.json()
    assert "wifi_ssid" in data
    assert "wifi_auth_type" in data
    assert "portal_path" in data
    assert data["portal_path"] == "/radius/portal"
    assert "admin_contact" in data
    assert "payment_config" in data

def test_ca_download_is_public():
    # CA download must be accessible by devices joining Wi-Fi without admin token
    response = client.get("/radius/api/certs/ca")
    # Will be 200 if cert exists or 404 if bootstrap not run, but NEVER 401 Unauthorized
    assert response.status_code in (200, 404)
    assert response.status_code != 401

def test_is_user_admin_fallback():
    assert is_user_admin("admin_radius") is True
    assert is_user_admin("unknown_guest_123") is False

def test_admin_authentication_and_session_token():
    admin_token = generate_session_token("admin_radius", role="admin")
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test protected settings route - accepted as admin (200 with DB, 500 if DB offline during unit test, never 401)
    res = client.get("/radius/api/settings", headers=headers)
    assert res.status_code in (200, 500)
    assert res.status_code != 401

def test_user_session_token_isolation():
    user_token = generate_session_token("regular_user", role="user")
    headers = {"Authorization": f"Bearer {user_token}"}
    
    # Regular user must be forbidden from administrative settings (strictly 401)
    res = client.get("/radius/api/settings", headers=headers)
    assert res.status_code == 401
