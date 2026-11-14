# Codifold 块配置规范

Codifold 只读取、校验和渲染 JSON，不分析、不执行源代码；前端的编辑也只写 JSON。一个项目由一份工作区配置 `codifold.json`、若干 `.blocks.json` 视图文件和源代码组成。

> **新工作区默认使用 flat 视图**：块是平表，层级由 `containers` 表达。完整规范见 [flat-schema.md](flat-schema.md)。本文余下部分描述旧嵌套格式，仍用于读取兼容。

```text
project/
  codifold.json          工作区配置：项目元数据 + 源码绑定 + 视图发现规则
  main.blocks.json       视图
  detail.blocks.json     另一个视图
  app.py                 被映射的源代码
```

视图按 `views.suffix`（默认 `.blocks.json`）自动发现；`codifold.json` 和其它 JSON 不参与视图列表。

## 1. 工作区配置 `codifold.json`

```json
{
  "project": {
    "name": "学生成绩管理",
    "description": "终端版学生成绩管理示例：加载、菜单、增删改查、统计与保存。",
    "root": "."
  },
  "files": ["gradebook.py", "src/store.py"],
  "views": {
    "suffix": ".blocks.json",
    "entry": "main"
  }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `project.name` | 是 | 项目名称，显示在顶栏和侧栏 |
| `project.description` | 是 | 项目描述，显示在侧栏 |
| `project.root` | 否 | 源码根目录，相对清单文件；默认 `"."`，允许 `".."` 或绝对路径 |
| `files` | 是 | 允许被 `code_mapping` 引用的文件，相对 `root`；可以是空数组；不能是绝对路径或包含 `..`；必须存在且不重复 |
| `views.suffix` | 否 | 视图文件后缀，默认 `.blocks.json`；必须是 `.xxx.json` 形式 |
| `views.entry` | 否 | 入口视图的 `view.id`；省略时取文件名排序后的第一个视图 |
| `views.format` | 否 | `flat`（新默认）或 `nested`（旧格式）；省略时按 `nested` 读取 |

**硬规则：只有 `files` 里声明过的文件才能被 `code_mapping` 引用。** 文件未声明时，带 `code_mapping` 的视图无法加载。

## 2. 视图文件

```json
{
  "view": {
    "id": "main",
    "name": "主流程",
    "description": "开始 → 菜单 → 六种功能 → 返回菜单。",
    "kind": "main"
  },
  "blocks": [ ... ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `view.id` | 是 | 稳定 id，小写字母开头，`[a-z0-9_-]`，项目内唯一；`jump`/`flow`/`emit` 引用它 |
| `view.name` | 是 | 视图名称，显示在流程标题和视图列表 |
| `view.description` | 是 | 视图描述，显示在流程标题下方和视图列表 |
| `view.kind` | 否 | `main` / `flow` / `entry` / `function` / `struct` / `toolbox`；省略时按 id 前缀推断 |
| `blocks` | 是 | 非空数组；数组顺序就是默认执行顺序 |

视图角色：

| `kind` | 用途 |
|---|---|
| `main` | 系统主线；一个项目一个，从运行入口走到进程退出 |
| `flow` | 跨模块业务链路 |
| `entry` | CLI 子命令、HTTP 路由、事件、后台线程等入口链路 |
| `function` | 函数/方法实现细节，只能作为 `jump` 目标 |
| `struct` | 模块声明、常量、类型 |
| `toolbox` | 没有入口能到达的工具代码 |

侧栏按角色分组；函数细节默认折叠。省略 `kind` 时，`entry-*` 推断为 `entry`，`fn-*` 为 `function`，`mod-*`/`struct` 为 `struct`，`main` 为 `main`。

视图文件必须匹配工作区的 `views.suffix`。入口视图由工作区的 `views.entry` 指定，视图文件里不再写 `entry`。

## 3. 块的公共字段

```json
{
  "id": 1,
  "type": "normal",
  "name": "读取输入",
  "description": "读取并解析用户输入。",
  "code_mapping": {"file": "gradebook.py", "lines": [12, "15-18"]}
}
```

| 字段 | 说明 |
|---|---|
| `id` | 正整数，整个视图内全局唯一（含分支步骤和 finally） |
| `type` | `normal` 或 `branch` |
| `name` / `description` | 必填，中文名称和说明 |
| `code_mapping` | 可选；`file` 必须是 `codifold.json` 声明过的文件；`lines` 支持 `1`、`2`、`"6-9"`，单块最多 400 行 |
| `jump` | 可选，实现细节链接，见下文；不产生执行线 |
| `flow` | 可选，跨视图主线继续，见下文；不产生执行线 |
| `on` | 可选，事件入口名；只能写在视图第一个顶层块 |

### `jump` 与 `flow`

```json
"jump": {"id": 8}
"jump": {"view": "detail", "id": 2}
"flow": {"view": "entry-serve", "id": 1}
```

- `jump` 是“查看实现”的导航链接，可指向函数细节、同视图块或事件入口。
- `flow` 是“主线继续”的链接，**必须跨视图**，目标视图必须是 `main` / `flow` / `entry`，目标编号必须存在。
- 同一个块可以同时有 `flow` 和 `jump`；双击优先走 `flow`，右侧面板分别提供“继续主线”和“跳转”。
- 跨视图执行仍然只能用 `flow` / `jump` / `emit` 导航；不能用 `next` 指向另一个视图。
- `flow` 不改变代码覆盖和 `next` 的执行语义，它只描述读者应该接着看哪一段。

### `on`

```json
"on": "device.click"
```

- 标记这个块是事件处理链的入口。
- 只能写在视图的第一个顶层块，普通块或分支块都可以。
- 事件发出块的 `emit` 必须指向带 `on` 的块。

## 4. 普通块 `normal`

| 字段 | 说明 |
|---|---|
| `next` | 三态：不写 = 顺序下一块；整数 = 跳转到该编号；`null` = 显式终止 |
| `emit` | 可选，事件发出目标数组，元素为 `{"id": 8}` 或 `{"view": "handler", "id": 1}` |
| `kind` | 暂不支持；普通块的外观 kind 尚未启用 |

`emit` 规则：

- 只能写在普通块上，至少一个目标。
- 目标视图必须存在；目标编号必须存在。
- **目标块必须带 `on`**，否则报错。
- 事件不画执行线；点击角标或双击发出块会跳到目标入口。

## 5. 分支块 `branch`

```json
{
  "id": 3,
  "type": "branch",
  "select": "single",
  "name": "按选择执行",
  "description": "单选，只进入一条。",
  "branches": [
    {"condition": "输入 1", "steps": [ ... ]},
    {"steps": [ ... ]}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `select` | `single`（只进一条）或 `multi`（并行） |
| `branches` | 非空数组；每项 `{condition?, steps}`，`steps` 非空 |
| `kind` | 可选，目前只支持 `"try"` |

规则：

- 分支块不能写 `next` 或 `emit`。
- 列表尾默认汇入外层序列的下一块；尾块写 `next` 则不汇合。
- `condition` 显示在扇出线上；无条件列表直接进入。

### `kind: "try"`

```json
{
  "id": 2,
  "type": "branch",
  "kind": "try",
  "select": "single",
  "branches": [
    {"role": "body", "steps": [ ... ]},
    {"role": "except", "condition": "FileNotFoundError", "steps": [ ... ]}
  ],
  "finally": [ ... ]
}
```

- `select` 必须是 `single`。
- 恰好一条 `role: "body"`，且必须是第一条；body 不能写 `condition`。
- 其余列表必须是 `role: "except"`；`condition` 是异常类型，可省略。
- 至少要有一条 except 或一个非空 `finally`；允许 `try/finally` 没有 except。
- `finally` 是普通步骤序列，不是分支列表。
- body / except 列表尾汇入 finally 第一块；finally 出口继续外层下一块。
- 异常扇出线和异常尾汇合线显示为虚线。
- finally 里的块参与 id 唯一、代码映射、jump/emit 目标校验；因为它是嵌套序列，里面不能写 `on`。

## 6. 执行与布局规则

- 顶层块按数组顺序从上到下；每块默认连到同序列的下一块。
- 分支块扇出到各列表第一块；列表尾汇合到外层下一块。
- `next` 覆盖默认后继：整数跳转、`null` 终止；写 `next` 的尾块不参与汇合。
- `jump` / `emit` 只做导航和事件关联，不画执行线。
- 所有结构用线条表达，没有块中块容器。
- 事件的产生链和处理链分开：发出块 `emit`，处理视图首块 `on`。
- try 的 body/except 是并列路径，finally 是它们共同的后续。

## 7. 校验

命令行：

```bash
python3 -m codifold.validate examples/gradebook
python3 -m codifold.validate examples/gradebook --json
python3 -m codifold.validate examples/gradebook --strict
```

检查内容：

- JSON、字段、id 唯一、`next` / `jump` / `emit` 引用、分支与 try 结构。
- `code_mapping` 文件必须在 `codifold.json` 中声明且存在。
- 代码覆盖：Python 用 `tokenize` 排除空行和纯注释行；其它语言用非空且不以常见注释前缀开头的行。
- 重复映射：同一行被两个及以上块映射，输出区间和块编号。
- 映射到非代码行（注释、空行）也会报告。
- 不可达块：从视图第一个顶层块做执行可达性分析；终止块之后、没有执行入边的块会警告。`jump` 是导航，不算执行边；被 `jump` 指向的块视为有意导航，不报不可达。`function` / `struct` / `toolbox` 视图视为实现或声明集合，不做执行可达性警告。
- 跨视图 `jump` 目标 id：项目级检查，目标视图里没有这个 id 是错误。视图本身仍可打开，错误由校验命令/报告给出。
- 连贯性（`validate` / `workbench check` / `workbench coherence`）：从 `kind=main` 的视图出发，沿 `jump.view` / `flow.view` / `emit[].view` 做不限深度 BFS；可达视图数 / 视图总数必须是 1.0000，否则有视图是孤立的。

输出：

- **错误**：配置不合法、引用不存在、文件未声明、跨视图 `jump` 目标缺失等，退出码 1。
- **警告**：未覆盖行、重复映射、映射到非代码行、不可达块；默认退出码 0，`--strict` 时退出码 1。
- 重复映射是警告而不是错误，因为分支块和它的步骤经常有意重叠。
- JSON 报告里的每个视图带 `unreachable` 数组，列出不可达块的 id 和名称。

同一个报告也可以通过 `GET /api/coverage?path=<项目目录>` 获取。

## 8. 前端编辑与写接口

前端 `/blocks` 的“编辑”模式只对工作区目录生效；`?config=` 单文件模式保持只读。

### 修订值 `revision`

所有写接口都可以带上“我读到的那一版”的修订值，避免两个窗口互相覆盖：

- `GET /api/views` 返回的每个视图带 `revision`，索引顶层带 `manifest_revision`；值都是文件内容的 SHA-256。
- `GET /api/blocks-config` 的返回值带 `revision` 和 `manifest_revision`。
- `GET /api/project` 返回 `{manifest, revision, index}`。
- 保存已有视图时把读取到的 `revision` 一起发回；新建视图发 `"revision": null`。
- 文件已被其他编辑改动时返回 409：

  ```json
  {"error": "文件已被其他编辑修改，请重新加载后再保存",
   "code": "revision_conflict", "current_revision": "..."}
  ```

- 省略 `revision` 时保持旧的“后写覆盖先写”行为，方便外部脚本。

### 视图

- 新增块支持普通块、条件分支（单选/并行）和 try/except/finally；分支列表、条件、步骤、finally 在表单里编辑。类型创建后固定；非 try 分支可以在单选/并行间切换；分支步骤可以递归嵌套普通块、条件分支和 try，最多 5 层。
- `GET /api/events?path=<工作区目录>` 返回工作区已有的 `on` 值，编辑表单用它做下拉选项。
- 保存视图：`POST /api/views`，body `{"path": "<工作区目录>", "config": {"view": {...}, "blocks": [...]}, "revision"?: "..."}`。
  - `view.id` 决定目标文件：已有视图写回索引里的文件，新视图创建 `<view.id><views.suffix>`。
  - 保存前做结构校验；写入后跑整项目 `mapping_report` 复检。任何错误都会回滚，原文件不变。
  - 返回值：`{"payload": ..., "index": ..., "warnings": [...], "created": bool, "revision", "manifest_revision"}`。
  - 保存会按 2 空格缩进、UTF-8、末尾换行重写视图文件；未知字段会丢失。
- 删除视图：`DELETE /api/views?path=<工作区目录>&view=<view.id>&revision=<视图修订>&manifest_revision=<清单修订>`。
  - 不能删除最后一个视图；被其他视图的 `jump` / `emit` 引用时拒绝。
  - 删除入口视图时自动把 `views.entry` 改成剩余视图的第一个。
  - 修订不匹配返回 409。

### 项目设置

- 读取：`GET /api/project?path=<工作区目录>`，返回 `{manifest, revision, index}`；`manifest` 是 `codifold.json` 原始对象。
- 保存：`POST /api/project`，body：

  ```json
  {
    "path": "/abs/workspace",
    "revision": "<manifest_revision>",
    "config": {
      "project": {"name": "项目名", "description": "描述", "root": "."},
      "files": ["app.py", "src/store.py"],
      "views": {"entry": "main"}
    }
  }
  ```

  - 只允许修改 `project.name`、`project.description`、`project.root`、`files` 和 `views.entry`；`views.suffix` 暂不支持修改。
  - 未提供的字段保持原值，`codifold.json` 里的未知字段也会保留。
  - `project.root` 指向的目录必须存在；`files` 会按新 `root` 校验相对路径、存在性和重复项。
  - `views.entry` 必须是已有视图，或传 `null` 清除入口。
  - 保存后同样跑整项目复检；删除仍被 `code_mapping` 引用的文件会失败并回滚。
  - 返回值：`{manifest, index, revision, manifest_revision}`。
- “重命名工作区”只改 `project.name` / `project.description`，不移动目录。

### 工作区生命周期

- 新建工作区：`POST /api/workspaces`，body `{"directory": "<绝对路径或 ~ 开头>", "name", "description", "view_id"?, "view_name"?}`。
  - 目录必须为空或不存在；创建 `codifold.json` 和一个 `next: null` 的“开始”块。
- 打开工作区：`POST /api/workspaces/open`，body `{"path": "<工作区目录>"}`。
  - 校验工作区和全部视图，返回 `{index, manifest}`，并把目录写入最近列表。
- 最近列表：`GET /api/workspaces`，返回 `{"recent": [{"path", "name", "description", "opened_at", "exists"}]}`。
  - 状态文件是 Codifold 仓库下的 `.codifold/workspaces.json`，可用环境变量 `CODIFOLD_STATE_DIR` 改写位置。
  - 列表最多保留 20 条；已不存在的目录仍会显示，但 `exists` 为 `false`。
- 移出列表：`DELETE /api/workspaces/recent?path=<工作区目录>`，只删记录，不动目录。
- 删除工作区目录：`DELETE /api/workspaces?path=<工作区目录>&confirm=<完整绝对路径>`。
  - `confirm` 必须和解析后的目录路径完全一致。
  - 拒绝文件系统根目录、顶层目录、用户主目录、Codifold 所在目录及其上级、Codifold 仓库内的目录，以及包含 `.git` 的目录；也拒绝删除符号链接。
  - 删除是不可逆操作，前端必须二次确认。

### 通用规则

- 编辑器自动分配块 id；视图 id 和块 id 保存后不提供修改，避免引用失效。
- 编辑接口只接受本机同源请求；视图文件和清单写入前会校验路径在工作区目录内，拒绝 `..` 和符号链接逃逸。
- 并发写没有文件锁；带 `revision` 时做内容比对，不带时后写覆盖先写。
- 工作区目录重命名不在接口范围内，需要用户自己移动目录后重新打开。

## 9. AI 输出检查清单

1. 先写 `codifold.json`：项目 `name`/`description`、`files`、`views.suffix` 和 `views.entry`。
2. 每个视图一个 `.blocks.json`；`view.id` 唯一，`view.name`/`description` 必填。
3. 视图内所有块 id 全局唯一，包括分支步骤和 finally。
4. 所有被 `code_mapping` 引用的文件都写进 `codifold.json` 的 `files`。
5. 运行 `python3 -m codifold.validate <项目目录>`，错误必须清零。
6. 检查未覆盖区间和重复映射，确认重叠是有意的。
7. 终止块写 `"next": null`；循环/跳转写目标 id。
8. 事件发出只指向带 `on` 的入口块。
9. try 的 body 放第一条，异常列表写 `role: "except"`。
