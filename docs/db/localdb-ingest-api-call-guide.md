# LocalDB 写入链路接口调用开发指导

本文面向需要接入或调试 `openviking.db.ingest` 写入链路的开发者，重点覆盖：

- 单元测试 [`tests/unit/test_localdb_ingest.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_ingest.py) 当前锁定的行为
- 服务端 HTTP 接口 `/api/v1/localdb/ingest` 的调用方式
- `ingest()` 内部真实执行顺序
- 现阶段 YOYO 场景下的固定输入/固定输出约束

---

## 1. 当前实现的核心结论

基于 [`tests/unit/test_localdb_ingest.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_ingest.py)，当前写入链路有 3 个关键事实：

1. 实际读取的 SQLite 路径是固定值，不依赖调用方传入的 `db_path`
   固定路径定义在 [`openviking/db/ingest.py`](/d:/code/openviking/openviking-private/openviking/db/ingest.py)：
   `D:\HONOR Share\YOYO History\yoyochat2.db`

2. 默认写入目标不是单一 `events.jsonl`，而是按表名分流到两个固定 URI
   - `user_information` -> `viking://yoyo/userinformation/default/userinformation.jsonl`
   - `user_tendencies` -> `viking://yoyo/usertendencies/default/usertendencies.jsonl`

3. 每条写入事件的 `evidence.db` 会记录固定 SQLite 路径

这意味着：调用侧即使传入别的 `db_path`，当前实现也不会使用；真正决定写入位置的是 mapping 中的 `table` 或显式 `output_uri`。

---

## 2. 入口接口

### 2.1 Python API

调用入口：

- [`ingest()`](/d:/code/openviking/openviking-private/openviking/db/ingest.py)
- [`IngestRequest`](/d:/code/openviking/openviking-private/openviking/db/types.py)

示例：

```python
from openviking.db import IngestRequest, ingest

report = await ingest(
    IngestRequest(
        db_path=r"C:\ignored.db",  # 当前实现会忽略，实际固定读取 YOYO DB
        user_space="default/default",
        source="yoyo_history",
        config_path=r"D:\code\openviking\openviking-private\examples\localdb_yoyo_mapping.yaml",
        dry_run=False,
        redact=True,
    )
)
```

### 2.2 HTTP API

服务端路由定义在 [`openviking/server/routers/localdb.py`](/d:/code/openviking/openviking-private/openviking/server/routers/localdb.py)。

接口：

```text
POST /api/v1/localdb/ingest
```

请求体：

```json
{
  "db_path": "C:\\ignored.db",
  "user_space": "default/default",
  "source": "yoyo_history",
  "config_path": "examples/localdb_yoyo_mapping.yaml",
  "dry_run": false,
  "redact": true
}
```

说明：

- `db_path` 目前可省略，也可传任意值，但当前实现会被固定路径覆盖
- `config_path` 支持绝对路径，也支持仓库根目录相对路径
- 该接口要求 ROOT 权限

---

## 3. 一次写入调用的真实执行顺序

当前 `ingest()` 的内部主流程在 [`openviking/db/ingest.py`](/d:/code/openviking/openviking-private/openviking/db/ingest.py) 中，大致如下：

1. 解析实际 DB 路径
   - `_resolve_db_path()` 直接返回固定常量 `YOYO_SQLITE_DB_PATH`

2. 校验 DB 是否存在
   - 如果固定路径不存在，直接抛 `FileNotFoundError`

3. 加载 mapping
   - 调用 [`load_mapping_config()`](/d:/code/openviking/openviking-private/openviking/db/config.py)
   - 支持 YAML / JSON

4. 只读打开 SQLite
   - 调用 [`open_sqlite_readonly()`](/d:/code/openviking/openviking-private/openviking/db/sqlite_reader.py)
   - 若只读打开失败，会复制到临时目录后再打开

5. 构造 ROOT 上下文
   - 从 `user_space` 拆出 `account/user/agent`
   - 用 ROOT 角色构造 `RequestContext`

6. 遍历每个 extract item
   - 按 `item.table` 或 `item.output_uri` 解析写入目标 URI
   - 执行 SQL
   - 对每一行调用 [`build_event()`](/d:/code/openviking/openviking-private/openviking/db/normalize.py)
   - 调用 [`append_jsonl()`](/d:/code/openviking/openviking-private/openviking/db/writer.py) 追加写入

7. 汇总 `IngestReport`
   - 返回写入 URI、总行数、失败数、样例事件等

---

## 4. 写入目标 URI 是如何决定的

默认映射常量在 [`openviking/db/ingest.py`](/d:/code/openviking/openviking-private/openviking/db/ingest.py)：

```python
YOYO_TABLE_OUTPUT_URIS = {
    "userinformation": "viking://yoyo/userinformation/default/userinformation.jsonl",
    "usertendencies": "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}
```

解析规则：

1. 如果 extract 配了 `output_uri`
   使用该值，支持模板变量：
   - `{user_space}`
   - `{source}`
   - `{db_path}`

2. 如果 extract 没配 `output_uri`
   则根据 `table` 做归一化后查 `YOYO_TABLE_OUTPUT_URIS`

