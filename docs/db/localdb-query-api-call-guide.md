# LocalDB 读取链路接口调用开发指导

本文面向需要接入、调试或扩展 `openviking.db.query` 读取链路的开发者，重点覆盖：

- 单元测试 [`tests/unit/test_localdb_query.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_query.py) 当前锁定的行为
- Python API `list_sources()` / `query_events()` / `get_event()` 的调用方式
- 服务端 HTTP 接口 `/api/v1/localdb/sources`、`/api/v1/localdb/query`、`/api/v1/localdb/event`
- 当前 YOYO 双文件布局下的 source 到 URI 解析规则

---

## 1. 当前实现的核心结论

基于 [`tests/unit/test_localdb_query.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_query.py) 和当前实现，读取链路有 4 个关键事实：

1. 读取入口不再只依赖 `viking://user/{user_space}/memories/localdb/{source}/events.jsonl`
   当前还兼容 YOYO 的固定双文件：
   - `userinformation` -> `viking://yoyo/userinformation/default/userinformation.jsonl`
   - `usertendencies` -> `viking://yoyo/usertendencies/default/usertendencies.jsonl`

2. `list_sources()` 现在既会扫描老的 `memories/localdb/.../events.jsonl` 目录，也会把非空的 YOYO 固定文件映射成 source 名返回

3. `query_events()` 的过滤逻辑是“先顺序扫描 JSONL，再按条件过滤，再分页”
   当前不会建立索引，也不会随机访问

4. `get_event()` 会顺序扫描目标 JSONL，找到首个 `event_id` 精确匹配的事件后返回

---

## 2. 入口 API

### 2.1 Python API

核心定义：

- [`list_sources()`](/d:/code/openviking/openviking-private/openviking/db/query.py)
- [`query_events()`](/d:/code/openviking/openviking-private/openviking/db/query.py)
- [`get_event()`](/d:/code/openviking/openviking-private/openviking/db/query.py)
- [`QueryRequest`](/d:/code/openviking/openviking-private/openviking/db/types.py)
- [`GetEventRequest`](/d:/code/openviking/openviking-private/openviking/db/types.py)

推荐导入方式：

```python
from openviking.db import list_sources, query_events, get_event
from openviking.db import QueryRequest, GetEventRequest
```

### 2.2 HTTP API

服务端路由定义在 [`openviking/server/routers/localdb.py`](/d:/code/openviking/openviking-private/openviking/server/routers/localdb.py)。

当前提供：

- `GET /api/v1/localdb/sources`
- `POST /api/v1/localdb/query`
- `GET /api/v1/localdb/event`

这三个接口本质上是对 Python 读链路 API 的 HTTP 封装。

---

## 3. Source 到 URI 的解析规则

核心逻辑在 [`openviking/db/reader.py`](/d:/code/openviking/openviking-private/openviking/db/reader.py)。

当前有一组固定映射：

```python
YOYO_SOURCE_URIS = {
    "userinformation": "viking://yoyo/userinformation/default/userinformation.jsonl",
    "usertendencies": "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}
```

### 3.1 `build_events_uri(user_space, source)` 的行为

解析顺序：

1. 先对 `source` 做归一化
   - 去掉非字母数字字符
   - 小写化

2. 如果归一化后命中 `YOYO_SOURCE_URIS`
   直接返回固定 URI

3. 否则回退到旧格式：

```text
viking://user/{user_space}/memories/localdb/{source}/events.jsonl
```

### 3.2 当前推荐的 source 名

YOYO 场景下建议只使用：

- `userinformation`
- `usertendencies`

例如：

```python
QueryRequest(user_space="default/default", source="userinformation", ...)
QueryRequest(user_space="default/default", source="usertendencies", ...)
```

---

## 4. `list_sources()` 调用指导

### 4.1 Python 调用

```python
sources = await list_sources("default/default", ctx)
print(sources)
```

### 4.2 HTTP 调用

```powershell
python -c "import requests; r=requests.get('http://127.0.0.1:1933/api/v1/localdb/sources', params={'user_space':'default/default'}, timeout=30); print(r.status_code); print(r.text)"
```

### 4.3 当前真实行为

实现见 [`openviking/db/query.py`](/d:/code/openviking/openviking-private/openviking/db/query.py)。

它会做两件事：

1. 扫描：

```text
viking://user/{user_space}/memories/localdb/
```

只把目录下存在 `events.jsonl` 的 source 加入结果

2. 额外检查 `YOYO_SOURCE_URIS`
   - 如果目标文件存在且内容非空
   - 就把对应 source 名加入结果

### 4.4 单测锁定的行为

