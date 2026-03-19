# `openviking.db`（LocalDB）能力说明

本文档描述 `openviking/db` 目录提供的能力：

- 从本地 SQLite 数据库按配置抽取数据（ingest）
- 将抽取结果规范化为统一的事件（Event）并写入 `events.jsonl`
- 从 `events.jsonl` 回读并按条件查询/分页/取单条（query）

> 适用对象：需要在 OpenViking 中导入/读取 LocalDB 记忆的开发者。

---

## 1. 模块定位与数据流

`openviking.db` 是一套“本地 SQLite → 事件 JSONL → 回读查询”的轻量封装。

### 1.1 写入链路（ingest）

1. 读取 mapping 配置（YAML/JSON）
2. 只读打开 SQLite（必要时复制到临时目录再打开）
3. 执行配置中的 SQL，逐行产出事件字典
4. 追加写入到 VikingFS：
   
   `viking://user/{user_space}/memories/localdb/{source}/events.jsonl`

### 1.2 读取链路（query）

1. 从 VikingFS 读取 `events.jsonl`
2. 逐行解析 JSON（容错：坏行会记录到 `errors`）
3. 转换为 `Event` 数据结构
4. 按条件过滤 + 分页返回

---

## 2. 对外公共 API（`openviking/db/__init__.py`）

对外暴露：

- 写入：`ingest()`
- 读取：`list_sources()`、`query_events()`、`get_event()`
- 类型：`IngestRequest`、`IngestReport`、`QueryRequest`、`QueryResult`、`Event` 等

建议调用方统一从：

```python
from openviking.db import ingest, query_events, get_event, list_sources
from openviking.db import IngestRequest, QueryRequest, GetEventRequest
```

---

## 3. 写入能力：`ingest`（SQLite → events.jsonl）

### 3.1 请求与返回

- 请求：`IngestRequest`
  - `db_path`: SQLite 文件路径
  - `user_space`: 用户空间（通常形如 `<account>/<user>` 或 `<account>/<user>/<agent>`）
  - `source`: 数据源名称（会成为 localdb 下的目录名）
  - `config_path`: mapping 配置文件路径（yaml/yml/json）
  - `since`: 可选，用于增量抽取（会注入 SQL 参数 `:since` 与 `:since_ts`）
  - `dry_run`: 可选，仅跑抽取与规范化，不写入
  - `redact`: 可选，是否对 URL 做脱敏（去 query/fragment）

- 返回：`IngestReport`
  - `output_uri`: 默认输出位置
  - `output_uris`: 实际写入过的 URI 列表（支持每个 extract 自定义 output）
  - `total_rows / written / failed`
  - `opened_via_copy`: 是否因只读打开失败而走了“复制后打开”
  - `items`: 每个 extract 的统计
  - `errors`: 抽取失败信息
  - `samples`: 最多 5 条事件样例（便于调试）

### 3.2 mapping 配置格式（`config.py`）

`load_mapping_config()` 支持 `.yaml/.yml/.json`，格式要求：

- 顶层必须是对象（dict）
- 必须包含 `extract` 数组，且非空
- 每个 `extract` 项必填：
  - `id`: 抽取项 ID（会写入 evidence.query_id）
  - `type`: 事件类型（会写入 event.type）
  - `sql`: SQL 文本
- 可选字段：
  - `columns`: 字段映射（见下文）
  - `table`: 预留字段（当前实现不强依赖）
  - `output_uri`: 覆盖输出位置（支持模板变量）

#### 3.2.1 `columns` 字段映射约定

`normalize.build_event()` 通过 `columns` 从 SQL 返回列中取值，常用 key：

- `pk`: 行主键/唯一标识（用于生成稳定事件 id）
- `time`: 时间字段（支持 unix 秒/毫秒、ISO、SQLite datetime 字符串）
- `url`: URL 字段（可脱敏、可提取 host）
- `title`: 标题字段

> 说明：SQL 中建议使用 alias 与 `columns` 对齐，例如 `SELECT id AS pk, created_at AS time ...`。

#### 3.2.2 `output_uri` 模板变量

当 extract 配置了 `output_uri`，会执行：

- `{user_space}`
- `{source}`
- `{db_path}`

替换后作为实际写入位置。

### 3.3 SQLite 只读打开与 fallback（`sqlite_reader.py`）

- 优先使用 SQLite URI `mode=ro` 只读打开
- 若失败（例如文件被占用/URI 不兼容等），会复制 DB 到临时目录再打开
- `iter_rows()` 以 `batch_size` 分批拉取，避免一次性加载过多

