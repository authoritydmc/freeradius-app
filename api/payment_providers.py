import re
import hmac
import hashlib
import datetime
from typing import Optional, Dict, Any, Tuple
import logging

class PaymentProvider:
    @staticmethod
    def verify_razorpay_signature(body: bytes, signature: str, secret: str) -> bool:
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def verify_cashfree_signature(body: bytes, signature: str, timestamp: str, secret: str) -> bool:
        if not secret or not signature or not timestamp:
            return False
        data = f"{timestamp}{body.decode('utf-8', errors='ignore')}"
        expected = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def generate_upi_reference(username: str, plan_days: int) -> str:
        """
        Generates standard machine-readable UPI transaction note:
        e.g. WIFI|raj|20261002|7D
        """
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        return f"WIFI|{username}|{today_str}|{plan_days}D"

    @staticmethod
    def parse_upi_reference(note: str) -> Optional[Dict[str, Any]]:
        """
        Parses machine readable note: WIFI|<username>|<YYYYMMDD>|<N>D
        or returns None if not matching.
        """
        if not note:
            return None
        
        # Support formats like: WIFI|raj|20261002|7D or WIFI-raj-20261002-7
        clean = note.strip().upper()
        m = re.match(r"^WIFI[\|\-]([a-zA-Z0-9_\.\-]+)[\|\-](\d{8})[\|\-](\d+)D?$", clean, re.IGNORECASE)
        if m:
            return {
                "username": m.group(1).lower(),
                "date": m.group(2),
                "plan_days": int(m.group(3))
            }
        return None

    @staticmethod
    def parse_email_payment_receipt(email_subject: str, email_body: str) -> Optional[Dict[str, Any]]:
        """
        Extracts payment amount, UTR / transaction ID, and UPI reference note from banking alert emails.
        """
        text = f"{email_subject}\n{email_body}"
        
        # Extract UTR / Txn ID
        utr_match = re.search(r"(?:UTR|Ref(?:erence)?\s*(?:No|Number|ID)?|Txn\s*ID|Transaction\s*ID)[:\s#]*([A-Za-z0-9]{8,30})", text, re.IGNORECASE)
        utr = utr_match.group(1) if utr_match else None

        # Extract Amount (INR / Rs / ₹)
        amt_match = re.search(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{2})?)", text, re.IGNORECASE)
        amount = None
        if amt_match:
            try:
                amount = float(amt_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Extract Reference / Note
        ref_match = re.search(r"(WIFI[\|\-][a-zA-Z0-9_\.\-]+[\|\-]\d{8}[\|\-]\d+D?)", text, re.IGNORECASE)
        note = ref_match.group(1) if ref_match else None

        parsed_ref = PaymentProvider.parse_upi_reference(note) if note else None

        if utr and amount and parsed_ref:
            return {
                "utr": utr,
                "amount": amount,
                "username": parsed_ref["username"],
                "plan_days": parsed_ref["plan_days"],
                "raw_note": note
            }
        return None
