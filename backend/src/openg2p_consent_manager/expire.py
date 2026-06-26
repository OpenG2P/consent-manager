#!/usr/bin/env python3
"""Standalone consent-expiry runner.

Invoked as ``python -m openg2p_consent_manager.expire``. Designed to run as a
Kubernetes CronJob (or any external scheduler) rather than an in-process
scheduler — so the API pods stay stateless and horizontally scalable, and the
expiry sweep runs exactly once per tick regardless of replica count.
"""

# ruff: noqa: E402, I001
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from .app import Initializer
from .services import ConsentService

_logger = logging.getLogger(_config.logging_default_logger_name)


def main() -> None:
    # Initialise services + DB engine without serving HTTP.
    Initializer().initialize()
    count = asyncio.run(ConsentService.get_component().expire_stale())
    _logger.info("Expiry run complete: %d artefacts expired", count)


if __name__ == "__main__":
    main()
