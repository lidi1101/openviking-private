# LocalDB 记忆读取封装设计

本文将 `openviking/db` 的读取能力方案收敛为可直接开发的接口清单与文件改动方案，目标是在不改变现有导入链路与落盘格式的前提下，为其他模块提供稳定的 Python 读取接口。

## 1. 设计目标

在 `openviking/db` 下补一层面向其他模块的读取能力封装，让调用方不直接依赖以下底层细节：

- `viking://user/.../memories/localdb/<source>/events.jsonl` URI 规则
- `VikingFS.read_file()` 调用方式
- `events.jsonl` 的逐行 JSON 解析
- 基于事件字段的过滤与分页逻辑

调用方只通过 `openviking.db` 暴露的稳定接口获取标准化事件数据。

## 2. 当前现状

当前 `openviking/db` 已具备单向导入能力：

- [openviking/db/ingest.py](d:\code\openviking\openviking-private\openviking\db\ingest.py)
  - 负责读取 SQLite、调用规范化逻辑、写入记忆文件
- [openviking/db/normalize.py](d:\code\openviking\openviking-private\openviking\db\normalize.py)
  - 负责将原始数据行转换为统一事件结构
- [openviking/db/writer.py](d:\code\openviking\openviking-private\openviking\db\writer.py)
  - 负责将事件 append 到 `events.jsonl`

当前缺失的是：

- `db` 侧统一的读取入口
- 面向其他模块的结构化查询接口
- 隐藏底层 URI 和 JSONL 文件格式的封装层

## 3. 设计范围

本次开发范围仅包含 `openviking/db` 下的 Python SDK 级读取封装。

本期包含：

- source 枚举
- 批量事件查询
- 单条事件读取
- 基础过滤与分页
- JSONL 容错解析

本期不包含：

- HTTP router
- 向量检索或语义检索
- 聚合统计
- sidecar 索引
- 修改现有导入格式

## 4. 对外接口清单

建议将其他模块的统一入口收敛到新文件 `openviking/db/query.py`。

### 4.1 `list_sources`

用途：
列举某个 `user_space` 下当前可读取的 localdb source。

接口：

```python
async def list_sources(user_space: str, ctx: RequestContext) -> list[str]:
    ...
```

输入：

- `user_space`: 目标用户空间，格式与导入时一致，例如 `default/default`
- `ctx`: 当前请求上下文

输出：

- 返回 source 名称列表，例如 `["yoyo_history", "browser_history"]`

行为要求：

- 只扫描 `viking://user/<user_space>/memories/localdb/`
- 不抛出“目录不存在”异常，目录不存在时返回空列表
- 仅返回包含 `events.jsonl` 的 source 目录名

### 4.2 `query_events`

用途：
按条件批量查询标准化事件。

接口：

```python
async def query_events(request: QueryRequest, ctx: RequestContext) -> QueryResult:
    ...
```

输入模型：

```python
@dataclass
class QueryRequest:
    user_space: str
    source: str
    event_types: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    since: str | None = None
    until: str | None = None
    keyword: str | None = None
    offset: int = 0
    limit: int = 100
    include_evidence: bool = True
```

输出模型：

```python
@dataclass
class QueryResult:
    user_space: str
    source: str
    total: int
    offset: int
    limit: int
    has_more: bool
    items: list[Event]
    errors: list[str] = field(default_factory=list)
```

行为要求：

- 从 `events.jsonl` 顺序读取全部行
- 对每行做 JSON 解析和事件结构校验
- 支持以下过滤：
  - `ids`
  - `event_types`
  - `since`
  - `until`
  - `keyword`
- 支持 `offset + limit` 分页
- 当 `include_evidence=False` 时，从返回结果中移除 `evidence`
- 当文件不存在时返回空结果，不抛致命异常
- 当单行损坏时跳过该行，并在 `errors` 中记录

### 4.3 `get_event`

用途：
按事件 ID 精确获取单条事件。

接口：

```python
async def get_event(request: GetEventRequest, ctx: RequestContext) -> Event | None:
    ...
```

输入模型：

```python
@dataclass
class GetEventRequest:
    user_space: str
    source: str
    event_id: str
    include_evidence: bool = True
```

行为要求：

- 通过扫描 `events.jsonl` 查找匹配 `event_id` 的事件
- 找到后立即返回
- 找不到返回 `None`
- 文件不存在时返回 `None`

## 5. 内部辅助接口清单

建议在新文件 `openviking/db/reader.py` 中实现底层读取与解析辅助函数，不直接暴露给其他模块。

### 5.1 URI 解析

```python
def build_events_uri(user_space: str, source: str) -> str:
    ...
```

职责：

- 统一生成 `events.jsonl` URI
- 作为导入和读取侧共享的 URI 规则函数

建议：

- 将 [openviking/db/ingest.py](d:\code\openviking\openviking-private\openviking\db\ingest.py) 中现有 `_default_output_uri()` 逻辑迁移或复用，避免双份 URI 规则

### 5.2 文件读取

```python
async def read_events_file(user_space: str, source: str, ctx: RequestContext) -> str | None:
    ...
```

职责：

- 读取完整 `events.jsonl` 文件内容
- 文件不存在时返回 `None`

### 5.3 JSONL 解析

```python
def iter_event_dicts(content: str) -> Iterator[tuple[dict[str, Any] | None, str | None]]:
    ...
```

职责：

- 逐行解析 JSONL
- 每一行返回 `(event_dict, error)`
- 成功时 `error` 为空
- 失败时 `event_dict` 为空

### 5.4 事件转换

```python
def parse_event(data: dict[str, Any], include_evidence: bool = True) -> Event:
    ...
```