3. 如果 `table` 无法映射
   当前实现会报错：
   `extract table is not mapped to a VikingFS target`

也就是说，当前 YOYO 方案下推荐的 mapping 写法是：

```yaml
extract:
  - id: yoyo_user_information_profile
    table: user_information
    output_uri: viking://yoyo/userinformation/default/userinformation.jsonl
    ...

  - id: yoyo_user_tendencies_preference
    table: user_tendencies
    output_uri: viking://yoyo/usertendencies/default/usertendencies.jsonl
    ...
```

参考：
[`examples/localdb_yoyo_mapping.yaml`](/d:/code/openviking/openviking-private/examples/localdb_yoyo_mapping.yaml)

---

## 5. `IngestRequest` 字段的当前语义

定义见 [`openviking/db/types.py`](/d:/code/openviking/openviking-private/openviking/db/types.py)。

### 5.1 `db_path`

保留字段，但当前 YOYO 场景下不会实际生效。

建议：

- 调用方可以传空字符串
- 或传文档化占位值
- 不要假设它会切换实际读取的 DB

### 5.2 `user_space`

主要作用：

- 构造 ROOT `RequestContext`
- 在显式 `output_uri` 模板里可用于变量替换

当前固定 YOYO 输出 URI 不依赖 `user_space`，但接口层仍保留该字段。

### 5.3 `source`

当前固定 YOYO 输出 URI 不依赖 `source`，但它仍参与：

- 事件 ID 生成
- `output_uri` 模板变量替换
- `report` 中的调用语义

### 5.4 `config_path`

必须有效。

当前支持：

- 绝对路径
- 仓库根目录相对路径

例如：

```text
examples/localdb_yoyo_mapping.yaml
```

或：

```text
D:\code\openviking\openviking-private\examples\localdb_yoyo_mapping.yaml
```

### 5.5 `since`

仅当 mapping SQL 使用了 `:since` 或 `:since_ts` 才会生效。

当前 `examples/localdb_yoyo_mapping.yaml` 未使用增量条件，因此通常没有效果。

### 5.6 `dry_run`

为 `true` 时：

- 会执行 SQL
- 会构造 event
- 会生成 report / samples
- 不会真的落盘到 VikingFS

### 5.7 `redact`

会透传到 `build_event()`，目前主要影响 URL 字段的脱敏。

YOYO 这套 mapping 当前主要用 `title` 文本，不依赖 URL。

---

## 6. `IngestReport` 怎么看

`IngestReport` 定义见 [`openviking/db/types.py`](/d:/code/openviking/openviking-private/openviking/db/types.py)。

典型返回结构：

```json
{
  "db_path": "D:\\HONOR Share\\YOYO History\\yoyochat2.db",
  "output_uri": "viking://yoyo/userinformation/default/userinformation.jsonl",
  "output_uris": [
    "viking://yoyo/userinformation/default/userinformation.jsonl",
    "viking://yoyo/usertendencies/default/usertendencies.jsonl"
  ],
  "total_rows": 39,
  "written": 39,
  "failed": 0,
  "opened_via_copy": false,
  "items": [
    {
      "id": "yoyo_user_information_profile",
      "output_uri": "viking://yoyo/userinformation/default/userinformation.jsonl",
      "rows": 10,
      "written": 10,
      "failed": 0
    },
    {
      "id": "yoyo_user_tendencies_preference",
      "output_uri": "viking://yoyo/usertendencies/default/usertendencies.jsonl",
      "rows": 29,
      "written": 29,
      "failed": 0
    }
  ],
  "errors": [],
  "samples": [...]
}
```

重点看：

- `db_path`
  是否确实是固定 YOYO DB 路径

- `output_uris`
  是否是两个目标 URI

- `written`
  是否等于预期总行数

- `items[*].rows/written`
  是否与各表行数匹配

- `errors`
  应为空

---

## 7. `test_localdb_ingest.py` 实际验证了什么

该测试不是端到端集成测试，而是写入链路的“核心行为单测”。

