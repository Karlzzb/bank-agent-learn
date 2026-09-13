"""仓储层:按领域切分,三个 MCP Server 各自只依赖自己领域的仓储。

接真银行系统时,替换本层实现即可,工具层与 Agent 层不变。
"""

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from bank_agent.core.models import (
    Account,
    Customer,
    KycStatus,
    RequestKind,
    ServiceRequest,
    Transaction,
)


class NotFoundError(Exception):
    """查询对象不存在。"""


def new_request_id() -> str:
    return f"SR-{uuid.uuid4().hex[:8]}"


def get_owned_account(session: Session, customer_id: str, account_id: str) -> Account:
    """取账户并校验归属;不存在或不属于该客户都按"不存在"处理(不泄露他人账户存在性)。"""
    account = session.get(Account, account_id)
    if account is None or account.customer_id != customer_id:
        raise NotFoundError(f"账户不存在:{account_id}")
    return account


class AccountsRepository:
    """账户领域:余额查询。"""

    def __init__(self, session: Session):
        self.session = session

    def list_accounts(self, customer_id: str) -> list[Account]:
        stmt = select(Account).where(Account.customer_id == customer_id)
        return list(self.session.exec(stmt).all())

    def get_account(self, customer_id: str, account_id: str) -> Account:
        return get_owned_account(self.session, customer_id, account_id)


class TransactionsRepository:
    """交易领域:交易明细、结单申请。"""

    def __init__(self, session: Session):
        self.session = session

    def list_transactions(
        self, customer_id: str, account_id: str, limit: int = 10
    ) -> list[Transaction]:
        get_owned_account(self.session, customer_id, account_id)
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.occurred_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def get_transaction(self, customer_id: str, transaction_id: str) -> Transaction:
        txn = self.session.get(Transaction, transaction_id)
        if txn is None:
            raise NotFoundError(f"交易不存在:{transaction_id}")
        get_owned_account(self.session, customer_id, txn.account_id)
        return txn

    def create_statement_request(
        self, customer_id: str, account_id: str, period: str
    ) -> ServiceRequest:
        get_owned_account(self.session, customer_id, account_id)
        req = ServiceRequest(
            id=new_request_id(),
            customer_id=customer_id,
            kind=RequestKind.STATEMENT,
            payload={"account_id": account_id, "period": period},
        )
        self.session.add(req)
        self.session.commit()
        return req


class ServiceRepository:
    """服务领域:改地址、支票簿申请、KYC 更新。写操作真实落库。"""

    def __init__(self, session: Session):
        self.session = session

    def change_address(self, customer_id: str, new_address: str) -> Customer:
        customer = self._get_customer(customer_id)
        customer.address = new_address
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def request_cheque_book(self, customer_id: str, account_id: str) -> ServiceRequest:
        self._get_customer(customer_id)
        get_owned_account(self.session, customer_id, account_id)
        req = ServiceRequest(
            id=new_request_id(),
            customer_id=customer_id,
            kind=RequestKind.CHEQUE_BOOK,
            payload={"account_id": account_id},
        )
        self.session.add(req)
        self.session.commit()
        return req

    def update_kyc(
        self,
        customer_id: str,
        *,
        name: str | None = None,
        phone: str | None = None,
        id_number: str | None = None,
    ) -> Customer:
        customer = self._get_customer(customer_id)
        if name is not None:
            customer.name = name
        if phone is not None:
            customer.phone = phone
        if id_number is not None:
            customer.id_number = id_number
        customer.kyc_status = KycStatus.VERIFIED
        customer.kyc_updated_at = datetime.now(UTC)
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def _get_customer(self, customer_id: str) -> Customer:
        customer = self.session.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"客户不存在:{customer_id}")
        return customer
