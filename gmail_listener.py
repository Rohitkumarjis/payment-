# gmail_listener.py - Gmail Alert Reader
import imaplib
import email
import re
import requests
from config import GMAIL_USER, GMAIL_APP_PASSWORD, IMAP_SERVER, IMAP_PORT
from database import get_db, mark_order_success, is_utr_duplicate

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(errors="ignore")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="ignore")
    return body

def scan_gmail_for_order(order_id, expected_amount, submitted_utr=None):
    if submitted_utr and is_utr_duplicate(submitted_utr):
        return {"success": False, "message": "Yeh UTR pehle hi use ho chuka hai!"}

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("INBOX")
    except Exception as e:
        return {"success": False, "message": f"Gmail login error: {str(e)}"}

    try:
        status, messages = mail.search(None, 'ALL')
        if status != "OK" or not messages[0]:
            mail.logout()
            return {"success": False, "message": "Inbox me email alert nahi mila."}

        email_ids = messages[0].split()
        recent_ids = email_ids[-30:]

        amt_int = int(float(expected_amount))
        amt_float = f"{float(expected_amount):.2f}"
        amount_regex = rf"(?:Rs\.?|INR|₹)?\s*(?:{re.escape(amt_float)}|{amt_int})\b"

        for m_id in reversed(recent_ids):
            res, msg_data = mail.fetch(m_id, "(RFC822)")
            for part in msg_data:
                if isinstance(part, tuple):
                    msg = email.message_from_bytes(part[1])
                    body = extract_body(msg)

                    has_amount = re.search(amount_regex, body, re.IGNORECASE)

                    if has_amount:
                        utrs_found = re.findall(r"\b\d{12}\b", body)
                        matched_utr = None

                        if submitted_utr:
                            if str(submitted_utr) in body:
                                matched_utr = str(submitted_utr)
                        elif len(utrs_found) > 0:
                            for cand in utrs_found:
                                if not is_utr_duplicate(cand):
                                    matched_utr = cand
                                    break

                        if matched_utr:
                            mark_order_success(order_id, matched_utr)
                            mail.logout()
                            trigger_merchant_webhook(order_id, matched_utr, expected_amount)
                            return {
                                "success": True,
                                "message": "Payment verified successfully!",
                                "order_id": order_id,
                                "utr": matched_utr,
                                "amount": expected_amount
                            }

        mail.logout()
        return {"success": False, "message": "Payment alert nahi mila abhi tak."}

    except Exception as e:
        try:
            mail.logout()
        except:
            pass
        return {"success": False, "message": f"Scan failed: {str(e)}"}

def trigger_merchant_webhook(order_id, utr, amount):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT webhook_url FROM orders WHERE order_id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()

    if row and row["webhook_url"]:
        try:
            payload = {
                "event": "payment.success",
                "order_id": order_id,
                "utr": utr,
                "amount": amount,
                "status": "PAID"
            }
            requests.post(row["webhook_url"], json=payload, timeout=5)
        except Exception:
            pass
