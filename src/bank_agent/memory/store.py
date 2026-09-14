"""SQLite 落地的 LangGraph BaseStore:跨进程/重启可持久的长期记忆。

只实现 BaseStore 的两个抽象方法 batch/abatch,get/put/search 等 helper 均由基类
基于 batch 派生,因此结果形状必须与基类消费方严格对齐(GetOp→Item|None,
PutOp→None,SearchOp→list[SearchItem],ListNamespacesOp→list[tuple])。

不支持的特性(与 InMemoryStore 未配置 index 时的行为对齐):
- 语义检索:PutOp.index 忽略;SearchOp.query 非 None 时忽略,退化为按前缀列出;
- TTL:PutOp.ttl 忽略(基类在 supports_ttl=False 时已对显式 ttl 报错)。
"""

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

# 命名空间 tuple 拼成单列存储,分隔符选 ".":
# BaseStore.put 的 _validate_namespace 已拒绝含 "." 的段名,故 "." 不会出现在段内,
# 拼接无歧义;直接调 batch 绕过校验的用法在本项目不存在(教学项目从简)。
_NS_SEP = "."


def _encode_ns(namespace: tuple[str, ...]) -> str:
    return _NS_SEP.join(namespace)


def _decode_ns(namespace: str) -> tuple[str, ...]:
    return tuple(namespace.split(_NS_SEP))


def _to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


class SqliteStore(BaseStore):
    """单文件 SQLite 存储:(namespace, key) 主键,value 存 JSON 文本。

    线程安全:单连接 + check_same_thread=False + 一把互斥锁。
    教学项目从简,本地 SQLite 操作微秒级,单连接无并发瓶颈。
    """

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS store (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
                """
            )
            self._conn.commit()

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        with self._lock:
            for op in ops:
                if isinstance(op, GetOp):
                    results.append(self._get(op))
                elif isinstance(op, PutOp):
                    self._put(op)
                    results.append(None)
                elif isinstance(op, SearchOp):
                    results.append(self._search(op))
                elif isinstance(op, ListNamespacesOp):
                    results.append(self._list_namespaces(op))
                else:
                    raise ValueError(f"未知操作类型: {type(op)}")
            self._conn.commit()
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        # 本地 SQLite 操作微秒级,直接复用同步实现;async 包装只为满足接口,
        # 无阻塞事件循环的实际顾虑(教学项目从简)。
        return self.batch(ops)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _get(self, op: GetOp) -> Item | None:
        row = self._conn.execute(
            "SELECT value, created_at, updated_at FROM store WHERE namespace = ? AND key = ?",
            (_encode_ns(op.namespace), op.key),
        ).fetchone()
        if row is None:
            return None
        value_str, created_at, updated_at = row
        return Item(
            value=json.loads(value_str),
            key=op.key,
            namespace=op.namespace,
            created_at=_to_dt(created_at),
            updated_at=_to_dt(updated_at),
        )

    def _put(self, op: PutOp) -> None:
        ns = _encode_ns(op.namespace)
        if op.value is None:
            self._conn.execute("DELETE FROM store WHERE namespace = ? AND key = ?", (ns, op.key))
            return
        now = time.time()
        # 更新时保留首次 created_at,只刷新 value 与 updated_at。
        self._conn.execute(
            """
            INSERT INTO store (namespace, key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                value = excluded.value, updated_at = excluded.updated_at
            """,
            (ns, op.key, json.dumps(op.value, ensure_ascii=False), now, now),
        )

    def _search(self, op: SearchOp) -> list[SearchItem]:
        # 全量扫表后 Python 侧过滤:教学项目数据量小,换来前缀边界与 JSON 过滤的清晰实现。
        rows = self._conn.execute(
            "SELECT namespace, key, value, created_at, updated_at FROM store"
            " ORDER BY created_at, key"
        ).fetchall()
        prefix = op.namespace_prefix
        items: list[SearchItem] = []
        for ns_str, key, value_str, created_at, updated_at in rows:
            ns = _decode_ns(ns_str)
            # 前缀按段对齐:("profiles", "C001") 不能匹配 ("profiles", "C0012")
            if len(ns) < len(prefix) or ns[: len(prefix)] != prefix:
                continue
            value = json.loads(value_str)
            # filter:按 value 顶层字段等值过滤
            if op.filter and any(value.get(k) != v for k, v in op.filter.items()):
                continue
            items.append(
                SearchItem(
                    namespace=ns,
                    key=key,
                    value=value,
                    created_at=_to_dt(created_at),
                    updated_at=_to_dt(updated_at),
                    score=None,  # 无语义检索,score 恒为 None
                )
            )
        return items[op.offset : op.offset + op.limit]

    def _list_namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        """列出 distinct 命名空间,支持 max_depth 截断与分页。

        match_conditions 非空时抛 NotImplementedError:本项目只用全量列出。
        注意基类 list_namespaces() 不带参数时传的是空 tuple(而非 None),空条件视为全量。
        """
        if op.match_conditions:
            raise NotImplementedError(
                "SqliteStore 暂不支持 match_conditions,仅支持全量列出命名空间"
            )
        rows = self._conn.execute("SELECT DISTINCT namespace FROM store").fetchall()
        namespaces = {_decode_ns(ns) for (ns,) in rows}
        if op.max_depth is not None:
            namespaces = {ns[: op.max_depth] for ns in namespaces}
        ordered = sorted(namespaces)
        return ordered[op.offset : op.offset + op.limit]