### 3.4 事件规范化（`normalize.py`）

`build_event()` 输出事件字典，核心字段：

- `id`: sha256（由 source/type/query_id/row_ref 组合）
- `type`: 事件类型
- `time`: `{ts, precision}`
- `text`: 用于关键词检索的拼接文本
- `attrs`: 目前主要包含 `url/title`
- `entities`: 目前会从 URL 提取 host，形成 `{kind:"url", host:...}`
- `evidence`: 溯源信息（db/query_id/row_ref/columns_used）
- `privacy`: `{redact: bool}`

### 3.5 写入方式（`writer.py`）

- 以 JSONL 追加写入：每个事件一行 JSON
- 底层使用 `get_viking_fs().append_file()`（异步）

### 3.6 默认输出位置（`reader.py`）

默认输出：

- 根：`viking://user/{user_space}/memories/localdb`
- 文件：`{root}/{source}/events.jsonl`

---

## 4. 读取能力：sources 枚举 / 查询 / 单条获取

### 4.1 `list_sources(user_space, ctx)`（`query.py`）

能力：

- 列出 `viking://user/{user_space}/memories/localdb/` 下的 source 目录
- 仅返回“目录下存在 `events.jsonl` 文件”的 source
- 若根目录不存在，返回空列表

### 4.2 `query_events(request, ctx)`（`query.py`）

能力：

- 读取 `events.jsonl` 全量内容
- 逐行解析 JSON（坏行不致命，记录到 `QueryResult.errors`）
- 转换为 `Event`
- 按条件过滤：
  - `ids`
  - `event_types`
  - `since` / `until`（ISO8601）
  - `keyword`（对 `event.text` 做包含匹配，大小写不敏感）
- 支持分页：`offset` + `limit`
- 支持 `include_evidence=False`（返回时清空 evidence）

返回：`QueryResult`（包含 `total`、`has_more`、`items`、`errors`）

### 4.3 `get_event(request, ctx)`（`query.py`）

能力：

- 扫描 `events.jsonl`，按 `event_id` 精确匹配
- 找到即返回 `Event`，否则返回 `None`

---

## 5. 数据结构（`types.py`）

### 5.1 `Event`

- `id: str`
- `type: str`
- `time: dict`
- `text: str`
- `attrs: dict`
- `entities: list[dict]`
- `evidence: dict`
- `privacy: dict`

### 5.2 `QueryRequest / QueryResult / GetEventRequest`

- `QueryRequest`：查询条件 + 分页 + `include_evidence`
- `QueryResult`：匹配总数、分页信息、items、errors
- `GetEventRequest`：按 id 获取单条

---

## 6. 调用示例

### 6.1 导入（ingest）

```python
from openviking.db import IngestRequest, ingest

report = await ingest(
    IngestRequest(
        db_path=r"D:\\path\\to\\demo.db",
        user_space="default/default",
        source="browser_history",
        config_path=r"examples\\localdb_mapping.yaml",
        since=None,
        dry_run=False,
        redact=True,
    )
)
print(report.written, report.failed, report.output_uri)
```

### 6.2 查询（query_events）

```python
from openviking.db import QueryRequest, query_events

result = await query_events(
    QueryRequest(
        user_space="default/default",
        source="browser_history",
        keyword="github",
        offset=0,
        limit=20,
        include_evidence=False,
    ),
    ctx=ctx,
)
for e in result.items:
    print(e.id, e.type, e.text)
```

### 6.3 单条获取（get_event）

```python
from openviking.db import GetEventRequest, get_event

event = await get_event(
    GetEventRequest(
        user_space="default/default",
        source="browser_history",
        event_id="<event_id>",
    ),
    ctx=ctx,
)
print(event)
```

---

## 7. 约束与注意事项

- `query_events()` 当前实现会读取整个 `events.jsonl` 到内存；文件很大时可能需要后续做流式读取/索引优化。
- `ingest()` 在本地 CLI 导入场景下会使用 `Role.ROOT` 构造 `RequestContext`（用户/账号从 `user_space` 解析）。
- `since` 参数是否生效取决于 mapping SQL 是否使用了 `:since` 或 `:since_ts`。

---

## 8. 相关文档

仓库内已有更偏“设计/测试”的文档可参考：

- `docs/db/localdb-read-api-design.md`
- `docs/db/localdb-ingest-dev-test.md`
- `docs/db/localdb-yoyo-realdb-test-demo.md`
