"""Railway pre-deploy bootstrap for database migrations and baseline data.

Database bootstrap runs before the web container starts. Keeping this work out of
FastAPI's lifespan lets Uvicorn bind to Railway's PORT immediately, so the
platform healthcheck is not blocked by database latency.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.db.seed import run_seed

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    alembic_cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied successfully.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_migrations()
    run_seed()
    logger.info("Pre-deploy database bootstrap completed successfully.")


if __name__ == "__main__":
    main()
