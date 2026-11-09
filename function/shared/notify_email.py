"""Send notification email via Azure Communication Services."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def send_email(*, to_address: str, subject: str, body: str) -> None:
    conn = os.environ.get("ACS_EMAIL_CONNECTION_STRING") or ""
    sender = os.environ.get("ACS_EMAIL_SENDER") or ""
    if not conn or not sender:
        logger.error("ACS email not configured; skip send to %s", to_address)
        return
    if not to_address:
        logger.warning("No uploaderEmail; skip email: %s", body)
        return

    from azure.communication.email import EmailClient

    client = EmailClient.from_connection_string(conn)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": to_address}]},
        "content": {
            "subject": subject,
            "plainText": body,
        },
    }
    poller = client.begin_send(message)
    result = poller.result()
    logger.info("Email sent to %s id=%s", to_address, getattr(result, "id", result))
