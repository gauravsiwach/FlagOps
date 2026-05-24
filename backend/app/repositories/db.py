"""Database initialization, seeding, and session management (repositories)."""
import os
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models import Base, MarketRegistry

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:admin@localhost:5432/gb_flag_ops")


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
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("✅ Database tables ready.")


async def seed_markets():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

    await engine.dispose()


async def init_db_on_startup():
    await ensure_database_exists()
    await init_db()
    await seed_markets()
