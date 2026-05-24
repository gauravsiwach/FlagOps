from sqlalchemy import Column, Integer, String, TIMESTAMP, JSON, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class MarketRegistry(Base):
    __tablename__ = "market_registry"
    id = Column(Integer, primary_key=True)
    market_code = Column(String(5), unique=True, nullable=False)
    environment_chain = Column(ARRAY(String), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

class PromotionBatch(Base):
    __tablename__ = "promotion_batches"
    id = Column(String, primary_key=True)
    market_code = Column(String(5), nullable=False)
    from_environment = Column(String(20), nullable=False)
    to_environment = Column(String(20), nullable=False)
    flags_data = Column(JSON)
    status = Column(String(20), nullable=False)
    created_by = Column(String(256))
    created_at = Column(TIMESTAMP, server_default=func.now())
    executed_by = Column(String(256))
    executed_at = Column(TIMESTAMP)

class FlagSnapshot(Base):
    __tablename__ = "flag_snapshots"
    id = Column(Integer, primary_key=True)
    promotion_batch_id = Column(String)
    flag_key = Column(String, nullable=False)
    market_code = Column(String(5), nullable=False)
    environment = Column(String(20), nullable=False)
    rules_before = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    action = Column(String(50), nullable=False)
    promotion_batch_id = Column(String)
    market_code = Column(String(5))
    from_environment = Column(String(20))
    to_environment = Column(String(20))
    flags_affected = Column(JSON)
    executed_by = Column(String(256))
    executed_at = Column(TIMESTAMP, server_default=func.now())
    extra_metadata = Column(JSON)
