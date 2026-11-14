# 转换工作台

> **实验性材料。** 当前仍未形成可靠的陌生项目转换方法。以下规则用于尝试与机械验收，不能保证图的语义正确或读者能够理解；请人工核对。当前优先边写项目边维护逻辑图、积累案例，再提炼规律和 SKILL。见 [当前状态](current-status.md)。

工作台把“写最终 JSON”拆成两步：

1. AI 写一份**局部视图草稿**：块用短 `key` 互相引用，行号用 `map` 简写；
2. 工作台分配数字 `id`、补全 `next`/`jump`/`flow`/`emit`、写文件，并跑整项目校验。

工作台是编辑器前端，读写仍然是 `codifold.json` 和 `*.blocks.json`。新工作区默认使用 flat 视图（`blocks` + `containers`）；草稿仍用嵌套写法，`apply` 会自动编译成 flat。旧嵌套工作区仍可写入。规则见 [flat-schema.md](flat-schema.md)。

## 命令

```bash
# 1. 看当前状态：覆盖率、未覆盖行、当前视图块结构、下一个可用 id
python3 -m codifold.workbench brief <工作区> --view main --snippets

# 2. 只编译，不写文件；输出最终 JSON
python3 -m codifold.workbench apply <工作区> draft.json --dry-run

# 3. 写入并整项目复检；失败自动回滚
python3 -m codifold.workbench apply <工作区> draft.json

# 4. 一次写入多个视图；视图之间可以互相 jump
python3 -m codifold.workbench apply <工作区> bundle.json

# 5. 最终检查，警告也算失败
python3 -m codifold.workbench check <工作区> --strict

# 6. 单独查看连贯性：从 main 能到达多少视图
python3 -m codifold.workbench coherence <工作区> --json

# 7. 导出供 AI 审核的 Markdown 文字稿
python3 -m codifold.workbench export-md <工作区> --out flow.md

# 8. 作为 MCP 服务器运行（stdio），供 AI 客户端调用
python3 -m codifold.workbench mcp
```

`brief` 加 `--json` 输出机器可读数据；`apply` 加 `--json` 输出写入摘要。草稿路径写 `-` 表示从 stdin 读。

## MCP 服务器

工作台也可以作为本地 MCP 服务器运行，让 ZCode、Claude Desktop 等 AI 客户端直接调用，不用再经文件中转：

```bash
python3 -m codifold.mcp_server
# 等价入口
python3 -m codifold.workbench mcp
```

客户端配置示例（`PYTHONPATH` 指向 Codifold 仓库根目录）：

```json
{
  "mcpServers": {
    "codifold": {
      "command": "python3",
      "args": ["-m", "codifold.mcp_server"],
      "env": {"PYTHONPATH": "/path/to/Codifold"}
    }
  }
}
```

服务只走 stdio，不监听端口；stdout 只写 JSON-RPC 消息，日志都走 stderr。`workspace` 必须是含 `codifold.json` 的目录；相对路径按服务器进程的当前目录解析。

### 客户端注册

不同客户端读不同位置的文件，键都是 `mcpServers`：

| 客户端 | 配置文件 |
|---|---|
| ZCode（用户级，所有工作区可用） | `~/.agents/mcp.json` |
| ZCode（仅某个工作区） | `<工作区>/.agents/mcp.json` |
| Claude Code / 其他 | 各自的 `mcpServers` 配置，如 `.mcp.json` |

ZCode 用户级条目示例：

```json
{
  "mcpServers": {
    "codifold": {
      "name": "codifold",
      "command": "/usr/bin/python3",
      "args": ["-m", "codifold.mcp_server"],
      "cwd": "/path/to/Codifold",
      "env": {"PYTHONPATH": "/path/to/Codifold"},
      "alwaysLoad": true,
      "timeoutMs": 120000
    }
  }
}
```

