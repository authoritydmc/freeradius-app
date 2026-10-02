import pytest
from unittest.mock import patch, MagicMock
from api.payment_engine import parse_bank_upi_text, verify_razorpay_signature

def test_parse_bank_upi_text_hdfc():
    sample_hdfc = """
    Dear Customer,
    Rs. 52.00 has been credited to your account **1234 on 02-OCT-26 by UPI/CRED/123456789012/wifi:rajkumar:3.
    Available balance is Rs. 15,200.50.
    """
    res = parse_bank_upi_text(sample_hdfc)
    assert res["amount"] == 52.0
    assert res["utr"] == "123456789012"
    assert res["username"] == "rajkumar"
    assert res["plan_id"] == 3

def test_parse_bank_upi_text_sbi():
    sample_sbi = """
    Dear SBI User, A/C *9876 Credited by Rs 30.0 on 02Oct26 transfer from aman@okhdfcbank Ref No 987654321098 Note wifi:aman.
    """
    res = parse_bank_upi_text(sample_sbi)
    assert res["amount"] == 30.0
    assert res["utr"] == "987654321098"
    assert res["username"] == "aman"
    assert res["plan_id"] is None

def test_razorpay_signature_verification():
    order_id = "order_O123456"
    payment_id = "pay_P123456"
    secret = "sample_secret_key"
    
    import hmac, hashlib
    msg = f"{order_id}|{payment_id}"
    expected_sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    
    assert verify_razorpay_signature(order_id, payment_id, expected_sig, secret) is True
    assert verify_razorpay_signature(order_id, payment_id, "invalid_sig", secret) is False