[`tests/unit/test_localdb_query.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_query.py) 当前验证了：

- 普通 localdb 目录下只有包含 `events.jsonl` 的目录会被返回
- YOYO 固定文件存在且非空时，`list_sources()` 会返回：
  - `userinformation`
  - `usertendencies`

---

## 5. `query_events()` 调用指导

### 5.1 Python 调用

```python
result = await query_events(
    QueryRequest(
        user_space="default/default",
        source="usertendencies",
        event_types=["yoyo_user_tendency"],
        keyword="无糖咖啡",
        offset=0,
        limit=10,
        include_evidence=False,
    ),
    ctx,
)
```

### 5.2 HTTP 调用

```powershell
@'
{
  "user_space": "default/default",
  "source": "usertendencies",
  "event_types": ["yoyo_user_tendency"],
  "keyword": "无糖咖啡",
  "offset": 0,
  "limit": 10,
  "include_evidence": false
}
'@ | python -c "import sys, json, requests; body=json.load(sys.stdin); r=requests.post('http://127.0.0.1:1933/api/v1/localdb/query', json=body, timeout=30); print(r.status_code); print(r.text)"
```

### 5.3 `QueryRequest` 字段语义

定义见 [`openviking/db/types.py`](/d:/code/openviking/openviking-private/openviking/db/types.py)。

- `user_space`
  目前对 YOYO 固定 source 的 URI 选择没有直接影响，但接口仍保留该字段

- `source`
  关键字段，用于决定读哪个 JSONL 文件

- `event_types`
  精确匹配 `event.type`

- `ids`
  精确匹配 `event.id`

- `since` / `until`
  ISO8601 时间过滤

- `keyword`
  对 `event.text` 做大小写不敏感包含匹配

- `offset` / `limit`
  分页参数

- `include_evidence`
  为 `False` 时返回结果里的 `evidence` 会被清空

### 5.4 内部执行顺序

当前 `query_events()` 的主流程：

1. 调 `_validate_query_request()`
   - `offset < 0` 直接报错
   - `limit <= 0` 直接报错

2. 通过 `read_events_file()` 读取目标 URI 的全文

3. 调 `iter_event_dicts()` 逐行解析 JSONL
   - 空行跳过
   - 坏行进入 `errors`

4. 调 `parse_event()` 把 dict 转成 `Event`

5. 调 `match_event()` 做过滤
   - `ids`
   - `event_types`
   - `since`
   - `until`
   - `keyword`

6. 基于匹配顺序做 `offset/limit` 分页

### 5.5 返回结构

返回类型是 [`QueryResult`](/d:/code/openviking/openviking-private/openviking/db/types.py)。

典型结构：

```json
{
  "user_space": "default/default",
  "source": "usertendencies",
  "total": 1,
  "offset": 0,
  "limit": 10,
  "has_more": false,
  "items": [
    {
      "id": "...",
      "type": "yoyo_user_tendency",
      "time": {"ts": "...", "precision": "second"},
      "text": "...无糖咖啡...",
      "attrs": {...},
      "entities": [],
      "evidence": {},
      "privacy": {"redact": true}
    }
  ],
  "errors": []
}
```

---

## 6. `get_event()` 调用指导

### 6.1 Python 调用

```python
event = await get_event(
    GetEventRequest(
        user_space="default/default",
        source="usertendencies",
        event_id="<event_id>",
        include_evidence=True,
    ),
    ctx,
)
```

### 6.2 HTTP 调用

```powershell
python -c "import requests; r=requests.get('http://127.0.0.1:1933/api/v1/localdb/event', params={'user_space':'default/default','source':'usertendencies','event_id':'<event_id>'}, timeout=30); print(r.status_code); print(r.text)"
```

### 6.3 当前真实行为

实现见 [`openviking/db/query.py`](/d:/code/openviking/openviking-private/openviking/db/query.py)。

逻辑很直接：

1. 读取目标 JSONL 文件
2. 顺序扫描每一行
3. 逐条解析成 `Event`
4. 用 `event.id == request.event_id` 做精确匹配
5. 找到即返回，找不到返回 `None`

注意：

- 当前没有索引，属于线性扫描
- 文件越大，单次读取成本越高

---

## 7. `test_localdb_query.py` 实际验证了什么

该测试不是端到端 HTTP 测试，而是读取链路核心逻辑的单元测试。

### 7.1 `iter_event_dicts()` 的容错

验证：

- 会跳过空行
- 会对坏 JSON 返回 `error`

### 7.2 `parse_event(include_evidence=False)` 会清空 evidence

验证：

```python
assert event.evidence == {}
```

### 7.3 `build_events_uri()` 会识别固定 YOYO source

验证：

- `userinformation` -> `viking://yoyo/userinformation/default/userinformation.jsonl`
- `user_tendencies` -> `viking://yoyo/usertendencies/default/usertendencies.jsonl`

说明：
source 名允许带下划线，归一化后仍能命中映射。

### 7.4 `query_events()` 的过滤、分页和错误收集

验证：

- `event_types` 过滤
- `keyword` 过滤
- `since` / `until` 过滤
- `offset` / `limit` 分页
- 坏行进入 `errors`
- `include_evidence=False` 会剥离 evidence

### 7.5 文件不存在时返回空结果

验证：

```python
assert result.total == 0
assert result.items == []
assert result.errors == []
```

### 7.6 `get_event()` 精确返回单条

验证：

- 给定 `event_id`
- 返回正确事件

### 7.7 `list_sources()` 支持两类 source 发现机制

验证：

- 传统目录 + `events.jsonl`
- YOYO 固定 URI

### 7.8 分页参数校验

验证：

- `offset < 0` 抛错

---

## 8. 当前推荐的读取验证顺序

### 8.1 先确认底层 JSONL 可读

```powershell
python scripts/read_yoyo_jsonl.py --max-lines 5
```

适合验证：

- 目标 URI 文件是否存在
- 文件里是否真的有 JSONL

### 8.2 再跑完整读链路验证脚本

```powershell
python scripts/verify_localdb_query.py
```

这份脚本会验证：

- `/api/v1/content/read` 原始读回
- `/api/v1/localdb/sources`
- `/api/v1/localdb/query`
- `/api/v1/localdb/event`

并在前台打印：

- source 列表
- 各 source 总数
- 若干关键词命中摘要
- `get_event` 的完整命中结果

### 8.3 再跑单测锁定核心行为

```powershell
python -m pytest --override-ini addopts="" tests/unit/test_localdb_query.py
```

---

## 9. 常见调用误区

### 9.1 误区：`source="yoyo_history"` 还能读到新数据

不一定。

当前 ingest 默认已经把数据分流到了两个固定 URI：

- `userinformation`
- `usertendencies`

如果 query 侧还继续传 `yoyo_history`，会回退去读旧的：

```text
viking://user/{user_space}/memories/localdb/yoyo_history/events.jsonl
```

这通常不是你现在要的数据。

### 9.2 误区：`include_evidence=False` 会减少匹配数

不会。

它只影响返回结构里的 `evidence` 字段，不影响过滤结果。

### 9.3 误区：`keyword` 搜索的是 `attrs.title`

不是。

当前搜索的是 `event.text`。

只是很多 event 的 `text` 里也包含 `title` 内容，所以看起来像搜到了标题。

### 9.4 误区：`get_event()` 很快

当前不是。

它是全文顺序扫描 JSONL。

如果文件后续变大，需要考虑索引或分片。

---

## 10. 推荐调用模板

### 10.1 列 source

```python
sources = await list_sources("default/default", ctx)
assert "userinformation" in sources
assert "usertendencies" in sources
```

### 10.2 查询个人信息

```python
result = await query_events(
    QueryRequest(
        user_space="default/default",
        source="userinformation",
        event_types=["yoyo_user_information"],
        keyword="王丽",
        limit=3,
        include_evidence=False,
    ),
    ctx,
)
assert result.total >= 1
```

### 10.3 查询偏好

```python
result = await query_events(
    QueryRequest(
        user_space="default/default",
        source="usertendencies",
        event_types=["yoyo_user_tendency"],
        keyword="无糖咖啡",
        limit=3,
    ),
    ctx,
)
assert result.total >= 1
```

### 10.4 先 query 再 get_event

```python
hits = await query_events(
    QueryRequest(
        user_space="default/default",
        source="usertendencies",
        keyword="无糖咖啡",
        limit=1,
    ),
    ctx,
)

event = await get_event(
    GetEventRequest(
        user_space="default/default",
        source="usertendencies",
        event_id=hits.items[0].id,
    ),
    ctx,
)
assert "无糖咖啡" in event.text
```

---

## 11. 调试观察点

实际调试 query 问题时，建议优先看这几项：

- `build_events_uri()` 最终解析出来的是哪个 URI
- `list_sources()` 返回的 source 集合里是否包含目标 source
- `/api/v1/content/read` 对该 URI 是否能直接读出内容
- `query_events()` 返回的 `total` 与 `errors`
- `include_evidence` 是否符合预期
- `keyword` 是否真的出现在 `event.text`

---

## 12. 相关文件

- 单测：
  [`tests/unit/test_localdb_query.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_query.py)
- 核心读取实现：
  [`openviking/db/query.py`](/d:/code/openviking/openviking-private/openviking/db/query.py)
- 读取辅助：
  [`openviking/db/reader.py`](/d:/code/openviking/openviking-private/openviking/db/reader.py)
- 路由：
  [`openviking/server/routers/localdb.py`](/d:/code/openviking/openviking-private/openviking/server/routers/localdb.py)
- 类型：
  [`openviking/db/types.py`](/d:/code/openviking/openviking-private/openviking/db/types.py)
- 读取验证脚本：
  [`scripts/verify_localdb_query.py`](/d:/code/openviking/openviking-private/scripts/verify_localdb_query.py)
- 原始文件查看脚本：
  [`scripts/read_yoyo_jsonl.py`](/d:/code/openviking/openviking-private/scripts/read_yoyo_jsonl.py)
- 一键刷新脚本：
  [`scripts/refresh_yoyo_ingest.py`](/d:/code/openviking/openviking-private/scripts/refresh_yoyo_ingest.py)
