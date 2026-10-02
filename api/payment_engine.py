"""
api/payment_engine.py
=====================
Indian Payment Gateways & Email IMAP Auto-Reconciliation Engine for RajLabs FreeRADIUS.

Supported Gateways:
- Direct UPI QR & Note-based Recon (Google Pay, PhonePe, Paytm, BHIM, Cred)
- Email / IMAP Bank Alert Scanner (Gmail, Workspace, Outlook, IMAP TLS)
- Razorpay API & Webhook Verification
- Cashfree PG Orders & Webhook Verification
- PayU Money / Biz Payment Verification
- 1-Click Manual UTR / Note Top-up
"""

import os
import re
import hmac
import hashlib
import imaplib
import email
from email.header import decode_header
import json
import time
import urllib.request
import urllib.error
import base64
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("radius.payment_engine")


def decode_mime_words(s: str) -> str:
    """Decode RFC 2047 encoded email headers."""
    if not s:
        return ""
    decoded_fragments = []
    for fragment, encoding in decode_header(s):
        if isinstance(fragment, bytes):
            try:
                decoded_fragments.append(fragment.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                decoded_fragments.append(fragment.decode("latin1", errors="replace"))
        else:
            decoded_fragments.append(str(fragment))
    return "".join(decoded_fragments)


def get_email_body_text(msg: email.message.Message) -> str:
    """Extract plain text or html body from an email Message object."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" not in content_disposition and content_type in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body += payload.decode(charset, errors="replace") + "\n"
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
        except Exception:
            pass
    # Strip HTML tags if HTML
    clean_text = re.sub(r"<[^>]+>", " ", body)
    clean_text = re.sub(r"\s+", " ", clean_text)
    return clean_text.strip()


def parse_bank_upi_text(text: str, subject: str = "") -> Dict[str, Any]:
    """
    Extracts Amount, UTR (12-digit UPI reference), Note / Remarks, and Payer Info
    from standard Indian bank alert emails (HDFC, SBI, ICICI, Axis, Kotak, Yes Bank, NPCI, Paytm, PhonePe, GPay).
    """
    combined = f"{subject} {text}"
    
    # 1. Extract Amount
    # Matches: Rs. 250, INR 250.00, Rs 50.00, credited by Rs 100, received Rs. 20
    amount = None
    amt_match = re.search(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)", combined, re.IGNORECASE)
    if amt_match:
        try:
            raw_amt = amt_match.group(1).replace(",", "")
            amount = float(raw_amt)
        except ValueError:
            pass

    # 2. Extract UTR / RRN / Transaction ID (12-digit standard UPI sequence or alphanumeric ref)
    utr = None
    utr_match = re.search(r"(?:UTR|RRN|UPI\s*Ref|Ref\s*No|Txn\s*ID|Transaction\s*Id)[\s/:\-]+([0-9]{12}|[A-Za-z0-9]{10,25})", combined, re.IGNORECASE)
    if utr_match:
        utr = utr_match.group(1).strip()
    else:
        # Fallback 12-digit contiguous sequence
        standalone_12 = re.search(r"\b([0-9]{12})\b", combined)
        if standalone_12:
            utr = standalone_12.group(1)

    # 3. Extract Note / Tag (e.g. wifi:aman:1, wifi:raj, RL-1234, username)
    note_username = None
    note_plan_id = None

    # Check for explicit wifi/rl prefix first: wifi:username[:plan_id] or wifi-username
    wifi_prefix_match = re.search(r"\b(?:wifi|rl)[\s:\-_/]+([a-zA-Z0-9_.@-]{2,64}(?::\d+)?)", combined, re.IGNORECASE)
    if wifi_prefix_match:
        raw_note = wifi_prefix_match.group(1).strip().rstrip(".,;:! ")
        if ":" in raw_note:
            parts = raw_note.split(":", 1)
            note_username = parts[0].strip().rstrip(".,;:! ")
            try:
                note_plan_id = int(parts[1].rstrip(".,;:! "))
            except ValueError:
                pass
        else:
            note_username = raw_note
    else:
        # Check for generic note/remark/for prefix
        generic_note_match = re.search(r"\b(?:note|remark|remarks|desc|msg)[\s:\-]+([a-zA-Z0-9_.@-]{2,64})", combined, re.IGNORECASE)
        if generic_note_match:
            note_username = generic_note_match.group(1).strip().rstrip(".,;:! ")

    # Fallback to direct username pattern if found in message body
    if not note_username:
        direct_match = re.search(r"\b(?:username|user|client)[\s:\-]+([a-zA-Z0-9_.@-]{2,64})", combined, re.IGNORECASE)
        if direct_match:
            note_username = direct_match.group(1).strip().rstrip(".,;:! ")

    return {
        "amount": amount,
        "utr": utr,
        "username": note_username,
        "plan_id": note_plan_id,
        "matched": bool(amount and utr and note_username)
    }


def test_imap_connection(imap_host: str, imap_port: int, imap_user: str, imap_pass: str) -> Dict[str, Any]:
    """Test IMAP SSL connection to Gmail or custom mail server."""
    if not (imap_host and imap_user and imap_pass):
        return {"ok": False, "error": "IMAP Host, User/Email, and Password are required."}
    
    try:
        mail = imaplib.IMAP4_SSL(imap_host, int(imap_port or 993), timeout=10)
        mail.login(imap_user, imap_pass)
        status, folders = mail.list()
        mail.logout()
        return {
            "ok": True,
            "message": f"Successfully connected & authenticated with {imap_host} as {imap_user}!",
            "folders_count": len(folders) if folders else 0
        }
    except Exception as e:
        return {"ok": False, "error": f"IMAP connection failed: {str(e)}"}


def scan_bank_emails_for_payments(
    imap_host: str,
    imap_port: int,
    imap_user: str,
    imap_pass: str,
    folder: str = "INBOX",
    mark_seen: bool = True,
    limit: int = 30
) -> Dict[str, Any]:
    """
    Connects to IMAP, searches for recent unread or bank payment emails,
    extracts UPI notes/UTRs, and returns actionable reconciliation records.
    """
    if not (imap_host and imap_user and imap_pass):
        return {"success": False, "error": "IMAP credentials not configured in settings."}

    parsed_transactions = []
    try:
        mail = imaplib.IMAP4_SSL(imap_host, int(imap_port or 993), timeout=15)
        mail.login(imap_user, imap_pass)
        mail.select(folder or "INBOX")

        # Search for UNSEEN emails or recent messages
        status, messages = mail.search(None, "UNSEEN")
        msg_ids = messages[0].split() if messages and messages[0] else []
        
        # If no unread, check last 15 messages
        if not msg_ids:
            status, all_messages = mail.search(None, "ALL")
            if all_messages and all_messages[0]:
                msg_ids = all_messages[0].split()[-limit:]

        msg_ids = msg_ids[-limit:]  # Cap to limit
        msg_ids.reverse()

        for mid in msg_ids:
            res, data = mail.fetch(mid, "(RFC822)")
            if res != "OK" or not data or not data[0]:
                continue
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = decode_mime_words(msg.get("Subject", ""))
            from_addr = decode_mime_words(msg.get("From", ""))
            date_str = msg.get("Date", "")
            body = get_email_body_text(msg)

            parsed = parse_bank_upi_text(body, subject=subject)
            parsed["subject"] = subject
            parsed["from"] = from_addr
            parsed["date"] = date_str
            parsed["message_id"] = mid.decode() if isinstance(mid, bytes) else str(mid)
            parsed["raw_snippet"] = body[:200]
            parsed_transactions.append(parsed)

            if mark_seen and parsed.get("matched"):
                mail.store(mid, "+FLAGS", "\\Seen")

        mail.logout()
        return {
            "success": True,
            "scanned_count": len(parsed_transactions),
            "matched_count": sum(1 for t in parsed_transactions if t.get("matched")),
            "transactions": parsed_transactions
        }
    except Exception as e:
        logger.error("IMAP scan failed: %s", e)
        return {"success": False, "error": str(e)}


# ------------------------------------------------------------------------------
# RAZORPAY GATEWAY INTEGRATION
# ------------------------------------------------------------------------------
def verify_razorpay_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    """Validates Razorpay Payment Signature (HMAC SHA256)."""
    if not (order_id and payment_id and signature and secret):
        return False
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_razorpay_order(key_id: str, key_secret: str, amount_inr: float, receipt: str, notes: dict = None) -> Dict[str, Any]:
    """Creates an Order on Razorpay REST API (amount in paise)."""
    url = "https://api.razorpay.com/v1/orders"
    payload = {
        "amount": int(round(amount_inr * 100)), # Razorpay requires paise
        "currency": "INR",
        "receipt": receipt,
        "notes": notes or {}
    }
    auth_header = "Basic " + base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": auth_header, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        return {"error": f"Razorpay API Error ({e.code}): {err_body}"}
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------------------
# CASHFREE GATEWAY INTEGRATION
# ------------------------------------------------------------------------------
def create_cashfree_order(app_id: str, secret_key: str, order_id: str, amount_inr: float, customer_id: str, customer_phone: str = "9999999999", customer_email: str = "user@rajlabs.in", env: str = "PROD") -> Dict[str, Any]:
    """Creates a Payment Session on Cashfree Orders API."""
    base_url = "https://api.cashfree.com/pg/orders" if env.upper() == "PROD" else "https://sandbox.cashfree.com/pg/orders"
    payload = {
        "order_id": order_id,
        "order_amount": float(amount_inr),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": customer_id,
            "customer_phone": customer_phone or "9999999999",
            "customer_email": customer_email or f"{customer_id}@rajlabs.in"
        },
        "order_meta": {
            "return_url": "https://wifi.rajlabs.in/portal?order_id={order_id}"
        }
    }
    req = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-client-id": app_id,
            "x-client-secret": secret_key,
            "x-api-version": "2023-08-01",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        return {"error": f"Cashfree API Error ({e.code}): {err_body}"}
    except Exception as e:
        return {"error": str(e)}
