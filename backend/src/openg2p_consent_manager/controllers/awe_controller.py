import json
import logging

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from openg2p_fastapi_common.controller import BaseController

from ..config import Settings
from ..services.awe_webhook_service import AweWebhookService, WebhookError

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class AweController(BaseController):
    """Inbound AWE webhook receiver.

    No bearer auth — authentication is entirely HMAC signature verification over
    the raw body (X-Approval-Signature / X-Approval-Timestamp), exactly as the
    registry's webhook controller. Returns 2xx once the event is applied (or
    deduped), 401 on bad signature, 422 on an unknown correlation so AWE retries.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webhooks = AweWebhookService.get_component()
        self.router.prefix += "/consent/v1/awe"
        self.router.tags += ["AWE"]

        self.router.add_api_route(
            "/webhooks/decision", self.receive_decision, methods=["POST"],
        )

    async def receive_decision(
        self,
        request: Request,
        x_approval_event_id: str = Header(default="", alias="X-Approval-Event-Id"),
        x_approval_timestamp: str = Header(default="", alias="X-Approval-Timestamp"),
        x_approval_signature: str = Header(default="", alias="X-Approval-Signature"),
    ):
        # Verify against the RAW bytes — re-serialising would change the MAC.
        raw = await request.body()
        try:
            self.webhooks.verify_signature(
                raw, x_approval_timestamp, x_approval_signature
            )
        except WebhookError as exc:
            return JSONResponse(status_code=exc.status, content={"error": exc.message})

        try:
            event = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(status_code=400, content={"error": "invalid_json"})

        try:
            result = await self.webhooks.process(x_approval_event_id, event)
        except WebhookError as exc:
            return JSONResponse(status_code=exc.status, content={"error": exc.message})
        except Exception as exc:  # noqa: BLE001 — surface as retryable 422
            _logger.exception("AWE webhook processing error")
            return JSONResponse(status_code=422, content={"error": str(exc)})

        return JSONResponse(status_code=200, content={"status": result})
