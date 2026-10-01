import pytest
import datetime
from api.access_engine import get_access_decision
from api.payment_providers import PaymentProvider
from api.app import generate_session_token, verify_session_token

def test_disabled_user_access_decision():
    user = {
        "status": "DISABLED",
        "group_recharge_required": False,
        "recharge_required_override": False
    }
    decision = get_access_decision(user)
    assert decision["decision"] == "DENY"
    assert "disabled" in decision["reason"].lower()
    assert decision["session_timeout"] == 0

def test_recharge_exempt_user():
    # User in FREE group
    user = {
        "status": "ACTIVE",
        "group_recharge_required": False,
        "recharge_required_override": None,
        "group_max_session_seconds": 86400
    }
    decision = get_access_decision(user)
    assert decision["decision"] == "ALLOW"
    assert decision["recharge_required"] is False
    assert decision["session_timeout"] == 86400

    # User with explicit FALSE override
    user_override = {
        "status": "ACTIVE",
        "group_recharge_required": True,
        "recharge_required_override": False,
        "group_max_session_seconds": 3600
    }
    dec_override = get_access_decision(user_override)
    assert dec_override["decision"] == "ALLOW"
    assert dec_override["session_timeout"] == 3600

def test_recharge_required_no_subscription():
    user = {
        "status": "ACTIVE",
        "group_recharge_required": True,
        "recharge_required_override": None,
        "active_subscription": None
    }
    decision = get_access_decision(user)
    assert decision["decision"] == "DENY"
    assert "recharge required" in decision["reason"].lower()
    assert decision["session_timeout"] == 0

def test_recharge_required_active_subscription_cap_rules():
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Case A: 5 Hours remaining (18,000s) -> session_timeout MUST be 18,000s
    sub_5h = {
        "id": 1,
        "expires_at": now + datetime.timedelta(hours=5),
        "plan_max_session_seconds": 86400
    }
    user_5h = {
        "status": "ACTIVE",
        "group_recharge_required": True,
        "recharge_required_override": None,
        "active_subscription": sub_5h
    }
    decision_5h = get_access_decision(user_5h)
    assert decision_5h["decision"] == "ALLOW"
    assert 17990 <= decision_5h["session_timeout"] <= 18000

    # Case B: 10 Days remaining (864,000s) -> session_timeout MUST BE CAPPED AT 86,400s (1 Day max)
    sub_10d = {
        "id": 2,
        "expires_at": now + datetime.timedelta(days=10),
        "plan_max_session_seconds": 86400
    }
    user_10d = {
        "status": "ACTIVE",
        "group_recharge_required": True,
        "recharge_required_override": None,
        "active_subscription": sub_10d
    }
    decision_10d = get_access_decision(user_10d)
    assert decision_10d["decision"] == "ALLOW"
    assert decision_10d["session_timeout"] == 86400

def test_upi_reference_generator_and_parser():
    ref = PaymentProvider.generate_upi_reference("raj", 7)
    assert ref.startswith("WIFI|raj|")
    assert ref.endswith("|7D")

    parsed = PaymentProvider.parse_upi_reference(ref)
    assert parsed is not None
    assert parsed["username"] == "raj"
    assert parsed["plan_days"] == 7

def test_email_payment_receipt_parser():
    subject = "Alert: Credit in A/C XX8901 via UPI/428919208392"
    body = """
    Dear Customer,
    Your account has been credited with INR 100.00 on 02-10-2026.
    Transaction Ref / UTR: 428919208392
    Payment Note: WIFI|raj|20261002|7D
    Thank you for banking with us.
    """
    receipt = PaymentProvider.parse_email_payment_receipt(subject, body)
    assert receipt is not None
    assert receipt["utr"] == "428919208392"
    assert receipt["amount"] == 100.0
    assert receipt["username"] == "raj"
    assert receipt["plan_days"] == 7

def test_user_and_admin_tokens():
    admin_token = generate_session_token("raj", role="admin")
    v_admin = verify_session_token(admin_token)
    assert v_admin is not None
    assert v_admin[0] == "raj"
    assert v_admin[1] == "admin"

    user_token = generate_session_token("aman", role="user")
    v_user = verify_session_token(user_token)
    assert v_user is not None
    assert v_user[0] == "aman"
    assert v_user[1] == "user"