- `command` 用绝对路径的解释器，避免桌面端启动时 `PATH` 里没有 `python3`；`cwd` + `PYTHONPATH` 双保险，保证 `-m codifold.mcp_server` 能找到模块。
- 改完配置要重启客户端；客户端请求的协议版本不被支持时，服务器会回退到自己的最新版本（当前 `2025-06-18`），符合 MCP 协商规则。
- 工具与命令对应：

| MCP 工具 | 对应命令 | 说明 |
|---|---|---|
| `codifold_brief` | `brief` | 只读；`view`、`snippets` 可选 |
| `codifold_apply` | `apply` | 编译草稿；**默认 `dry_run=true`**，传 `dry_run=false` 才写入 |
| `codifold_check` | `check` | `strict=true` 时警告也算失败；不通过时 `ok=false` 且 `isError=true` |
| `codifold_coherence` | `coherence` | 只查连贯性；分数不是 1.0 时 `isError=true` |
| `codifold_export_md` | `export-md` | 默认返回文档文本；`out` 指定时写文件并返回摘要 |

`codifold_apply` 的 `draft` 可以直接传对象/数组，也可以传 JSON 字符串。其余参数与命令行同名：`views`/`kinds`/`with_code`/`max_code_lines`。

资源：

- `codifold://guide/conversion`
- `codifold://guide/workbench`
- `codifold://guide/flat-schema`
- `codifold://guide/blocks-schema`

边界：MCP 服务器只读写工作区 JSON，不执行、不分析被讲解的源码；`export-md --with-code` 也只读取 `code_mapping` 覆盖的行。默认 `dry_run=true` 是为了让 AI 先给出编译结果，人工确认后再落盘。

## 连贯性

连贯性衡量“从主线视图能不能进入所有视图”：

- 节点是视图，边是 `jump.view` / `flow.view` / `emit[].view`。
- 从 `kind=main` 的视图出发做不限深度的 BFS。
- `连贯性 = 可达视图数 / 视图总数`，最终必须是 **1.0000**。
- 只关心“能不能到”，不关心经过几层；深度会列出来，方便判断是直接入口还是深层细节。
- 有视图到不了时，`check` 报错，`coherence` 退出码 1，并列出未到达的视图。

`check` 和 `brief` 都会显示连贯性；`coherence` 单独输出每个视图的深度。

## 导出文字稿

`export-md` 把整个工作区投影成一份 Markdown，供 AI 或人做**文字审核**：

```bash
# 输出到 stdout
python3 -m codifold.workbench export-md <工作区>

# 写文件
python3 -m codifold.workbench export-md <工作区> --out flow.md

# 只导出部分视图或角色
python3 -m codifold.workbench export-md <工作区> --view main --view entry-http
python3 -m codifold.workbench export-md <工作区> --kind main --kind entry

# 文末附加代码证据；每块最多 20 行
python3 -m codifold.workbench export-md <工作区> --with-code --out flow.md
```

文档只使用视图的 `name`/`description`、块标题/描述、分支条件和跳转关系，不改写文字。阅读顺序固定为：

1. 主线；
2. 流程和入口（按从主线发现的顺序）；
3. 函数细节；
4. 结构/定义和工具箱；
5. 无法从主线到达的视图放在最后，并在附录标出。

块的写法：

- `[65] 标题 —— 描述`；块 ID 用于让 AI 精确引用，例如 `main:65`。
- 分支写成 `**如果：条件**`；并行分支写成 `**并行分支：条件**`。
- try 写成 `**正常执行**` / `**异常处理：条件**` / `**最后一定执行**`。
- `next:null` 或列表结束标“结束”；显式指向前面的块标“回到”；显式指向其他块标“继续”。
- 分支或 try 的最后一块会标“分支结束后继续 / 正常执行后继续 / 异常处理后继续 / 收尾后继续”，说明它离开当前分支后去哪。
- `flow` 标“主线继续”，`jump` 标“展开细节”，`emit` 标“事件通知”，目标写成 `view:id`。
- 被 `--view`/`--kind` 排除的目标视图会标“（未导出）”。

