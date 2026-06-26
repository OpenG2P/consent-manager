import logging

from openg2p_fastapi_common.controller import BaseController

from ..config import Settings
from ..services import CryptoService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class WellKnownController(BaseController):
    """Publishes the CM signing public keys so any party can verify receipts."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.crypto = CryptoService.get_component()
        self.router.tags += ["Well-Known"]

        self.router.add_api_route(
            "/.well-known/jwks.json", self.jwks, methods=["GET"],
        )

    async def jwks(self) -> dict:
        return self.crypto.public_jwks()