职责：

- 将 JSON 对象转换为标准 `Event`
- 对缺失字段做最小兼容处理

### 5.5 过滤判断

```python
def match_event(event: Event, request: QueryRequest) -> bool:
    ...
```

职责：

- 聚合所有过滤条件判断
- 保持 `query_events()` 主流程简洁

## 6. 文件改动方案

### 6.1 修改 `openviking/db/types.py`

新增以下 dataclass：

- `QueryRequest`
- `GetEventRequest`
- `QueryResult`

建议保留现有 `Event` 类型不变。

改动点：

- 不修改现有导入请求与报告模型
- 只追加读取侧类型

### 6.2 新增 `openviking/db/reader.py`

新增底层读取模块，承接以下职责：

- 构造 `events.jsonl` URI
- 调用 `get_viking_fs().read_file()`
- JSONL 逐行解析
- 事件字典转 `Event`
- 基础过滤辅助

该文件不直接承担对外业务接口，只作为 `query.py` 的底层能力依赖。

### 6.3 新增 `openviking/db/query.py`

新增高层查询模块，对外暴露：

- `list_sources`
- `query_events`
- `get_event`

职责边界：

- 负责读取流程编排
- 负责结果组装
- 不直接实现底层 JSONL 解析细节

### 6.4 修改 `openviking/db/ingest.py`

建议做一个小范围重构：

- 将 `_default_output_uri()` 的 URI 生成逻辑复用到 `reader.py` 或共用工具函数

目标：

- 导入与读取对同一 URI 规则只保留一份实现

不建议在本次改动中调整导入主流程。

### 6.5 修改 `openviking/db/__init__.py`

将以下公共接口导出：

```python
from .query import get_event, list_sources, query_events
from .types import GetEventRequest, QueryRequest, QueryResult
```

目标：

- 让调用方可以直接通过 `openviking.db` 使用读取能力

## 7. 事件兼容策略

当前 `normalize.py` 输出事件结构为字典，字段包括：

- `id`
- `type`
- `time`
- `text`
- `attrs`
- `entities`
- `evidence`
- `privacy`

建议读取侧兼容策略如下：

- 以该结构为标准输入
- 读取时优先映射到现有 `Event` dataclass
- 对缺失的可选字段填默认值
- 对非法结构记录错误并跳过

如果实现时发现 `Event` dataclass 与落盘字典存在明显差异，可接受首版 `QueryResult.items` 先返回 `dict` 列表，但优先目标仍应是复用 `Event`

## 8. 查询语义定义

### 8.1 `ids`

- 空列表表示不过滤
- 非空时仅保留 `event.id in ids` 的记录

### 8.2 `event_types`

- 空列表表示不过滤
- 非空时仅保留 `event.type in event_types` 的记录

### 8.3 `since`

- 以 `event.time["ts"]` 为比较基准
- 包含边界，即 `>= since`
- 无法解析为时间时，该条记录默认不命中过滤条件

### 8.4 `until`

- 以 `event.time["ts"]` 为比较基准
- 包含边界，即 `<= until`
- 无法解析为时间时，该条记录默认不命中过滤条件

### 8.5 `keyword`

- 对 `event.text` 做简单包含匹配
- 首版默认区分大小写可接受
- 若实现成本低，可直接做不区分大小写匹配

## 9. 错误处理要求

读取接口整体采用“容错优先”策略。

要求如下：

- `events.jsonl` 不存在：
  - `list_sources` 返回空
  - `query_events` 返回空结果
  - `get_event` 返回 `None`
- 单行 JSON 解析失败：
  - 跳过该行
  - 在 `QueryResult.errors` 中记录
- 单条记录字段不完整：
  - 尝试默认值兼容
  - 无法兼容时跳过并记录错误
- 非法分页参数：
  - 在接口层显式校验
  - `offset < 0` 或 `limit <= 0` 时抛 `ValueError`

## 10. 开发顺序建议

建议按以下顺序实现，降低联调成本：

1. 在 `types.py` 中补齐读取侧请求/响应模型
2. 在 `reader.py` 中实现 URI 构造、文件读取、JSONL 解析
3. 在 `reader.py` 中实现 `Event` 转换与匹配判断
4. 在 `query.py` 中实现三类公开接口
5. 在 `ingest.py` 中复用统一 URI 构造逻辑
6. 在 `__init__.py` 中导出公共 API

## 11. 最小验收标准

开发完成后，至少满足以下验收项：

- 其他模块可以不关心 URI 和 JSONL，直接调用 `openviking.db.query_events()`
- 可以按 `source` 读取事件
- 可以按 `id` 获取单条事件
- 可以按 `type`、`since/until`、`keyword` 过滤
- 文件不存在时行为稳定，不抛出无关异常
- 坏行不会导致整次读取失败
- 导入与读取共用同一套 `events.jsonl` URI 规则

## 12. 预期调用方式

```python
from openviking.db import QueryRequest, query_events

result = await query_events(
    QueryRequest(
        user_space="default/default",
        source="yoyo_history",
        event_types=["chat"],
        since="2026-03-01T00:00:00+00:00",
        limit=20,
    ),
    ctx=ctx,
)

for event in result.items:
    print(event.id, event.type, event.text)
```

## 13. 后续扩展点

本方案落地后，后续可以平滑扩展：

- 在 `query.py` 上层增加 router 接口
- 支持跨 source 查询
- 增加 sidecar 索引以优化大文件扫描
- 将 localdb 记忆读取统一接入更高层检索模块

当前不建议在本期一并实现，避免把“读取封装”扩大成“检索系统重构”。
