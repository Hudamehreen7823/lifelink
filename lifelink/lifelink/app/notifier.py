"""Notification service.

Every notification is stored as an in-app row. If SMTP is configured
(LIFELINK_SMTP_HOST, optional _PORT/_USER/_PASSWORD/_FROM) an additional
'email' row is queued and delivered by `dispatch_pending_emails`, which the
background worker calls periodically. Delivery never happens inside a database
transaction, so a slow mail server cannot hold the write lock.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def smtp_configured() -> bool:
    return bool(os.environ.get("LIFELINK_SMTP_HOST"))


def send_email(to: str, subject: str, body: str) -> None:
    host = os.environ["LIFELINK_SMTP_HOST"]
    port = int(os.environ.get("LIFELINK_SMTP_PORT", "587"))
    user = os.environ.get("LIFELINK_SMTP_USER")
    password = os.environ.get("LIFELINK_SMTP_PASSWORD")
    sender = os.environ.get("LIFELINK_SMTP_FROM", user or "lifelink@localhost")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if os.environ.get("LIFELINK_SMTP_TLS", "1") == "1":
            smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def dispatch_pending_emails(conn, limit: int = 25) -> int:
    """Send queued email notifications. Returns the number attempted."""
    rows = conn.execute(
        """SELECT n.id, n.message, u.email FROM notifications n JOIN users u ON u.id = n.user_id
           WHERE n.channel = 'email' AND n.status = 'pending' ORDER BY n.id LIMIT ?""",
        (limit,),
    ).fetchall()
    for row in rows:
        try:
            send_email(row["email"], "LifeLink update", row["message"])
            status = "sent"
        except Exception:  # noqa: BLE001 - any delivery failure is recorded, not raised
            status = "failed"
        conn.execute("UPDATE notifications SET status = ? WHERE id = ?", (status, row["id"]))
    return len(rows)
