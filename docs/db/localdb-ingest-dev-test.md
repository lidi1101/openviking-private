# 本地 SQLite 导入长期记忆开发测试指南

本文用于验证新增的 LocalDB 导入能力是否可用，覆盖从 SQLite 读取、通过服务端接口导入、写入 `viking://user/.../memories/localdb/.../events.jsonl`，到最终读取落盘文件的完整链路。

适用范围：
- `openviking/db/*`
- `openviking/server/routers/localdb.py`
- `scripts/verify_localdb_ingest.py`

---

## 1. 测试目标

验证以下事项：

- 服务端已暴露 `POST /api/v1/localdb/ingest`
- 服务端可以只读打开本地 SQLite 数据库
- mapping 配置可以驱动 SQL 抽取
- 行数据可以被归一化为事件 JSON
- 数据会落盘到 `viking://user/<user_space>/memories/localdb/<source>/events.jsonl`
- `GET /api/v1/content/read` 可以读回 `events.jsonl`

---

## 2. 关键文件

- 接口入口：`openviking/server/routers/localdb.py`
- 导入主流程：`openviking/db/ingest.py`
- mapping 解析：`openviking/db/config.py`
- SQLite 读取：`openviking/db/sqlite_reader.py`
- 事件归一化：`openviking/db/normalize.py`
- JSONL 写入：`openviking/db/writer.py`
- 验证脚本：`scripts/verify_localdb_ingest.py`
- mapping 示例：`examples/localdb_yoyo_mapping.yaml`

---

## 3. 环境要求

### 3.1 Python 依赖

至少确认当前 Python 环境可导入：

```bash
python -c "import fastapi, uvicorn, httpx; print('ok')"
```

### 3.2 原生产物

如果当前工作树没有预编译产物，服务可能无法启动。至少要能提供以下文件，或者先完成本地构建：

- `openviking/storage/vectordb/engine*.pyd`
- `openviking/bin/agfs-server.exe`
- `openviking/lib/libagfsbinding.dll`

### 3.3 配置文件

`ov.conf` 需要至少满足以下条件：

- `server.host = 127.0.0.1`
- `server.port = 1933`
- `storage.workspace` 指向本地可写目录
- `embedding` 配置存在且可初始化

最小示例：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 1933,
    "workers": 1
  },
  "storage": {
    "workspace": "D:\\openviking-test-data",
    "agfs": { "backend": "local" },
    "vectordb": { "backend": "local" }
  },
  "embedding": {
    "dense": {
      "provider": "openai",
      "model": "text-embedding-3-small",
      "api_key": "dummy-local-only",
      "api_base": "http://127.0.0.1:65535/v1",
      "dimension": 1536
    }
  }
}
```

### 3.4 测试数据

本文以如下 SQLite 文件作为联调样例：

```text
D:\HonorShare\yoyochat2.db
```

---

## 4. 标准自测流程

### 4.1 启动服务

```bash
python -m openviking_cli.server_bootstrap --config <ov.conf> --host 127.0.0.1 --port 1933
```

健康检查：

```bash
curl http://127.0.0.1:1933/health
```

预期返回：

```json
{"status":"ok"}
```

### 4.2 执行导入验证脚本

使用自动探测 mapping：

```bash
python scripts/verify_localdb_ingest.py ^
  --user-space default/default ^
  --db "D:\HonorShare\yoyochat2.db" ^
  --source yoyo_history ^
  --base-url http://127.0.0.1:1933
```

使用显式 mapping：

```bash
python scripts/verify_localdb_ingest.py ^
  --user-space default/default ^
  --db "D:\HonorShare\yoyochat2.db" ^
  --source yoyo_history ^
  --config examples/localdb_yoyo_mapping.yaml ^
  --base-url http://127.0.0.1:1933
```

只验证 SQL 与归一化，不落盘：

```bash
python scripts/verify_localdb_ingest.py ^
  --user-space default/default ^
  --db "D:\HonorShare\yoyochat2.db" ^
  --source yoyo_history ^
  --base-url http://127.0.0.1:1933 ^
  --dry-run
