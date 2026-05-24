-- Initial schema for GrowthBook Feature Flag Ops
-- Created by: app/db.py

CREATE TABLE IF NOT EXISTS market_registry (
    id SERIAL PRIMARY KEY,
    market_code VARCHAR(5) UNIQUE NOT NULL,
    environment_chain TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promotion_batches (
    id VARCHAR PRIMARY KEY,
    market_code VARCHAR(5) NOT NULL,
    from_environment VARCHAR(20) NOT NULL,
    to_environment VARCHAR(20) NOT NULL,
    flags_data JSONB,
    status VARCHAR(20) NOT NULL,
    created_by VARCHAR(256),
    created_at TIMESTAMP DEFAULT NOW(),
    executed_by VARCHAR(256),
    executed_at TIMESTAMP,
    FOREIGN KEY (market_code) REFERENCES market_registry(market_code)
);

CREATE TABLE IF NOT EXISTS flag_snapshots (
    id SERIAL PRIMARY KEY,
    promotion_batch_id VARCHAR NOT NULL,
    flag_key VARCHAR NOT NULL,
    market_code VARCHAR(5) NOT NULL,
    environment VARCHAR(20) NOT NULL,
    rules_before JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (promotion_batch_id) REFERENCES promotion_batches(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL,
    promotion_batch_id VARCHAR,
    market_code VARCHAR(5),
    from_environment VARCHAR(20),
    to_environment VARCHAR(20),
    flags_affected JSONB,
    executed_by VARCHAR(256),
    executed_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,
    FOREIGN KEY (promotion_batch_id) REFERENCES promotion_batches(id)
);
