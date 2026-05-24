"""Database initialization, seeding, and session management (repositories).

This module now exposes a single async engine and sessionmaker instance that
is created at startup to avoid creating/disposing engines on every call.
"""
import os
import asyncpg
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models import Base, MarketRegistry

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:admin@localhost:5432/gb_flag_ops")

# Shared engine and sessionmaker — initialized by `init_engine()` at startup
engine: Optional[AsyncEngine] = None
async_session: Optional[sessionmaker] = None


def init_engine():
    """Initialize the module-level async engine and sessionmaker.

    Call this once on application startup.
    """
    global engine, async_session
    if engine is None:
        engine = create_async_engine(DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def ensure_database_exists():
    url = DATABASE_URL.replace("postgresql+asyncpg://", "")
    userpass, hostdb = url.split("@")
    user, password = userpass.split(":")
    hostport, dbname = hostdb.rsplit("/", 1)
    host, port = (hostport.split(":") + ["5432"])[:2]

    try:
        conn = await asyncpg.connect(
            user=user, password=password, host=host, port=int(port), database="postgres"
        )
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", dbname)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"✅ Database '{dbname}' created.")
        else:
            print(f"ℹ️  Database '{dbname}' already exists.")
        await conn.close()
    except Exception as e:
        print(f"⚠️  Could not ensure DB exists: {e}")


async def init_db():
    # Use shared engine
    if engine is None:
        init_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ready.")


async def seed_markets():
    # Use shared engine/session
    if engine is None:
        init_engine()

    async with async_session() as session:
        # Delete stale AU entry if it exists
        result = await session.execute(
            select(MarketRegistry).where(MarketRegistry.market_code == "AU")
        )
        stale_au = result.scalars().first()
        if stale_au:
            await session.delete(stale_au)
            await session.commit()
            print("🗑  Stale Market AU deleted.")
        
        # Ensure Market IN exists
        result = await session.execute(
            select(MarketRegistry).where(MarketRegistry.market_code == "IN")
        )
        existing = result.scalars().first()

        if not existing:
            session.add(MarketRegistry(
                market_code="IN",
                environment_chain=["dev", "qa", "uat", "pre-prod", "production"]
            ))
            await session.commit()
            print("✅ Market IN seeded.")
        else:
            existing.environment_chain = ["dev", "qa", "uat", "pre-prod", "production"]
            await session.commit()
            print("ℹ️  Market IN already exists — env chain updated.")

    # keep engine alive for app lifecycle


async def init_db_on_startup():
    # Ensure DB exists then initialize shared engine and create tables
    await ensure_database_exists()
    init_engine()
    await init_db()
    await seed_markets()


async def create_promotion_batch(batch_id: str, market_code: str, from_environment: str, to_environment: str, flags_data: dict, status: str = "pending"):
    """Create a PromotionBatch record with provided data."""
    if async_session is None:
        init_engine()

    async with async_session() as session:
        try:
            from app.models.database import PromotionBatch

            pb = PromotionBatch(
                id=batch_id,
                market_code=market_code,
                from_environment=from_environment,
                to_environment=to_environment,
                flags_data=flags_data,
                status=status,
            )
            session.add(pb)
            await session.commit()
            logger.info("Created PromotionBatch", extra={"batch_id": batch_id, "market": market_code, "from_env": from_environment, "to_env": to_environment})
        except Exception:
            await session.rollback()
            logger.exception("Failed to create PromotionBatch", extra={"batch_id": batch_id})
            raise


async def update_promotion_batch_resolutions(batch_id: str, resolutions: dict):
    """Update an existing PromotionBatch with resolutions and mark validated."""
    if async_session is None:
        init_engine()

    async with async_session() as session:
        try:
            from app.models.database import PromotionBatch

            result = await session.execute(
                select(PromotionBatch).where(PromotionBatch.id == batch_id)
            )
            pb = result.scalars().first()
            if not pb:
                return None

            existing = pb.flags_data or {}
            existing["resolutions"] = resolutions
            pb.flags_data = existing
            pb.status = "validated"
            await session.commit()
            logger.info("Updated PromotionBatch resolutions", extra={"batch_id": batch_id})
            return pb
        except Exception:
            await session.rollback()
            logger.exception("Failed to update PromotionBatch resolutions", extra={"batch_id": batch_id})
            raise
