import json
from urllib import request

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class AlertService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, event: str, severity: str, payload: dict) -> None:
        logger.warning(
            {
                "event": "alert",
                "alert_event": event,
                "severity": severity,
                "payload": payload,
            }
        )
        if not self.settings.alerting_enabled or not self.settings.alerting_webhook_url:
            return
        body = json.dumps({"event": event, "severity": severity, "payload": payload}).encode("utf-8")
        req = request.Request(
            self.settings.alerting_webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10):
            pass
