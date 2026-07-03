# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer

from .controllers import (
    AweController,
    LifecycleController,
    PartnerController,
    SubjectController,
    VerificationController,
    WellKnownController,
)
from .models import (
    AuditLog,
    AuthContext,
    AweProcessedEvent,
    ConsentArtefact,
    ConsentReceipt,
    ConsentRequest,
    DecisionLog,
    Partner,
    PartnerPolicy,
    RevocationRecord,
)
from .services import (
    AweClient,
    AweWebhookService,
    ConsentService,
    CryptoService,
    LifecycleService,
    PartnerMgmtKeyStore,
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
        PartnerMgmtKeyStore()
        PolicyService()
        ReceiptService()
        VerificationService()
        ConsentService()
        LifecycleService()
        AweClient()
        AweWebhookService()  # depends on PartnerService

        # Controllers.
        VerificationController().post_init()
        WellKnownController().post_init()
        PartnerController().post_init()
        LifecycleController().post_init()
        SubjectController().post_init()
        AweController().post_init()

    def migrate_database(self, args):
        super().migrate_database(args)

        async def migrate():
            _logger.info("Migrating consent manager database")
            for model in (
                Partner,
                PartnerPolicy,
                ConsentRequest,
                AuthContext,
                ConsentArtefact,
                ConsentReceipt,
                RevocationRecord,
                DecisionLog,
                AuditLog,
                AweProcessedEvent,
            ):
                await model.create_migrate()

            # create_migrate() only creates missing tables; it does not ALTER an
            # existing one. Add the AWE onboarding columns idempotently so a DB
            # created before the AWE integration picks them up on next migrate.
            from openg2p_fastapi_common.context import dbengine
            from sqlalchemy import text

            async with dbengine.get().begin() as conn:
                await conn.execute(
                    text(
                        "ALTER TABLE partners ADD COLUMN IF NOT EXISTS "
                        "approval_status VARCHAR(20) NOT NULL DEFAULT 'not_required'"
                    )
                )
                await conn.execute(
                    text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS awe_request_id VARCHAR(64)")
                )
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_partners_awe_request_id "
                        "ON partners (awe_request_id)"
                    )
                )
                # Partner keys moved to Partner Management — partners now carry a
                # PM reference instead of local keys / a jwks_url.
                await conn.execute(
                    text(
                        "ALTER TABLE partners ADD COLUMN IF NOT EXISTS "
                        "partner_mgmt_id VARCHAR(255)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_partners_partner_mgmt_id "
                        "ON partners (partner_mgmt_id)"
                    )
                )
            _logger.info("Database migration complete")

        asyncio.run(migrate())
