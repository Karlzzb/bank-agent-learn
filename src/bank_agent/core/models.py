"""mock 银行核心:领域实体。

所有下游均为 mock,但按真实领域形状设计:接真系统时替换仓储层即可。
状态类字段用 Literal 约束取值,避免自由字符串漂移。
"""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class KycStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"


class AccountType(StrEnum):
    SAVINGS = "savings"
    CHECKING = "checking"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class RequestKind(StrEnum):
    STATEMENT = "statement"
    ADDRESS_CHANGE = "address_change"
    CHEQUE_BOOK = "cheque_book"
    KYC_UPDATE = "kyc_update"


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    DONE = "done"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Customer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    phone: str
    id_number: str
    address: str
    kyc_status: KycStatus = KycStatus.PENDING
    kyc_updated_at: datetime | None = None


class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(index=True)
    account_number: str = Field(unique=True)
    account_type: AccountType
    currency: str = "CNY"
    balance: float = 0.0
    status: AccountStatus = AccountStatus.ACTIVE


class Transaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(index=True)
    occurred_at: datetime
    amount: float  # 正为入账,负为出账
    currency: str = "CNY"
    counterparty: str = ""
    description: str = ""


class ServiceRequest(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(index=True)
    kind: RequestKind
    status: RequestStatus = RequestStatus.SUBMITTED
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
