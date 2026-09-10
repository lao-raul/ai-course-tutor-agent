# Course Tutor Platform

本地优先、RAG 驱动的课程助教平台。首个课程实例为 University of Leeds MSc Artificial Intelligence。

## 后端应用

- **Agent API**：现有 `apps/api`，负责课程、摄取、检索问答、引用、会话和记忆；运行时名称为 `agent-api`。
- **Practice API**：位于 `apps/practice`，负责未来的随机题目练习；v0.2 已提供独立 dummy API，并返回明确的 501 未实现响应。

Ingestion worker 和 React Web 是支持工作负载，不计为额外后端产品 App。

规格见 [Function Spec](docs/function-spec.md)、[Design Spec](docs/design-spec.md)；执行顺序见 [Task Index](docs/tasks/task-00-index.md)，需求映射见 [Traceability](docs/requirements-traceability.md)。

## 当前状态

- Agent API 已完成本地/OIDC 身份边界、tenant/role/ACL 隔离、增量不可变内容版本、严格引用校验和真正的 SSE 增量输出。
- Practice API dummy 边界已实现；记忆、教学策略、Kubernetes 和完整 CI/CD 尚为 planned。
- 详细状态和验收责任以 Design Spec 和 `docs/tasks/` 为准；README 不单独声明 Phase 完成。

Kubernetes 交付统一使用 `infra/k8s/course-tutor` 下的 Helm v3 Chart。该 Chart
将作为 Agent API、Practice API、worker 和 Web 的唯一打包、安装、升级与回滚入口；
具体实现和验收由 TASK-09 负责。

## 本地原型启动

前置：Python 3.12、uv、Docker、Node.js。

```bash
cp .env.example .env
uv sync --extra dev
docker compose -f infra/docker/docker-compose.dev.yml up -d
uv run alembic -c apps/api/alembic.ini upgrade head
uv run uvicorn course_tutor_api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Practice API 可独立启动：

```bash
uv run uvicorn course_tutor_practice.app:create_app --factory --host 0.0.0.0 --port 8001
```

另一个终端启动当前 ingestion worker：

```bash
uv run python -m course_tutor_ingestion
```

健康检查：

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

除健康检查外，Agent API 均要求 Bearer token。本地默认令牌是
`local-dev-token`；本地启动会按 `LOCAL_TENANT_ID`/`LOCAL_USER_ID` 幂等 provision 开发身份。
生产环境会拒绝 `AUTH_MODE=local`，必须配置 OIDC issuer、audience 和 JWKS URL。

课程内容工作流分为三步：`POST /v1/admin/programmes` 注册专业，
`POST /v1/admin/courses` 注册课程/run/只读 SourceRoot，最后调用
`POST /v1/admin/courses/{course_id}/ingestions` 手动触发；worker 也会按配置周期扫描。
只有 READY 版本经显式 publish 后才会成为聊天使用的 active version。

当前 Agent chat 使用 `POST /v1/courses/{course_id}/chat`。请求体只包含 `query` 和可选
`session_id`；tenant、用户和内容访问级别全部由服务端认证上下文决定。

## NAS

应用不直接连接 `smb://L-NAS`。先通过操作系统或 Kubernetes SMB CSI 将目录挂载为只读 POSIX 路径，再配置 `COURSE_SOURCE_PATH`。当前已观察到的 macOS 挂载根为 `/Volumes/home/University of Leeds`；实际课程 SourceRoot 必须通过管理 API 显式注册。

不要提交 `.env`、SMB 凭据、课程原文、kubeconfig 或真实学习者数据。

## 契约验证

```bash
uv run python scripts/validate_contract_baseline.py
uv run pytest tests/unit/test_contract_baseline.py -q
```