文档开头有覆盖率、连贯性和视图/块数量；附录 A 列文件覆盖、错误/警告、孤立视图、无代码映射的块、未写条件的分支和描述过短的块；附录 B 是给审核 AI 的检查清单。`--with-code` 时附录 C 按 `view:id` 列 `code_mapping` 覆盖的源码行，每块默认最多 20 行，超出截断；代码只在附录，不插入正文。

注意：

- 纯文字稿只能检查“文字是否自洽”，不能判断描述与代码是否一致；需要事实核对时加 `--with-code`。
- 导出是 JSON 的忠实投影，不会润色；文字不好应改 JSON，再重新导出。
- 默认不写时间戳，同样输入生成同样文本，便于 diff 和反复审核。
- 默认输出到 stdout；`--out` 才会写文件，并且是原子写入。
- 函数细节不会内联进主线，主线里只保留跳转引用。

## 视图草稿

```json
{
  "view": {
    "id": "fn-load",
    "name": "读取学生数据",
    "description": "load_students：文件不存在时返回空列表。",
    "kind": "function"
  },
  "file": "gradebook.py",
  "blocks": [
    {
      "key": "entry",
      "id": 1,
      "name": "函数入口",
      "description": "无参数；返回学生列表。",
      "map": "12-13"
    },
    {
      "key": "check",
      "id": 2,
      "type": "branch",
      "name": "文件是否存在",
      "description": "DATA_FILE 指向 students.json；定义见 struct。",
      "map": 14,
      "jump": "struct:2",
      "branches": [
        {
          "condition": "不存在",
          "steps": [
            {"key": "empty", "id": 3, "name": "返回空列表",
             "description": "不读取文件。", "map": 15, "next": "end"}
          ]
        },
        {
          "condition": "存在",
          "steps": [
            {"key": "read", "id": 4, "name": "读取并解析",
             "description": "按 UTF-8 解析 JSON。", "map": 16,
             "next": "end", "jump": "struct:2"}
          ]
        }
      ]
    }
  ]
}
```

更新已有视图时，**被其他视图 `jump`/`flow`/`emit` 引用的块要保留原来的 `id`**。不写 `id` 的块会分配新编号，旧编号不会被复用；外部引用因此失效时，整批写入会回滚并报错。

草稿是嵌套格式；写入 flat 工作区时，工具会转换成 `blocks` + `containers`。`--dry-run` 在 flat 工作区输出最终的 flat JSON。

## 视图角色

| `view.kind` | 用途 |
|---|---|
| `main` | 系统主线；一个项目一个 |
| `flow` | 跨模块业务链路 |
| `entry` | CLI/HTTP/事件/后台线程入口 |
| `function` | 函数细节，只能作为 `jump` 目标 |
| `struct` | 模块声明、常量、类型 |
| `toolbox` | 未接入入口的工具代码 |

省略 `kind` 时按 id 前缀推断；建议显式写。侧栏按角色分组，函数细节默认折叠。

## 契约视图

流程回答“接下来发生什么”，契约回答“东西长什么样、允许什么”。`kind: "contract"` 的视图用表格表达静态结构和约束：JSON 类型、HTTP 接口、配置键、前端组件。它复用块的 `id`、描述和来源链接，不另起一套 id。

```json
{
  "view": {"id": "contract-api", "name": "任务 API 契约",
           "description": "类型与接口的静态契约。", "kind": "contract"},
  "blocks": [
    {
      "id": 1,
      "type": "normal",
      "name": "Job",
      "description": "任务记录，所有任务接口返回的对象。",
      "contract": {
        "kind": "type",
        "fields": [
          {"name": "id", "type": "int", "required": true},
          {"name": "state", "type": "enum",
           "values": ["queued", "running", "done", "failed", "canceled"],
           "required": true}
        ]
      },
      "evidence": [{"view": "mod-storage", "id": 11}]
    },
    {
      "id": 2,
      "type": "normal",
      "name": "创建任务",
      "description": "校验后写入并发布事件。",
      "contract": {
        "kind": "endpoint",
        "method": "POST",
        "path": "/api/jobs",
        "auth": true,
        "request": "JobCreate",
        "response": "Job",
        "status": 201,
        "errors": [{"status": 400, "when": "类型、内容或尝试次数非法"}],
        "handler": {"view": "fn-api-create-job", "id": 1}
      }
    }
  ]
}
```

