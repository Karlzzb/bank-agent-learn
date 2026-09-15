"""交易领域工具实现:交易明细、结单申请。"""

from sqlmodel import Session

from bank_agent.core.repositories import TransactionsRepository


def list_transactions(session: Session, customer_id: str, account_id: str, limit: int = 10) -> dict:
    """查询账户最近的交易列表。用户指定笔数(如"最近三笔")时,limit 必须传该数字。"""
    repo = TransactionsRepository(session)
    txns = repo.list_transactions(customer_id, account_id, limit)
    return {
        "transactions": [
            {
                "transaction_id": t.id,
                "occurred_at": t.occurred_at.isoformat(),
                "amount": t.amount,
                "currency": t.currency,
                "counterparty": t.counterparty,
                "description": t.description,
            }
            for t in txns
        ]
    }


def get_transaction_detail(session: Session, customer_id: str, transaction_id: str) -> dict:
    """查询单笔交易明细。"""
    repo = TransactionsRepository(session)
    t = repo.get_transaction(customer_id, transaction_id)
    return {
        "transaction_id": t.id,
        "account_id": t.account_id,
        "occurred_at": t.occurred_at.isoformat(),
        "amount": t.amount,
        "currency": t.currency,
        "counterparty": t.counterparty,
        "description": t.description,
    }


def request_statement(session: Session, customer_id: str, account_id: str, period: str) -> dict:
    """申请账户结单,生成服务请求并落库。period 如 "2026-08"。"""
    repo = TransactionsRepository(session)
    req = repo.create_statement_request(customer_id, account_id, period)
    return {"request_id": req.id, "kind": req.kind, "status": req.status, "period": period}
