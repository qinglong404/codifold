# Flat 视图规范（新默认）

新工作区默认使用 flat 视图：**块是一张平表，层级由容器表达**。不再有“顶层块内部嵌整棵树”的写法。

旧工作区里的嵌套视图仍然可以读取；它属于兼容格式，见 [blocks-schema.md](blocks-schema.md)。

## 文件结构

```json
{
  "view": {
    "id": "main",
    "name": "系统主线",
    "description": "入口 → 分发 → 退出",
    "kind": "main"
  },
  "containers": [
    {"id": "root", "kind": "root", "blocks": [1, 2, 5]},
    {"id": "c2-0", "kind": "branch", "parent": 2, "condition": "serve", "blocks": [3]},
    {"id": "c2-1", "kind": "branch", "parent": 2, "condition": "worker", "blocks": [4]},
    {"id": "c5-0", "kind": "branch", "parent": 5, "role": "body", "blocks": [7]},
    {"id": "c5-1", "kind": "branch", "parent": 5, "role": "except", "condition": "发生异常", "blocks": [8]},
    {"id": "f5", "kind": "finally", "parent": 5, "blocks": [6]}
  ],
  "blocks": [
    {"id": 1, "type": "normal", "name": "开始", "description": "进入程序"},
    {"id": 2, "type": "branch", "name": "按命令分发", "description": "选择入口",
     "select": "single", "branches": ["c2-0", "c2-1"]},
    {"id": 3, "type": "normal", "name": "serve", "description": "启动服务"},
    {"id": 4, "type": "normal", "name": "worker", "description": "启动 worker"},
    {"id": 5, "type": "branch", "kind": "try", "name": "尝试", "description": "异常结构",
     "select": "single", "branches": ["c5-0", "c5-1"], "finally": "f5"},
    {"id": 6, "type": "normal", "name": "收尾", "description": "清理"},
    {"id": 7, "type": "normal", "name": "处理", "description": "执行受保护操作"},
    {"id": 8, "type": "normal", "name": "记录失败", "description": "处理异常"}
  ]
}
```

## 视图字段

`view` 对象支持可选的 `semantics`，用来声明这个视图的执行语义：

| 取值 | 含义 | 默认 |
|---|---|---|
| `sequential` | 一条执行链；块后没有标注时默认执行下一块 | `main` / `flow` / `entry` 的默认 |
| `router` | 按条件选择一条分支，一次请求只走一条 | 需要显式声明 |
| `catalog` | 并列条目（函数、声明、工具），没有默认顺序 | `function` / `struct` / `toolbox` / `contract` 的默认 |

`semantics` 只影响阅读和导出（`export-md` 会按它写「读取方式」），不改变执行、覆盖率和连贯性的计算。

## 容器

| 字段 | 说明 |
|---|---|
| `id` | 字符串，项目内视图唯一；根容器固定为 `root` |
| `kind` | `root` / `branch` / `finally` |
| `parent` | branch/finally 的父分支块 id；root 不写 |
| `condition` | 分支条件/异常类型；root、finally 不写 |
| `role` | try 的 `body` / `except`；非 try 不写 |
| `blocks` | 有序块 id 数组，非空 |

规则：

- 恰好一个 `root` 容器。
- 每个块必须且只能属于一个容器。
- 非 root 容器的 `parent` 必须存在，且是 `type="branch"` 的块。
- 分支块的 `branches` 必须引用 `kind="branch"` 容器；`finally` 必须引用 `kind="finally"` 容器，且父块一致。
- root 深度为 1，嵌套上限沿用 5 层。
- 容器引用不能成环。

## 块

公共字段与旧规范一致：`id`、`type`、`name`、`description`、`code_mapping`、`jump`、`flow`、`on`、`next`、`emit`。

契约块额外字段（只有 `kind: "contract"` 的视图可以写，且不能写 `code_mapping` 和上面这些流程字段）：

```json
{
  "id": 1,
  "type": "normal",
  "name": "Job",
  "contract": {"kind": "type", "fields": [{"name": "id", "type": "int"}]},
  "evidence": [{"view": "mod-storage", "id": 11}]
}
```

字段含义见 [workbench.md](workbench.md#契约视图)。

分支块额外字段：

```json
{
  "id": 2,
  "type": "branch",
  "select": "single",
  "branches": ["c2-0", "c2-1"],
  "finally": "f5"
}
```

- `branches` 是容器 id 数组，不是步骤对象。
- `finally` 是容器 id；只有 try 可以写。
- 普通块不能写 `branches` / `finally`。
- 分支块不能写 `next` / `emit`。

## 执行顺序

- 同一容器内默认按 `blocks` 数组顺序执行。
- `next` 仍可指向同视图任意块；`null` 显式终止。
- 分支列表尾默认汇入外层下一块；尾块写 `next` 则不汇合。
- `jump` / `flow` / `emit` 仍然是导航/事件，不画执行线。

## 单块操作

flat 视图的操作单位是块或容器：

| 操作 | 作用 |
|---|---|
| `add_block` | 往指定容器插入普通块；可选 `after_id` |
| `add_branch_block` | 插入一个分支块，并创建默认分支容器 |
| `delete_block` | 删除块；分支块可连带删除子块（`cascade`） |
| `add_branch` | 给分支块追加一条分支列表和默认步骤 |
| `add_finally` | 给 try 块追加 finally 容器和默认步骤 |
| `delete_container` | 删除分支/finally 容器及其子块 |
| `update_container` | 修改分支条件或 role |

每次操作只改一个块/容器，保存时仍走整视图校验和整项目复检。删除块时，其他块的 `next` 会自动接到被删块的后继；仍被 `jump` / `flow` / `emit` 引用的块会被拒绝。

## 阅读与编辑

- 存储：flat `blocks` + `containers`。
- 阅读：后端把 flat 还原成嵌套投影，现有布局/连线逻辑不变；API 的 `config` 仍是嵌套投影，`flat` 字段是原始 flat 数据。
- 编辑：侧栏“块结构”显示所有块和容器；任意深度块都能直接选中、编辑、增删。
- 不再有“顶层块”弹窗；块编辑弹窗只编辑当前块，子块在块结构里操作。
- 新建工作区默认 `views.format: "flat"`。
- 旧嵌套视图仍可读；编辑时块操作只对 flat 视图开放。

## 工作台

workbench 的草稿仍然是嵌套写法（方便阅读），`apply` 写入 flat 工作区时自动编译成 `blocks + containers`；`--dry-run` 会打印最终的 flat JSON。

## 校验

- `validate`：结构、覆盖率、连贯性。
- `workbench check --strict`：覆盖率、叙事、连贯性。
- 连贯性仍按视图计算：从 `main` 沿 `jump` / `flow` / `emit` 到达所有视图，必须 1.0000。