规则：

- 契约视图只放普通块，每块必须写 `contract`；不能写 `next` / `jump` / `flow` / `emit` / `on`。
- 契约块不写 `code_mapping`：类型用 `evidence`，接口用 `handler`，指向已有的流程/结构块，覆盖仍由原块负责。
- 第一版 `contract.kind` 只有 `type` 和 `endpoint`。`type` 的字段表支持 `name` / `type` / `required` / `values` / `description`；`endpoint` 支持 `method` / `path` / `auth` / `request` / `response` / `status` / `errors` / `handler` / `external`。
- 工作区内类型名唯一，`method + path` 唯一；`request` / `response` 必须解析到某个类型块的 `name`。
- `type` 块至少要有一条 `evidence`；非 `external` 接口必须有 `handler`，且目标视图角色是 `function` / `entry` / `flow`。
- 契约视图必须能从 main 经 `jump` / `emit` 到达，计入连贯性；它自身是叶子，不再指向别处。

`check` 会多打印一段“契约检查”，`brief` 显示类型/接口数量，`export-md` 把契约视图输出成表格而不是编号步骤，阅读顺序在入口之后、函数细节之前。草稿的块可以直接写 `contract` 和 `evidence`，`handler` 用 `{view, id}` 引用已有视图。前端把契约视图渲染成可点击的表格：点行选中块，点类型名跳到对应类型，点“来源 / 处理”跳到原块看代码；编辑走“视图设置 → 编辑视图 JSON”。

## 主线继续 `flow`

`flow` 和 `jump` 都是跨视图导航，但语义不同：

- `flow`：主线继续，目标必须是 `main` / `flow` / `entry`；双击优先走它。
- `jump`：查看实现细节，目标可以是 `fn-*`。

```json
{"key": "dispatch", "name": "按子命令分发", "description": "分发到五个入口", "map": 265,
 "branches": [
   {"condition": "serve", "steps": [
     {"key": "serve", "name": "进入 serve", "description": "serve 入口",
      "flow": "entry-serve:start"}
   ]},
   {"condition": "worker", "steps": [
     {"key": "worker", "name": "进入 worker", "description": "worker 入口",
      "flow": "entry-worker:start"}
   ]}
 ]}
```

引用写法：

| 写法 | 含义 |
|---|---|
| `"flow": "entry-serve:start"` | 同一批次里 `entry-serve` 的 `key=start` 块 |
| `"flow": {"view": "entry-serve", "id": 1}` | 已有视图 `entry-serve` 的块 1 |
| `"flow": {"view": "entry-run", "key": "start"}` | 同一批次里的入口块 |

`flow` 不能指向本视图；同视图继续用 `next`。`main` / `flow` 视图的终点必须是 `next:null` 或 `flow`，不能只剩一个函数细节的 `jump`。

## 引用规则

| 写法 | 含义 |
|---|---|
| `"next": "end"` 或 `null` | 显式终止 |
| 不写 `next` | 顺序下一块 |
| `"next": "entry"` / `"next": "@entry"` | 同一视图里 `key=entry` 的块 |
| `"jump": "@entry"` | 同一视图里 `key=entry` 的块 |
| `"jump": "detail:start"` | **同一批次**里 `detail` 视图的 `key=start` 块 |
| `"jump": "struct:2"` | 已有视图 `struct` 的块 2 |
| `"flow": "entry-serve:start"` | **同一批次**里 `entry-serve` 的入口块 |
| `"flow": {"view": "entry-serve", "id": 1}` | 已有入口视图的块 1 |
| `{"view": "detail", "id": 5}` | 明确指定已有块 5 |
| `{"key": "start"}` | 同一视图里 `key=start` 的块 |

