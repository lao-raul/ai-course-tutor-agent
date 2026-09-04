# AI Course Tutor Agent

一个以 Leeds MSc AI 课程为首个实例、可扩展至小学到大学专业课的本地优先 AI 助教平台。

## 技术选择

- **后端：Python 3.12 + FastAPI**：RAG、文档解析、嵌入模型与评估工具链最成熟；FastAPI 易于拆为独立服务。见 [ADR-001](docs/adr/001-python-fastapi-backend.md)。
- **前端：React + TypeScript + Vite**：生态完整、组件化成熟，适合对话、引用阅读器与教师管理界面。
- **基础设施：PostgreSQL、Qdrant、Redis、MinIO（生产）**：职责清晰，均可横向扩展或托管替换。
- **推理：LM Studio 的 OpenAI-compatible API**：默认接入 `http://192.168.50.146:1234/v1`，不把任何模型能力绑定到云端。见 [ADR-003](docs/adr/003-embedding-model-and-dimension.md)。
- **部署形态：模块化单体 + 明确的拆分触发条件**，见 [ADR-002](docs/adr/002-modular-monolith-extraction-policy.md)。

行为与架构见 [Function Spec](docs/function-spec.md)；实施任务见 [Design Spec](docs/design-spec.md)。

## 快速开始

前置：`uv`、Docker、Python 3.12。

```bash
# 1. 安装 Python 依赖
uv sync --extra dev

# 2. 启动基础设施
docker compose -f infra/docker/docker-compose.yml up -d postgres qdrant redis minio

# 3. 启动 API（自动执行 alembic migration）
uv run uvicorn course_tutor_api:create_app --factory --host 0.0.0.0 --port 8000

# 4. 启动 ingestion worker（后台）
uv run python -m course_tutor_ingestion
```

或使用完整生产栈（包括 Web UI）：

```bash
cd infra/docker
cp ../../../.env.deploy .env
docker compose up --build
```

验证：

```bash
curl http://localhost:8000/health
```

## 当前进度

**Phase 0（基础与决策）已完成。** 已就绪：uv workspace 工具链、配置校验、结构化日志与
correlation ID、OTel 桩、核心实体契约与 ORM、可逆的初始 migration、LM Studio 适配器与确定性测试替身、
health/readiness、CI（lint / mypy / 测试 / migration 往返 / 密钥扫描）。

**Phase 1（课程摄取）已完成。** 扫描器、PDF/PPTX/DOCX/MD 解析器、OCR 降级、MinIO 存储、
`content_version` 发布/回滚、admin API 已就绪。验证：14 个 Leeds 模块文件 → 8580 chunks，约 3 秒；
二次扫描 → 0 个新 chunks（校验和幂等性）。

**Phase 2（检索与 RAG 对话）已完成。** `POST /v1/courses/{id}/chat` SSE 流式响应（token/citation/abstained/done）、
`HybridRetrievalService`（dense + Python 关键词 boost + 显式 unit 路径 boost）、`EmbeddingIndexer`（LM Studio → Qdrant）、
React chat UI（课程选择器、流式渲染、引用面板）、合成检索 benchmark 已就绪。
Qdrant sparse index（TEXT_INDEX）因 server 1.12.5 不支持而跳过，已用 Python 层关键词 boost 替代。

**关键修复记录：**
- **Chunk 聚合（v1.1.0）**：target_size=1000 chars，overlap=200 chars；7564 tiny fragments → 699 semantic-rich chunks（约 500–600 chars each）， VARCHAR(128) anchor_value 截断至 120 chars
- **Unit 路径 boost**：查询含 "unit N" / "week N" 时，对匹配路径的 chunk 额外 +0.35 分，解决 embedding 模型对 overview 内容的偏向问题
- **Citation map 全量构建**：从全部 20 个 retrieval candidates 构建 citation_map（而非仅 reranked top-5），支持 LLM 引用 [Source N]（N>5）时正确解析
- **验证**：`"unit3的主要内容"` → 返回 4 个 unit3 引用的实质性内容（Jacobian、Hessian、自动微分）

测试套件与 CI **不依赖 NAS 或 LM Studio**。

下一步是 Phase 3（记忆与教学体验）。

## 端口约定

| 服务 | 默认端口 | 说明 |
|---|---|---|
| API | 8000 | FastAPI |
| Web UI | 3000 → 80 | Vite dev (3000) / nginx prod (80) |
| PostgreSQL | 5432 | |
| Qdrant | 6333 (REST) / 6334 (gRPC) | |
| Redis | 6380 | 6379 常被占用 |
| MinIO | 9000 (API) / 9001 (Console) | |

