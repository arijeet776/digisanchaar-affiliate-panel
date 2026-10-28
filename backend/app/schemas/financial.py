from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class WithdrawalRequestBody(BaseModel):
    # Decimal (not float) at the JSON boundary — pydantic v2 parses a JSON
    # number straight into Decimal without going through a binary float,
    # so `100.10` in the request body can never become `100.09999...`
    # before it reaches financial_service.to_money's precision check.
    amount: Decimal = Field(gt=0)
    idempotency_key: str | None = None


class RejectWithdrawalBody(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A rejection reason is required")
        return v


class MarkPaidBody(BaseModel):
    reference: str | None = None


class ReverseEarningBody(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A reason is required")
        return v


class AdjustmentBody(BaseModel):
    publisher_id: str
    amount: Decimal = Field(gt=0)
    direction: str  # 'credit' | 'debit'
    reason: str

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A reason is required")
        return v
