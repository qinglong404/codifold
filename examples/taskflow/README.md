# Taskflow

一个小型、无第三方依赖的任务编排服务。它用 SQLite 保存任务，worker 线程领取任务后按插件注册的步骤执行，HTTP API 负责创建和查询任务，调度器负责回收过期租约。

这个目录是 Codifold 的**转换练习题**：源码和运行说明保持只读，转换产物是同一目录下的 `codifold.json` 和 `*.blocks.json`。视图使用 flat 格式（`blocks` + `containers`），见 [flat-schema.md](../../docs/flat-schema.md)。

## 阅读顺序

- 从 `main` 开始：`run.py` → `cli.main` 解析/配置 → 按 `COMMANDS` 分发到五个子命令。
- `entry-serve` 是运行时主线：启动 worker、调度器和 HTTP；对应线程/请求链可以从侧栏“事件入口”单独打开。
- 函数细节在侧栏“函数细节”里默认折叠；在块上双击或点右侧“跳转”进入，用顶栏“返回”回到主线。

## 运行

```bash
cd examples/taskflow
python3 run.py --help
```

启动完整服务（HTTP + 2 个 worker + 调度器）：

```bash
python3 run.py serve --db /tmp/taskflow-demo.db
```

另开终端创建一条报表任务，然后查看状态：

```bash
python3 run.py enqueue report --payload '{"path":"sample.csv"}' --db /tmp/taskflow-demo.db
python3 run.py status --db /tmp/taskflow-demo.db
```

也可以只跑一次 worker：

```bash
python3 run.py run-once --db /tmp/taskflow-demo.db
```

默认监听 `127.0.0.1:8765`。配置文件可参考 `taskflow.example.json`；环境变量用 `TASKFLOW_` 前缀覆盖，例如 `TASKFLOW_WORKERS=4`。

## HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查，返回任务计数和已注册步骤；不需要 token |
| POST | `/api/jobs` | 创建任务，body：`kind`、`payload`、可选 `max_attempts` |
| GET | `/api/jobs?state=&limit=` | 按状态列出任务 |
| GET | `/api/jobs/{id}` | 查看单条任务 |
| DELETE | `/api/jobs/{id}` | 取消排队中或失败的任务 |
| POST | `/api/maintenance` | 创建一条清理任务 |

配置了 `api_token` 后，除 `/health` 外的请求都要带 `X-API-Token` 或 `Authorization: Bearer <token>`。

示例：

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"kind":"report","payload":{"path":"sample.csv"}}'
```

## 结构

```text
run.py                     脚本入口
taskflow/__main__.py       python -m taskflow 入口
taskflow/cli.py            argparse 子命令、运行时组装、信号处理
taskflow/config.py         默认值 → JSON 文件 → TASKFLOW_* 环境变量
taskflow/storage.py        SQLite 表、原子领取、租约、清理
taskflow/pipeline.py       任务类型 → 步骤序列，重试与失败结果
taskflow/worker.py         worker 线程、租约续期、调度器
taskflow/api.py            HTTP 路由、鉴权、JSON 请求/响应
taskflow/registry.py       装饰器注册表与插件扫描
taskflow/events.py         同步事件总线
taskflow/plugins/          csv.import / report.summarize / notify.webhook / maintenance.prune
```

任务类型到步骤的映射写在 `pipeline.py` 的 `PIPELINES` 里。插件模块被 `registry.load_plugins()` 动态导入，步骤和事件订阅者在导入时通过装饰器注册。

## 已知边界

- 这是单机演示：SQLite、进程内事件总线和线程池，没有分布式协调。
- webhook 步骤只接受 `http(s)` 地址；留空时跳过。
- 任务失败后不会自动重试；`max_attempts` 限制的是租约过期后的重新领取次数。
- 没有 HTTP 分页；`limit` 最大 200。
