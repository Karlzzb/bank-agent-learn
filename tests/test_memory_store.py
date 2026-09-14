"""SqliteStore 单元测试:BaseStore 契约行为 + SQLite 持久化接缝。"""

from datetime import datetime

import pytest

from bank_agent.memory import SqliteStore


@pytest.fixture
def store(tmp_path):
    return SqliteStore(str(tmp_path / "store.sqlite3"))


def test_put_get_roundtrip(store):
    value = {"name": "张三", "prefs": {"theme": "dark", "tags": ["vip", "sms"]}}
    store.put(("profiles", "C001"), "profile", value)
    item = store.get(("profiles", "C001"), "profile")
    assert item is not None
    assert item.namespace == ("profiles", "C001")
    assert item.key == "profile"
    assert item.value == value  # 嵌套 dict/list 原样往返
    assert isinstance(item.created_at, datetime)
    assert isinstance(item.updated_at, datetime)


def test_get_missing_returns_none(store):
    assert store.get(("profiles", "C001"), "nope") is None


def test_put_none_deletes(store):
    store.put(("profiles", "C001"), "profile", {"name": "张三"})
    store.put(("profiles", "C001"), "profile", None)
    assert store.get(("profiles", "C001"), "profile") is None
    # delete() helper 等价路径
    store.put(("profiles", "C001"), "profile", {"name": "张三"})
    store.delete(("profiles", "C001"), "profile")
    assert store.get(("profiles", "C001"), "profile") is None


def test_search_prefix_boundary(store):
    store.put(("a", "b"), "k1", {"n": 1})
    store.put(("a", "bc"), "k2", {"n": 2})
    store.put(("a", "b", "c"), "k3", {"n": 3})
    keys = {item.key for item in store.search(("a", "b"))}
    # ("a", "b") 命中自身与更深的子命名空间,但不能前缀误伤 ("a", "bc")
    assert keys == {"k1", "k3"}


def test_search_filter_and_pagination(store):
    for i in range(5):
        store.put(("memos", "C001"), f"m{i}", {"idx": i, "kind": "note" if i % 2 else "task"})
    # 等值过滤
    notes = store.search(("memos",), filter={"kind": "note"})
    assert {item.value["idx"] for item in notes} == {1, 3}
    # limit/offset 分页(按 created_at, key 排序)
    page = store.search(("memos", "C001"), limit=2, offset=1)
    assert [item.key for item in page] == ["m1", "m2"]


def test_namespace_isolation_between_customers(store):
    store.put(("profiles", "C001"), "profile", {"name": "张三"})
    store.put(("profiles", "C002"), "profile", {"name": "李四"})
    # 同名 key 在不同客户命名空间下互不可见
    assert store.get(("profiles", "C001"), "profile").value == {"name": "张三"}
    results = store.search(("profiles", "C001"))
    assert [item.value["name"] for item in results] == ["张三"]


def test_persistence_across_instances(tmp_path):
    # 同一文件路径新建第二个实例,能读到第一个实例写入的数据:
    # 这是"进程重启后长期记忆仍在"的接缝。
    path = str(tmp_path / "store.sqlite3")
    first = SqliteStore(path)
    first.put(("profiles", "C001"), "profile", {"name": "张三"})
    second = SqliteStore(path)
    item = second.get(("profiles", "C001"), "profile")
    assert item is not None and item.value == {"name": "张三"}


def test_list_namespaces(store):
    store.put(("profiles", "C001"), "p", {"x": 1})
    store.put(("profiles", "C002"), "p", {"x": 2})
    store.put(("memos",), "m", {"x": 3})
    assert store.list_namespaces() == [("memos",), ("profiles", "C001"), ("profiles", "C002")]
    # max_depth 截断
    assert store.list_namespaces(max_depth=1) == [("memos",), ("profiles",)]
    # limit/offset
    assert store.list_namespaces(limit=1, offset=1) == [("profiles", "C001")]


def test_list_namespaces_match_conditions_unsupported(store):
    store.put(("profiles", "C001"), "p", {"x": 1})
    with pytest.raises(NotImplementedError):
        store.list_namespaces(prefix=("profiles",))


async def test_async_helpers(tmp_path):
    # abatch 与 BaseStore async helper 的兼容走查
    store = SqliteStore(str(tmp_path / "store.sqlite3"))
    await store.aput(("profiles", "C001"), "profile", {"name": "张三", "vip": True})
    item = await store.aget(("profiles", "C001"), "profile")
    assert item is not None and item.value == {"name": "张三", "vip": True}
    results = await store.asearch(("profiles",), filter={"vip": True})
    assert [i.key for i in results] == ["profile"]
    assert ("profiles", "C001") in await store.alist_namespaces()
    await store.adelete(("profiles", "C001"), "profile")
    assert await store.aget(("profiles", "C001"), "profile") is None
