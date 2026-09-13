"""账户领域工具实现:余额查询。

工具实现的唯一来源:MCP Server 与进程内工具提供者都复用本模块。
所有工具返回可 JSON 序列化的 dict,异常统一抛 NotFoundError(由调用层转成话术)。
"""

from sqlmodel import Session

from bank_agent.core.repositories import AccountsRepository


def query_balance(session: Session, customer_id: str, account_id: str | None = None) -> dict:
    """查询客户账户余额。不指定账户时返回全部账户。"""
    repo = AccountsRepository(session)
    if account_id is not None:
        accounts = [repo.get_account(customer_id, account_id)]
    else:
        accounts = repo.list_accounts(customer_id)
    return {
        "accounts": [
            {
                "account_id": a.id,
                "account_number": a.account_number,
                "account_type": a.account_type,
                "currency": a.currency,
                "balance": a.balance,
            }
            for a in accounts
        ]
    }
