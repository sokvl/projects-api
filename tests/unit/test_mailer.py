from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from moto.core.models import DEFAULT_ACCOUNT_ID
from moto.ses.models import ses_backends

from app.core.config import settings
from app.mail.ses import Mailer, MailError

REGION = "eu-central-1"
SENDER = "noreply@projects.local"


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def mailer() -> Iterator[Mailer]:
    with mock_aws():
        yield Mailer(
            settings.model_copy(
                update={"s3_region": REGION, "ses_api_url": None, "sender_email": SENDER}
            )
        )


async def test_send_delivers_a_text_mail_from_the_sender(mailer: Mailer) -> None:
    boto3.client("ses", region_name=REGION).verify_email_identity(EmailAddress=SENDER)

    await mailer.send("anna@example.com", "Invitation", "Join it here: http://x/join?token=t")

    [message] = ses_backends[DEFAULT_ACCOUNT_ID][REGION].sent_messages
    assert message.source == SENDER
    assert message.destinations["ToAddresses"] == ["anna@example.com"]
    assert message.subject == "Invitation"
    assert message.body == "Join it here: http://x/join?token=t"


async def test_send_raises_mail_error_when_ses_rejects(mailer: Mailer) -> None:
    with pytest.raises(MailError):
        await mailer.send("anna@example.com", "Invitation", "body")