所有宿主端口可通过 `.env` 中的 `*_HOST_PORT` 变量覆盖。

## NAS 说明

`smb://L-NAS` 是客户端挂载地址，不是应用路径。必须先由操作系统以只读服务账号挂载，
再把 `COURSE_SOURCE_PATH` 指向挂载后的绝对 POSIX 路径（macOS 形如
`/Volumes/L-NAS/...`），服务只读取本地路径。配置层会拒绝 URL 形式与相对路径。

## 部署架构

```
┌─────────────────────────────────────────────┐
│  nginx (:80)  ← Web 浏览器                  │
│  ├── /           → React SPA (静态文件)     │
│  ├── /v1/*      → API (:8000)              │
│  └── /admin/*   → API admin (:8000)        │
├─────────────────────────────────────────────┤
│  FastAPI (:8000)                            │
│  ├── /v1/courses/{id}/chat  (SSE流式回答)   │
│  ├── /v1/courses                      │
│  ├── /admin/ingest                    │
│  └── /health                          │
├─────────────────────────────────────────────┤
│  Ingestion Worker (后台)                    │
│  ├── 扫描任务 (scan) → 写 PostgreSQL chunks │
│  └── 嵌入任务 (embed) → 写入 Qdrant         │
│       两阶段通过 outbox 事件解耦            │
├─────────────────────────────────────────────┤
│  Postgres  Redis  Qdrant  MinIO            │
└─────────────────────────────────────────────┘
```

### 环境配置

```bash
# 复制环境变量模板
cp .env.example .env

# 必填项：
#   DATABASE_URL         — PostgreSQL 连接串
#   QDRANT_URL           — Qdrant 地址（默认 http://localhost:6333）
#   REDIS_URL            — Redis 连接串
#   LM_STUDIO_URL        — LM Studio API（默认 http://192.168.50.146:1234/v1）
#   COURSE_SOURCE_PATH   — 课程文件根目录（本地 POSIX 路径，必须先挂载 NAS）
```

### 启动依赖服务（本地开发）

```bash
docker compose -f infra/docker/docker-compose.yml up -d postgres qdrant redis minio
```

### 启动 API 和 Ingestion Worker（本地开发）

```bash
# 终端 1：启动 API（自动执行 alembic migration）
uv run uvicorn course_tutor_api:create_app --factory --host 0.0.0.0 --port 8000

# 终端 2：启动 ingestion worker（同时处理 scan + embed 任务）
uv run python -m course_tutor_ingestion
```

### 完整生产栈（Docker）

```bash
cd infra/docker
cp ../../../.env.deploy .env   # 修改密码和 LM Studio URL
docker compose up --build
```

### 触发内容摄取

课程文件就绪后，通过 API 触发扫描（也可使用 Web UI 的 Admin 面板）：

```bash
# 注册课程内容版本并触发首次扫描
curl -X POST http://localhost:8000/admin/ingest \
  -H "Content-Type: application/json" \
  -d '{"course_id": "<UUID>", "source_root": "/Volumes/L-NAS/.../OCOM5105M"}'

# 或通过 Web UI → Admin → Ingestion 页面
```

Worker 会自动处理 outbox 事件：
1. `ingestion.scan` → 扫描文件、计算 checksum、写入 `source_documents` + `chunks`
2. `ingestion.embed` → 批量 embedding → 写入 Qdrant

**重新摄取（如修改了 chunk_size）：** 需先清理 PostgreSQL 和 Qdrant 数据，再重新扫描：

```bash
# 清理旧数据（示例：course OCOM5105M）
psql $DATABASE_URL -c "DELETE FROM chunks WHERE source_id IN (SELECT id FROM source_documents WHERE version_id = '<version_uuid>');"
psql $DATABASE_URL -c "DELETE FROM source_documents WHERE version_id = '<version_uuid>';"
# Qdrant 清理（见 Qdrant REST API 或使用 qdrant-cli）

# 重置 chunk embedding 版本
psql $DATABASE_URL -c "UPDATE chunks SET embedding_model_version = 'pending';"

# 重新扫描（同上 curl 命令）
```

### 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 聊天接口（需先摄取课程内容）
curl -X POST http://localhost:8000/v1/courses/<course_id>/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "unit3的主要内容", "access_label": "enrolled"}' -N

# Web UI
open http://localhost:3000
```

### Ingestion Worker 独立部署

Worker 可独立部署，不依赖 API 服务：

```bash
# 只运行 worker（连接远程 PostgreSQL/Qdrant）
LM_STUDIO_URL=http://192.168.50.146:1234/v1 \
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  QDRANT_URL=http://host:6333 \
  uv run python -m course_tutor_ingestion
```