```

### 4.3 预期输出

脚本成功时应出现以下关键信息：

- `Ingest API response`
- `status: ok`
- `written > 0`
- `failed = 0`
- `OK: events.jsonl written`
- `Preview lines:`

一次实际联调样例中，返回结果为：

- `total_rows = 10`
- `written = 10`
- `failed = 0`

---

## 5. 落盘验证

### 5.1 Viking URI

当参数为：

- `user_space = default/default`
- `source = yoyo_history`

输出 URI 应为：

```text
viking://user/default/default/memories/localdb/yoyo_history/events.jsonl
```

### 5.2 通过 API 读回

```bash
curl "http://127.0.0.1:1933/api/v1/content/read?uri=viking://user/default/default/memories/localdb/yoyo_history/events.jsonl&offset=0&limit=20"
```

返回中 `result` 字段应包含 JSONL 文本。

### 5.3 通过本地文件验证

在 local AGFS 模式下，URI 会映射到 `storage.workspace` 下的本地目录。

若：

- `storage.workspace = D:\openviking-test-data`
- `account_id = default`
- `user_space = default/default`

则本地文件通常位于：

```text
D:\openviking-test-data\viking\default\user\default\default\memories\localdb\yoyo_history\events.jsonl
```

查看前几行：

```bash
python -c "from pathlib import Path; p=Path(r'D:\openviking-test-data\viking\default\user\default\default\memories\localdb\yoyo_history\events.jsonl'); print(p.exists()); print(''.join(p.open('r', encoding='utf-8').readlines()[:5]))"
```

---

## 6. 验收标准

满足以下条件即可认为功能可用：

- 服务能正常启动并通过 `/health`
- `POST /api/v1/localdb/ingest` 返回 `status = ok`
- `report.written > 0`
- `report.failed = 0`
- `viking://user/.../events.jsonl` 可读
- `events.jsonl` 中每行都是合法 JSON
- 每条事件至少包含 `id`、`type`、`time`、`text`、`evidence`

建议额外检查：

- `privacy.redact` 与请求参数一致
- `time.ts` 被规范化为 ISO8601
- `evidence.row_ref` 可回溯到源表主键

---

## 7. 回归测试建议

每次改动以下模块后，都应至少跑一次完整自测：

- `openviking/db/config.py`
- `openviking/db/sqlite_reader.py`
- `openviking/db/normalize.py`
- `openviking/db/ingest.py`
- `openviking/server/routers/localdb.py`

建议覆盖以下场景：

- 正常导入
- `--dry-run`
- mapping 文件缺失
- SQL 字段名错误
- 数据库文件不存在
- 数据库被占用时走 copy fallback
- 文本包含中文、URL、空值、时间戳

---

## 8. 常见问题

### 8.1 服务启动失败

优先检查：

- `ov.conf` 是否可被加载
- `embedding` 配置是否完整
- `engine*.pyd`、`agfs-server.exe`、`libagfsbinding.dll` 是否存在
- `storage.workspace` 是否可写

### 8.2 导入接口报权限错误

`/api/v1/localdb/ingest` 只允许 ROOT 调用。

如果服务未配置 `server.root_api_key`，且只绑定 `127.0.0.1`，当前默认是本地开发模式，可直接调用。

### 8.3 `events.jsonl` 为空

重点检查：

- SQL 是否真的查到了数据
- mapping 的 `columns.pk/time/title/url` 是否和 SQL alias 对齐
- 是否误传了 `--dry-run`

### 8.4 中文预览乱码

如果 PowerShell 里直接打印 `content/read` 结果出现乱码，优先用 Python 按 UTF-8 直接读取本地 `events.jsonl` 文件验证，不要只看终端编码表现。

---

## 9. 推荐提交流程

开发完成后，建议按以下顺序自检：

1. 跑一次 `/health`
2. 跑一次 `verify_localdb_ingest.py --dry-run`
3. 跑一次真实导入
4. 读取 `events.jsonl` 前 5 行
5. 记录 `total_rows/written/failed` 到提交说明或测试记录

这样可以把“接口可调用”“数据能写入”“落盘可读”三层问题拆开定位。
