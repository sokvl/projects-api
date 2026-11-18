from functools import partial

import boto3
from anyio import CapacityLimiter, to_thread
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, settings

ses_limiter = CapacityLimiter(5)


class MailError(Exception):
    """SES call failed."""


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.sender = settings.sender_email
        self.client = boto3.client(
            "ses",
            region_name=settings.s3_region,
            endpoint_url=settings.ses_api_url,
            config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 3}),
        )

    async def send(self, to: str, subject: str, body: str) -> None:
        call = partial(
            self.client.send_email,
            Source=self.sender,
            Destination={"ToAddresses": [to]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
        )
        try:
            await to_thread.run_sync(call, limiter=ses_limiter)
        except (BotoCoreError, ClientError) as e:
            raise MailError(str(e)) from e


mailer = Mailer(settings)


def get_mailer() -> Mailer:
    return mailer
