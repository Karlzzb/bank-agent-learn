"""服务领域工具实现:改地址、支票簿申请、KYC 更新。写操作真实落库。"""

from sqlmodel import Session

from bank_agent.core.repositories import ServiceRepository


def change_address(session: Session, customer_id: str, new_address: str) -> dict:
    """修改客户联系地址。"""
    repo = ServiceRepository(session)
    customer = repo.change_address(customer_id, new_address)
    return {"customer_id": customer.id, "address": customer.address}


def request_cheque_book(session: Session, customer_id: str, account_id: str) -> dict:
    """为账户申请新支票簿,生成服务请求并落库。"""
    repo = ServiceRepository(session)
    req = repo.request_cheque_book(customer_id, account_id)
    return {"request_id": req.id, "kind": req.kind, "status": req.status, "account_id": account_id}


def update_kyc(
    session: Session,
    customer_id: str,
    name: str | None = None,
    phone: str | None = None,
    id_number: str | None = None,
) -> dict:
    """更新客户 KYC 资料(姓名/手机号/证件号),更新后状态置为 verified。"""
    repo = ServiceRepository(session)
    customer = repo.update_kyc(customer_id, name=name, phone=phone, id_number=id_number)
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "kyc_status": customer.kyc_status,
    }
