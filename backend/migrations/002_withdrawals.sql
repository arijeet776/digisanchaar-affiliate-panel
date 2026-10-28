-- Part 9 — Withdrawal requests. This table holds WORKFLOW state (which
-- status a request is in) — the actual money movement it represents is
-- recorded immutably in financial_ledger via a 'withdrawal_hold' entry at
-- request time and, if rejected/cancelled, a 'withdrawal_release' entry.
-- A row here MAY have its status/reviewed_by/paid_by/reference columns
-- updated (that's workflow progress, not rewriting financial truth) but
-- its requested amount/publisher/currency are never altered after creation.

CREATE TABLE IF NOT EXISTS withdrawals (
    id                 BIGSERIAL PRIMARY KEY,
    withdrawal_id      TEXT NOT NULL UNIQUE,
    idempotency_key    TEXT UNIQUE,
    publisher_id       TEXT NOT NULL,
    manager_id         TEXT,
    amount             NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency           TEXT NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
    status             TEXT NOT NULL DEFAULT 'requested' CHECK (status IN (
                           'requested', 'under_review', 'approved', 'paid',
                           'rejected', 'cancelled'
                       )),
    reference          TEXT,
    rejection_reason   TEXT,
    requested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by        TEXT,
    paid_by            TEXT
);

CREATE INDEX IF NOT EXISTS idx_withdrawals_publisher ON withdrawals (publisher_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_withdrawals_manager ON withdrawals (manager_id) WHERE manager_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals (status);
