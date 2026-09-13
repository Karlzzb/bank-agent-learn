"""种子数据:演示客户张三(C001)、李四(C002)及其账户、交易。

用法:python -m bank_agent.core.seed
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from bank_agent.config import get_settings
from bank_agent.core.db import init_db, make_engine
from bank_agent.core.models import Account, AccountType, Customer, KycStatus, Transaction

DEMO_CUSTOMER_ID = "C001"
OTHER_CUSTOMER_ID = "C002"


def seed(session: Session) -> None:
    if session.get(Customer, DEMO_CUSTOMER_ID) is not None:
        return  # 幂等:已播种则跳过
    session.add(
        Customer(
            id=DEMO_CUSTOMER_ID,
            name="张三",
            phone="13800001111",
            id_number="110101199001011234",
            address="北京市朝阳区建国路 1 号",
            kyc_status=KycStatus.VERIFIED,
        )
    )
    session.add_all(
        [
            Account(
                id="A001",
                customer_id=DEMO_CUSTOMER_ID,
                account_number="6222020200112233",
                account_type=AccountType.SAVINGS,
                balance=12800.50,
            ),
            Account(
                id="A002",
                customer_id=DEMO_CUSTOMER_ID,
                account_number="6222020200445566",
                account_type=AccountType.CHECKING,
                balance=3200.00,
            ),
        ]
    )
    # 第二个客户:跨用户隔离与越权测试用
    if session.get(Customer, OTHER_CUSTOMER_ID) is None:
        session.add(
            Customer(
                id=OTHER_CUSTOMER_ID,
                name="李四",
                phone="13900009999",
                id_number="110101199202024321",
                address="上海市徐汇区漕溪北路 100 号",
                kyc_status=KycStatus.VERIFIED,
            )
        )
        session.add(
            Account(
                id="A101",
                customer_id=OTHER_CUSTOMER_ID,
                account_number="6222020200778899",
                account_type=AccountType.SAVINGS,
                balance=500.00,
            )
        )
    base = datetime.now(UTC)
    txns = [
        ("T001", "A001", -58.00, "星巴克", "咖啡消费", 1),
        ("T002", "A001", 15000.00, "某公司", "工资入账", 3),
        ("T003", "A001", -2000.00, "房东", "房租", 5),
        ("T004", "A002", -320.50, "京东商城", "网购", 2),
        ("T005", "A002", -66.00, "滴滴出行", "打车", 4),
    ]
    for tid, account_id, amount, counterparty, desc, days_ago in txns:
        session.add(
            Transaction(
                id=tid,
                account_id=account_id,
                occurred_at=base - timedelta(days=days_ago),
                amount=amount,
                counterparty=counterparty,
                description=desc,
            )
        )
    session.commit()


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.bank_db_path)
    init_db(engine)
    with Session(engine) as session:
        seed(session)
    print(f"种子数据已写入 {settings.bank_db_path}(客户 {DEMO_CUSTOMER_ID} 张三)")


if __name__ == "__main__":
    main()
