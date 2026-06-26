# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer

from .controllers import (
    LifecycleController,
    PartnerController,
    SubjectController,
    VerificationController,
    WellKnownController,
)
from .models import (
    AuditLog,
    AuthContext,
    ConsentArtefact,
    ConsentReceipt,
    ConsentRequest,
    DecisionLog,
    Partner,
    PartnerKey,
    PartnerPolicy,
    RevocationRecord,
)
from .services import (
    ConsentService,
    CryptoService,
    LifecycleService,
    PartnerService,
    PolicyService,
    ReceiptService,
    VerificationService,
)

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize(**kwargs)

        # Services — order matters: a service that calls get_component() in its
        # __init__ must be constructed after its dependencies.
        CryptoService()
        PartnerService()
        PolicyService()
        ReceiptService()
        VerificationService()
        ConsentService()
        LifecycleService()

        # Controllers.
        VerificationController().post_init()
        WellKnownController().post_init()
        PartnerController().post_init()
        LifecycleController().post_init()
        SubjectController().post_init()

    def migrate_database(self, args):
        super().migrate_database(args)

        async def migrate():
            _logger.info("Migrating consent manager database")
            for model in (
                Partner,
                PartnerKey,
                PartnerPolicy,
                ConsentRequest,
                AuthContext,
                ConsentArtefact,
                ConsentReceipt,
                RevocationRecord,
                DecisionLog,
                AuditLog,
            ):
                await model.create_migrate()
            _logger.info("Database migration complete")

        asyncio.run(migrate())
