"""
Email delivery, service-based per spec §45 — business endpoints call
`email_service.send(...)`, never a provider SDK directly, so a real
provider (SES/SendGrid/Postmark/etc.) can be dropped in later by
implementing the same interface without touching any endpoint code.

This environment has no real SMTP/provider credentials available, so the
default backend logs the email instead of sending it. That is a Part 1/2
foundation limitation, not a design choice to keep long-term — swap
`_backend` for a real provider adapter when credentials exist.

Per spec §46, only these lifecycle emails exist. There is no generic
"send any email" business-endpoint entry point, and this module makes it a
one-line change per email type rather than sprinkling send calls everywhere.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger("app.email")


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailBackend:
    async def send(self, message: EmailMessage) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEmailBackend(EmailBackend):
    """Logs instead of sending. Replace with a real provider adapter for production."""

    async def send(self, message: EmailMessage) -> None:
        logger.info("EMAIL to=%s subject=%r body=%r", message.to, message.subject, message.body)


_backend: EmailBackend = ConsoleEmailBackend()


async def _send(to: str, subject: str, body: str) -> None:
    try:
        await _backend.send(EmailMessage(to=to, subject=subject, body=body))
    except Exception as exc:  # noqa: BLE001 — email failure must never break the caller's business op
        logger.error("Email delivery failed to=%s subject=%r: %s", to, subject, exc)


async def send_manager_invite(to: str, invite_link: str) -> None:
    await _send(to, "You're invited to DigiSanchaar", f"Complete your manager signup: {invite_link}")


async def send_publisher_invite(to: str, invite_link: str) -> None:
    await _send(to, "You're invited to DigiSanchaar", f"Complete your publisher signup: {invite_link}")


async def send_otp(to: str, code: str, purpose_label: str) -> None:
    # Never log the raw code outside this ConsoleEmailBackend dev stand-in —
    # a real provider adapter must not log message bodies in production.
    await _send(to, "Your DigiSanchaar verification code", f"Your {purpose_label} code is {code}. It expires in 10 minutes.")


async def send_manager_approved(to: str, manager_id: str) -> None:
    await _send(
        to,
        "Your DigiSanchaar manager account is approved",
        f"You're approved. Your Manager ID is {manager_id}. You can now log in.",
    )


async def send_publisher_approved(to: str, publisher_id: str) -> None:
    await _send(
        to,
        "Your DigiSanchaar publisher account is approved",
        f"You're approved. Your Publisher ID is {publisher_id}. You can now log in.",
    )


async def send_publisher_application_received(to: str, applicant_name: str, publisher_id: str, needs_manager: bool) -> None:
    """Lifecycle notice to the assigned Manager / Super Admin (Part 16.2.1). No secrets."""
    action = "Review it in Publisher Applications and assign a Manager when approving." if needs_manager else "Review it in your Publishers list."
    await _send(
        to,
        "New publisher application on DigiSanchaar",
        f"{applicant_name} (Publisher ID {publisher_id}) submitted a publisher application. {action}",
    )


async def send_publisher_assigned(to: str, publisher_name: str, publisher_id: str) -> None:
    await _send(
        to,
        "A publisher was assigned to you on DigiSanchaar",
        f"{publisher_name} (Publisher ID {publisher_id}) is now assigned to you.",
    )


async def send_password_reset_otp(to: str, code: str) -> None:
    await _send(to, "Reset your DigiSanchaar password", f"Your password reset code is {code}. It expires in 10 minutes.")
