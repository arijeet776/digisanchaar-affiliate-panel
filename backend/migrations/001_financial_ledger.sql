-- Part 9 — Financial ledger. This table is APPEND-ONLY: application code
-- must never UPDATE or DELETE a row here (enforced by convention in the
-- repository layer, since Postgres has no built-in "insert-only" table
-- privilege short of revoking UPDATE/DELETE grants, which deployment can
-- add on top of this for defense in depth). A reversal is a NEW row with
-- transaction_type='earning_reversal', never an edit of the original.
--
-- Every publisher's available balance is a live projection, not a stored
-- column: SUM(amount WHERE direction='credit') - SUM(amount WHERE
-- direction='debit') for that publisher. This keeps the ledger the single
-- source of truth — no second number that can drift out of sync with it.

CREATE TABLE IF NOT EXISTS financial_ledger (
    id                BIGSERIAL PRIMARY KEY,
    ledger_id         TEXT NOT NULL UNIQUE,
    idempotency_key   TEXT NOT NULL UNIQUE,
    transaction_type  TEXT NOT NULL CHECK (transaction_type IN (
                          'earning', 'earning_reversal',
                          'withdrawal_hold', 'withdrawal_release',
                          'adjustment_credit', 'adjustment_debit'
                      )),
    direction         TEXT NOT NULL CHECK (direction IN ('credit', 'debit')),
    publisher_id      TEXT NOT NULL,
    manager_id        TEXT,
    campaign_id       TEXT,
    conversion_id     TEXT,
    withdrawal_id     TEXT,
    amount            NUMERIC(18, 2) NOT NULL CHECK (amount >= 0),
    currency          TEXT NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
    status            TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'voided')),
    source            TEXT NOT NULL,
    reference         TEXT,
    actor_user_id     TEXT,
    request_id        TEXT,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ledger_publisher_created ON financial_ledger (publisher_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_conversion ON financial_ledger (conversion_id) WHERE conversion_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_withdrawal ON financial_ledger (withdrawal_id) WHERE withdrawal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_manager ON financial_ledger (manager_id) WHERE manager_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_campaign ON financial_ledger (campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ledger_transaction_type ON financial_ledger (transaction_type);
