"""mock IdP:给演示客户签发带 scope 的 JWT。

用法:
    python -m bank_agent.auth.idp C001                 # 全量 scope
    python -m bank_agent.auth.idp C001 accounts:read   # 指定 scope
"""

import sys

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import issue_token
from bank_agent.config import get_settings


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        raise SystemExit(2)
    customer_id = argv[0]
    scopes = set(argv[1:]) or ALL_SCOPES
    unknown = scopes - ALL_SCOPES
    if unknown:
        print(f"未知 scope:{sorted(unknown)};可选:{sorted(ALL_SCOPES)}")
        raise SystemExit(2)
    token = issue_token(get_settings(), customer_id, scopes)
    print(token)


if __name__ == "__main__":
    main(sys.argv[1:])