`emit` 的每个元素用同样的写法。`key` 在视图内唯一，`end` 是保留字。

## 行号映射

视图级 `file` 是默认文件；如果工作区只声明了一个文件，可以省略。

```json
{"map": "12-13"}
{"map": 14}
{"map": [14, "20-24"]}
{"map": {"file": "other.py", "lines": [3, "8-9"]}}
```

也可以直接写最终格式的 `code_mapping`，但同一块不能同时写 `map` 和 `code_mapping`。文件必须在 `codifold.json` 的 `files` 里声明。

## 分支与 try

- `type` 省略时：有 `branches` 就是分支块，否则是普通块。
- 分支块默认 `select: "single"`；并行分支写 `"select": "multi"`。
- try 写 `"kind": "try"`，分支列表用 `role: "body"` / `"except"`，可以再加 `finally`。
- 普通块不能写 `select`/`branches`/`finally`；分支块不能写 `next`/`emit`。

## 一次写多个视图

```json
{
  "views": [
    {
      "view": {"id": "detail", "name": "细节", "description": "细节视图",
               "kind": "function"},
      "file": "app.py",
      "blocks": [
        {"key": "start", "name": "开始", "description": "开始", "map": "1-2"}
      ]
    },
    {
      "view": {"id": "entry", "name": "入口", "description": "入口视图",
               "kind": "entry"},
      "file": "app.py",
      "blocks": [
        {"key": "go", "name": "打开", "description": "打开细节",
         "map": 3, "jump": "detail:start"}
      ]
    }
  ]
}
```

工作台先编译全部视图，再一起写入，最后只跑一次整项目校验。任何结构错误、跨视图引用错误或 `--strict` 警告都会让整批文件回滚。

## 推荐流程

1. `brief <工作区> --view main --snippets`，只关注当前链路和未覆盖行。
2. 先写 `kind: "main"` 的主线草稿：运行入口 → 分发；每个分支尾用 `flow` 接入口。
3. `apply --dry-run` 看最终 JSON；确认块顺序、`next`、`flow` 和 `jump`。
4. `apply` 写入；默认允许“未覆盖”警告。
5. 再写各 `entry-*` 入口；1–3 行的取值/转发函数内联，不单独建 `fn-*`。
6. 需要展开的函数才建 `kind: "function"`，从调用块用 `jump` 进入。
7. 最后 `check --strict`：覆盖率 100%、无重复映射、main/flow/entry 无不可达块、连贯性 1.0000，并且主线/入口叙事检查通过。

## 边界

- `--dry-run` 只做结构/引用编译，不计算覆盖率，也不写文件。
- `apply` 不带 `--strict` 时允许未覆盖、重复映射、不可达块等警告；带 `--strict` 会在写入后检查覆盖率类警告并回滚。
- `check --strict` 还会跑叙事检查和连贯性：所有视图是否都能从 main 经 `jump`/`flow`/`emit` 到达、main/flow 视图是否有死胡同。
- 跨视图 `key` 只在同一批次的视图之间有效；引用已有视图的块请用数字 `id`。
- 工作台不做并发修订检查；同一时间只让一个会话写入一个工作区。
- 工作台只读写工作区 JSON，不执行、不修改被讲解的源码；`export-md --with-code` 只读取 `code_mapping` 覆盖的行作为附录。
- 契约视图不写 `code_mapping`，只用 `evidence` / `handler` 指向已有块；覆盖率仍由流程和结构块负责。
- `export-md` 默认输出到 stdout；`--out` 才会写文件，并会按需创建父目录。
- MCP 服务器同样不做并发控制；`codifold_apply` 默认只预览，写入仍是后写覆盖先写。
