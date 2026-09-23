# Course Tutor Platform

本地优先、RAG 驱动的课程助教平台。首个课程实例为 University of Leeds MSc Artificial Intelligence。

## 后端应用

- **Agent API**：现有 `apps/api`，负责课程、摄取、检索问答、引用、会话和记忆；运行时名称为 `agent-api`。
- **Practice API**：位于 `apps/practice`，负责未来的随机题目练习；v0.2 已提供独立 dummy API，并返回明确的 501 未实现响应。

Ingestion worker 和 React Web 是支持工作负载，不计为额外后端产品 App。

规格见 [Function Spec](docs/function-spec.md)、[Design Spec](docs/design-spec.md)；执行顺序见 [Task Index](docs/tasks/task-00-index.md)，需求映射见 [Traceability](docs/requirements-traceability.md)。

## 当前状态

- Agent API 已完成本地/OIDC 身份边界、tenant/role/ACL 隔离、增量不可变内容版本、严格引用校验和真正的 SSE 增量输出。
- 会话/长期记忆、教学策略、Practice dummy、Helm/Kind 部署和完整 CI 工作流均已实现；main 的 GitHub-hosted CI 已全绿。
- TASK-13/14 已完成：local-real Helm 部署通过真实 NAS 与 LM Studio 验收，Leeds 课程已入库、显式发布，并通过 API/浏览器引用与拒答验证。
- TASK-15/16 已完成：Web 支持安全 Markdown/KaTeX 与复杂矩阵布局，PDF 引用保持页级边界；Unit/Week 使用独立的结构化范围检索，避免同编号内容误召回。
- TASK-11/12 已完成：CD 发布签名、带 provenance/SBOM 且经过最终 digest 扫描的不可变镜像；受保护环境负责原子部署、运行 digest 对比、冒烟和回滚。Prometheus/OTLP、SLO、告警、仪表盘、HA/恢复演练及发布清单已纳入代码。
- 详细状态和验收责任以 Design Spec 和 `docs/tasks/` 为准；README 不单独声明 Phase 完成。

Kubernetes 交付统一使用 `infra/k8s/course-tutor` 下的 Helm v3 Chart。该 Chart
将作为 Agent API、Practice API、worker 和 Web 的唯一打包、安装、升级与回滚入口；
具体实现和验收由 TASK-09 负责。

生产 CD 的工作流已经就绪，但不会凭 README 自动启用；仍需在 GitHub Environment
中配置目标集群的窄权限 kubeconfig、环境 values、冒烟令牌和课程 ID。环境契约与操作
步骤见 [release/rollback runbook](docs/runbooks/release-and-rollback.md)，发布判断见
[release checklist](docs/release-checklist.md)，本次本地演练见
[TASK-11/12 verification](docs/verification/2026-09-15-task-11-12.md)。

## 构建容器镜像

完整 Kubernetes 部署需要 Docker Desktop（含 buildx）、Kind、kubectl、Helm、jq，
以及能够访问的镜像仓库或本地 Kind 节点。构建脚本使用根目录的
`docker-bake.hcl`，可一次构建全部 workload：

```bash
export IMAGE_TAG=local-$(git rev-parse --short HEAD)
TAG="$IMAGE_TAG" scripts/build-docker.sh
```

也可以只构建指定目标：

```bash
TAG="$IMAGE_TAG" scripts/build-docker.sh agent-api practice-api ingestion-worker web
TAG="$IMAGE_TAG" scripts/build-docker.sh web
```

镜像名称分别为：

- `course-tutor-agent:$IMAGE_TAG`
- `course-tutor-practice:$IMAGE_TAG`
- `course-tutor-worker:$IMAGE_TAG`
- `course-tutor-web:$IMAGE_TAG`
- `course-tutor-fake-llm:$IMAGE_TAG`（仅 CI/离线测试使用）

本地重新构建时应使用新的标签，不要反复覆盖 `:local`。Kind 与 Kubernetes 的
镜像缓存可能令同名标签继续运行旧代码；唯一标签也能让 Helm 可靠触发滚动升级。

## 使用 Kind 和 Helm 部署真实课程环境

以下流程适用于已由 macOS/Linux 挂载的 NAS 目录和局域网 LM Studio。应用不会
直接保存或连接 SMB 凭据。路径、令牌和私有地址只写入被 Git 忽略的 `.local/`
配置或 Kubernetes Secret。

### 1. 创建专用 Kind 集群和只读课程卷

```bash
scripts/local-real-kind-setup.sh \
  --host-path "/absolute/path/to/University of Leeds/modules"
```

脚本使用 `course-tutor-real` 集群，并创建 `course-tutor-content` PV/PVC。课程目录
只挂载到 Agent API 和 ingestion worker；Practice API 与 Web 无权读取课程原文。

### 2. 配置 Secret 和本机 values

先从安全的本地凭据管理器导出值，不要将真实值写入仓库：

```bash
export COURSE_TUTOR_AUTH_TOKEN='replace-with-local-token'
export COURSE_TUTOR_MINIO_SECRET='replace-with-random-secret'
export LM_STUDIO_API_KEY='lm-studio-or-empty-local-key'

kubectl -n course-tutor create secret generic course-tutor-local-runtime \
  --from-literal=local-auth-token="$COURSE_TUTOR_AUTH_TOKEN" \
  --from-literal=minio-access-key=course-tutor \
  --from-literal=minio-secret-key="$COURSE_TUTOR_MINIO_SECRET" \
  --from-literal=llm-api-key="$LM_STUDIO_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

mkdir -p .local
cp infra/k8s/course-tutor/values-local-real.example.yaml \
  .local/course-tutor.values.yaml
```

