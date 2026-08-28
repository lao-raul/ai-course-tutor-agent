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
cp .env.example .env      # 按需修改；.env 永不提交
make install              # 安装 workspace 依赖
make up                   # 启动 Postgres / Qdrant / Redis / MinIO
make migrate              # 应用数据库 migration
make api                  # 启动 API（http://localhost:8080）
```

或者一步到位：`make dev`。`make help` 列出全部目标。

验证：

```bash
curl localhost:8080/healthz   # 存活，不触碰任何依赖
curl localhost:8080/readyz    # 逐项报告 postgres / redis / qdrant / llm
make check                    # lint + mypy strict + 测试
```

## 当前进度

**Phase 0（基础与决策）已完成。** 已就绪：uv workspace 工具链、配置校验、结构化日志与
correlation ID、OTel 桩、核心实体契约与 ORM、可逆的初始 migration、LM Studio 适配器与确定性测试替身、
health/readiness、CI（lint / mypy / 测试 / migration 往返 / 密钥扫描）。

测试套件与 CI **不依赖 NAS 或 LM Studio**。

下一步是 Phase 1（课程摄取），前置条件见下。

## 端口约定

本机可能同时跑多个 stack，因此 compose 的宿主端口全部可配。Redis 默认用 **6380**
（6379 常被占用）。冲突时改 `.env` 里的 `*_HOST_PORT` 即可。

## NAS 说明

`smb://L-NAS` 是客户端挂载地址，不是应用路径。必须先由操作系统以只读服务账号挂载，
再把 `COURSE_SOURCE_PATH` 指向挂载后的绝对 POSIX 路径（macOS 形如
`/Volumes/L-NAS/...`），服务只读取本地路径。配置层会拒绝 URL 形式与相对路径。