位置：
[`tests/unit/test_localdb_ingest.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_ingest.py)

它通过 monkeypatch 隔离了外部依赖，验证以下约束：

### 7.1 固定 DB 路径覆盖

测试把 `os.path.exists()` 打桩成只有 `YOYO_SQLITE_DB_PATH` 返回 `True`。

断言：

```python
assert report.db_path == YOYO_SQLITE_DB_PATH
```

说明：
`IngestRequest.db_path` 当前不会决定最终读取的 SQLite。

### 7.2 按表写入固定 URI

测试注入两个 `ExtractItem`：

- `table="user_information"`
- `table="user_tendencies"`

并断言：

```python
assert report.output_uris == [
    "viking://yoyo/userinformation/default/userinformation.jsonl",
    "viking://yoyo/usertendencies/default/usertendencies.jsonl",
]
```

说明：
URI 路由是当前写入链路的关键契约。

### 7.3 写入事件里的 `evidence.db` 正确

测试断言每条写入事件：

```python
assert all(write[1]["evidence"]["db"] == YOYO_SQLITE_DB_PATH for write in writes)
```

说明：
事件落盘后应能准确追溯到固定 YOYO SQLite。

### 7.4 连接会被关闭

测试中的 `FakeConn` 会记录 `close()` 是否被调用。

断言：

```python
assert conn.closed is True
```

说明：
即使成功路径下，连接资源也必须被释放。

---

## 8. 建议的开发调试顺序

### 8.1 先跑单测

```powershell
python -m pytest --override-ini addopts="" tests/unit/test_localdb_ingest.py
```

适合验证：

- 固定 DB 路径是否还在
- 表到 URI 的映射有没有改坏
- `evidence.db` 有没有漂移

### 8.2 再跑真实 HTTP ingest 验证

```powershell
python scripts/verify_localdb_ingest.py --user-space default/default --config examples/localdb_yoyo_mapping.yaml
```

适合验证：

- 服务端路由是否可用
- mapping 是否可被解析
- 真实 SQLite 是否可读
- 两个目标文件是否真正写到了 VikingFS

### 8.3 需要清空历史时先 reset

```powershell
python scripts/reset_yoyo_jsonl.py --ignore-missing
```

### 8.4 一步完成刷新

```powershell
python scripts/refresh_yoyo_ingest.py
```

---

## 9. 常见调用误区

### 9.1 误区：传不同的 `db_path` 就会切库

当前不会。

根因：
[`openviking/db/ingest.py`](/d:/code/openviking/openviking-private/openviking/db/ingest.py) 中 `_resolve_db_path()` 已固定返回 YOYO DB。

### 9.2 误区：`source` 会影响输出文件路径

当前固定 YOYO 场景下默认不会。

只有在：

- 你显式给了 `output_uri` 模板
- 或以后恢复通用 `events.jsonl` 路径

时，`source` 才直接决定落盘位置。

### 9.3 误区：重复 ingest 会覆盖旧文件

不会。

当前是 `append_file()` 追加写入。

如果要“只保留最新一轮”，应先执行：

```powershell
python scripts/reset_yoyo_jsonl.py --ignore-missing
```

或直接：

```powershell
python scripts/refresh_yoyo_ingest.py
```

### 9.4 误区：服务端一定能识别相对 `config_path`

只有在当前代码版本下才支持仓库根目录相对路径解析。

若服务是旧进程或旧版本，建议直接传绝对路径。

---

## 10. 推荐的接口调用模板

### 10.1 Python 内部调用模板

```python
from openviking.db import IngestRequest, ingest

report = await ingest(
    IngestRequest(
        db_path="",
        user_space="default/default",
        source="yoyo_history",
        config_path=r"D:\code\openviking\openviking-private\examples\localdb_yoyo_mapping.yaml",
        dry_run=False,
        redact=True,
    )
)

assert report.failed == 0
assert "viking://yoyo/userinformation/default/userinformation.jsonl" in report.output_uris
assert "viking://yoyo/usertendencies/default/usertendencies.jsonl" in report.output_uris
```

### 10.2 HTTP 调用模板

```powershell
@'
{
  "user_space": "default/default",
  "source": "yoyo_history",
  "config_path": "D:\\code\\openviking\\openviking-private\\examples\\localdb_yoyo_mapping.yaml",
  "dry_run": false,
  "redact": true
}
'@ | python -c "import sys, json, requests; body=json.load(sys.stdin); r=requests.post('http://127.0.0.1:1933/api/v1/localdb/ingest', json=body, timeout=120); print(r.status_code); print(r.text)"
```

### 10.3 返回校验模板

最少建议校验：

```python
assert result["status"] == "ok"
assert result["result"]["failed"] == 0
assert result["result"]["db_path"] == r"D:\HONOR Share\YOYO History\yoyochat2.db"
assert set(result["result"]["output_uris"]) == {
    "viking://yoyo/userinformation/default/userinformation.jsonl",
    "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}
```

---

## 11. 相关文件

- 单测：
  [`tests/unit/test_localdb_ingest.py`](/d:/code/openviking/openviking-private/tests/unit/test_localdb_ingest.py)
- 核心实现：
  [`openviking/db/ingest.py`](/d:/code/openviking/openviking-private/openviking/db/ingest.py)
- 路由：
  [`openviking/server/routers/localdb.py`](/d:/code/openviking/openviking-private/openviking/server/routers/localdb.py)
- 类型：
  [`openviking/db/types.py`](/d:/code/openviking/openviking-private/openviking/db/types.py)
- mapping：
  [`examples/localdb_yoyo_mapping.yaml`](/d:/code/openviking/openviking-private/examples/localdb_yoyo_mapping.yaml)
- 写入验证脚本：
  [`scripts/verify_localdb_ingest.py`](/d:/code/openviking/openviking-private/scripts/verify_localdb_ingest.py)
- 清理脚本：
  [`scripts/reset_yoyo_jsonl.py`](/d:/code/openviking/openviking-private/scripts/reset_yoyo_jsonl.py)
- 一键刷新脚本：
  [`scripts/refresh_yoyo_ingest.py`](/d:/code/openviking/openviking-private/scripts/refresh_yoyo_ingest.py)