编辑 `.local/course-tutor.values.yaml`，填写带 `/v1` 的 LM Studio 地址、已加载的
chat/embedding model ID 和真实 embedding dimension。CI 不使用这些私有配置。

### 3. 构建并导入镜像

```bash
export IMAGE_TAG=local-$(git rev-parse --short HEAD)-$(date +%H%M%S)
TAG="$IMAGE_TAG" scripts/build-docker.sh agent-api practice-api ingestion-worker web

kind load docker-image --name course-tutor-real \
  "course-tutor-agent:$IMAGE_TAG" \
  "course-tutor-practice:$IMAGE_TAG" \
  "course-tutor-worker:$IMAGE_TAG" \
  "course-tutor-web:$IMAGE_TAG"
```

### 4. 预检并通过 Helm 安装或升级

```bash
export LLM_BASE_URL='http://LAN_HOST:1234/v1'
export LLM_CHAT_MODEL='exact-loaded-chat-model-id'
export LLM_EMBEDDING_MODEL='exact-loaded-embedding-model-id'
export LLM_EMBEDDING_DIMENSION=1024
export PREFLIGHT_IMAGE="course-tutor-agent:$IMAGE_TAG"

scripts/local-real-preflight.sh

helm lint infra/k8s/course-tutor \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml

helm upgrade --install course-tutor infra/k8s/course-tutor \
  --namespace course-tutor --create-namespace \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml \
  --set-string backend.agent.image.tag="$IMAGE_TAG" \
  --set-string backend.practice.image.tag="$IMAGE_TAG" \
  --set-string worker.image.tag="$IMAGE_TAG" \
  --set-string web.image.tag="$IMAGE_TAG" \
  --atomic --wait --wait-for-jobs --timeout 10m

scripts/local-real-preflight.sh
```

确认 release、Pod 和实际镜像：

```bash
helm status course-tutor -n course-tutor
kubectl get pods -n course-tutor
kubectl get pods -n course-tutor \
  -o 'custom-columns=NAME:.metadata.name,IMAGES:.spec.containers[*].image'
```

### 5. 注册、摄取并发布课程

复制并编辑课程映射；`source_path` 是容器内 `/data/content/...` 路径，不是 SMB URL：

```bash
cp docs/examples/leeds-course.example.yaml .local/leeds-course.yaml
kubectl -n course-tutor port-forward service/course-tutor-agent 18000:8000
```

在另一个终端执行幂等注册、摄取和显式发布：

```bash
export COURSE_TUTOR_AUTH_TOKEN='same-token-used-by-the-runtime-secret'
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --ingest --wait
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --publish
scripts/local-course-e2e.sh --config .local/leeds-course.yaml
```

当 extraction、chunk、embedding payload 或 pipeline version 改变时，必须完成新内容
版本的 ingestion 和 publish；只重建 Web UI 时不需要重新摄取课程。

### 6. 从浏览器访问

```bash
kubectl -n course-tutor port-forward service/course-tutor-web 18080:80
```

打开 [http://127.0.0.1:18080](http://127.0.0.1:18080)。Pod 滚动升级会令已有
port-forward 失效，需要重新执行命令。若浏览器仍持有旧 hashed bundle，使用
`Command+Shift+R`（macOS）或 `Ctrl+Shift+R` 强制刷新。

完整操作说明和故障排查见 [local-real deployment](docs/runbooks/local-real-deployment.md)
与 [course bootstrap](docs/runbooks/course-bootstrap.md)。CI 使用生成课程 fixture、
Fake LLM 和 `values-ci.yaml`，不会连接家庭 NAS 或局域网 LM Studio。

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

当前 Agent chat 使用 `POST /v1/courses/{course_id}/chat`。请求体包含 `query`、可选
`session_id`，以及可选的 assessment/attempt/language 策略参数；tenant、用户和内容访问
级别全部由服务端认证上下文决定。长期记忆默认关闭，可通过课程级 memory-consent API
显式开启；Web 中可查看原因、纠正、置顶、导出或删除事实。

## NAS

应用不直接连接 SMB URL。先通过操作系统或 Kubernetes SMB CSI 将目录挂载为只读 POSIX 路径，再配置 `COURSE_SOURCE_PATH`。实际课程 SourceRoot 必须通过管理 API 显式注册；机器路径只允许出现在被忽略的 `.local/` 配置中。

大规模小学、初中和高中教材使用分层存储：教材原件及备份保留在 NAS，
PostgreSQL/Qdrant 活跃数据使用持久化 SSD/块存储。不要把 SMB/NFS 直接作为
Qdrant 的 `/qdrant/storage`。容量规划、按需导入及快照配置见
[`docs/runbooks/k12-storage-capacity.md`](docs/runbooks/k12-storage-capacity.md)。

真实 NAS、LM Studio 和课程注册流程见 [local-real deployment](docs/runbooks/local-real-deployment.md) 与 [course bootstrap](docs/runbooks/course-bootstrap.md)。

不要提交 `.env`、SMB 凭据、课程原文、kubeconfig 或真实学习者数据。

## 契约验证

```bash
uv run python scripts/validate_contract_baseline.py
uv run pytest tests/unit/test_contract_baseline.py -q
```
