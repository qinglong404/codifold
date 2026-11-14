# 静态契约视图（草案 v0.1）

## 1. 问题

当前 block 的底层模型是“一步叙事”：`name + description + code_mapping`，加上 `next` / `branches` / `try`。它回答“接下来发生什么”，适合流程、分支和异常。

类型、字段、HTTP 接口、事件、配置、组件 props 这些是**静态结构**：它们回答“东西长什么样、允许什么”。这是一张表或一棵树，不是时序。塞进流程块只能写成一段描述，读起来像清单，也无法复用和校验。

目标：在不改“只读 JSON、不执行源码”边界的前提下，让静态结构和约束也能被阅读、引用、导出和检查。

非目标：

- 不解析源码，不验证字段名与代码完全一致。
- 不导入 OpenAPI / TypeScript / JSON Schema。
- 第一版不做完整的表格表单编辑器。

## 2. 方案总览

新增视图角色 `contract`，并在块上增加可选 `contract` 载荷：

```json
{
  "view": {
    "id": "contract-api",
    "name": "任务 API 契约",
    "description": "HTTP 接口和 JSON 类型的静态契约。",
    "kind": "contract"
  },
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
          {"name": "status", "type": "enum",
           "values": ["queued", "running", "done", "failed", "cancelled"],
           "required": true}
        ]
      },
      "evidence": [{"view": "mod-storage", "id": 11}]
    }
  ]
}
```

为什么是 **block 级载荷**，不是视图级的大表：

- 每一行契约仍然是一个块，天然拥有稳定 `id`、选中态、描述和导出引用。
- 契约行需要指向已有解释；块上的 `evidence` 可以复用现有 `jump` 目标的定位方式。
- 覆盖率、侧栏、搜索、导出附录都按块工作，不需要再发明一套行 id。

为什么契约块**不写 `code_mapping`**：

- 同一段代码如果既被流程块映射、又被契约块映射，会触发“重复映射”警告；现有工作区通常已经 100% 覆盖。
- 契约是“换一个角度索引已有解释”，不是第二份覆盖声明。用 `evidence` / `handler` 指向已有块，覆盖仍由原块负责。
- 这样不会改变 `mapping_report` 的语义，也不会让 `check --strict` 因为新增契约视图而失败。

## 3. 视图与块约束

视图：

- `kind: "contract"`；省略时可由 `contract-` 前缀推断，但建议显式写。
- 侧栏分组“契约”，排序在入口之后、函数细节之前。
- 只允许普通块；不允许分支块和 `try`。
- 契约块不允许 `next` / `jump` / `flow` / `emit` / `on`；它们不是流程节点。
- 契约视图必须能从 main 经 `jump` / `emit` 到达，参与连贯性计算；它本身是叶子，不再指向别处。
- `views.entry` 不建议指向契约视图；校验给警告。

块：

- `type: "normal"`，`name` / `description` 照常必填。
- `contract` 必填，且只在 `kind == "contract"` 的视图里允许。
- `evidence` 可选；`type` 块至少一条。
- 不允许 `code_mapping`。

## 4. 载荷

### 4.1 `kind: "type"`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `fields` | array | 是 | 至少一个字段 |
| `fields[].name` | string | 是 | 类型内唯一 |
| `fields[].type` | string | 是 | 原始类型或其他类型名 |
| `fields[].required` | bool | 否 | 默认 `false` |
| `fields[].values` | string[] | 条件 | `type == "enum"` 时必填且非空 |
| `fields[].description` | string | 否 | 字段说明 |

类型名就是块的 `name`。工作区内类型名必须唯一，`request` / `response` 用它引用。

### 4.2 `kind: "endpoint"`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `method` | string | 是 | `GET / POST / PUT / PATCH / DELETE / HEAD / OPTIONS`，大写 |
| `path` | string | 是 | 以 `/` 开头，不含空白 |
| `auth` | bool | 否 | 默认 `false` |
| `request` | string | 否 | 引用一个 `type` 块的名字 |
| `response` | string | 否 | 引用一个 `type` 块的名字 |
| `status` | int | 否 | 成功状态码，默认 200 |
| `errors` | array | 否 | `{status: 4xx/5xx, when: 非空说明}`，状态不重复 |
| `handler` | ref | 条件 | 非 `external` 时必填；`{view, id}` |
| `external` | bool | 否 | 默认 `false`；外部接口没有本项目的 handler |

`method + path` 在工作区内必须唯一。

### 4.3 后续角色

同一套 `contract.kind` 可以继续扩展：

- `event`：事件名、payload 类型、发布者/订阅者；
- `config`：配置键、类型、必填、默认值；
- `component`：组件 props / state / emits；
- `route`：前端路径、页面、加载的数据、可用动作；
- `table`：表名、列、索引、约束。

第一版只实现 `type` 和 `endpoint`；其余角色等这套结构稳定后再加，避免一次引入太多校验规则。

## 5. 来源：`evidence` 与 `handler`

```json
"evidence": [
  {"view": "mod-storage", "id": 11},
  {"view": "mod-api", "id": 19}
]
```

- 目标必须是已有视图里的已有块；目标视图不能是 `contract`。
- `type` 块至少一条 `evidence`；`endpoint` 的 `handler` 就是主来源，`evidence` 可选。
- 目标块没有 `code_mapping` 时给警告（契约指向的代码没有覆盖）。
- 契约行不拥有代码；前端点击来源时跳到目标视图并选中目标块。

`handler` 使用与 `jump` 相同的 `{view, id}` 结构，校验目标视图存在、块存在，且角色是 `function` / `entry` / `flow`。

## 6. 校验

### 视图级（`block_config.validate`）

- `contract` 只允许出现在 `kind` 推断为 `contract` 的视图。
- 契约视图的每个块都必须是普通块，且有 `contract`。
- 契约块不能有 `next` / `jump` / `flow` / `emit` / `on` / `code_mapping`。
- `contract.kind` 只允许 `type` / `endpoint`（第一版）。
- 按角色检查必填字段、未知字段、字段名重复、枚举值、状态码范围。
- `evidence` 必须是 `{view, id}` 数组；形状错误在这里报。

### 工作区级（新增 `codifold/contract.py`）

- 类型名全局唯一。
- `method + path` 全局唯一。
- `request` / `response` 必须解析到某个 `type` 块的 `name`。
- `handler` 存在，且目标块角色合法。
- 非 `external` 接口必须有 `handler`。
- 每条 `evidence` 目标存在、不是契约视图。
- 警告：`type` 块没有 `evidence`；来源块没有 `code_mapping`；入口视图是 `contract`。

### 检查入口

新增 `codifold/checks.py`，把 `mapping_report` / `narrative` / `contract` 三份报告合成一份：

```json
{
  "ok": false,
  "errors": [],
  "warnings": [],
  "mapping": {},
  "narrative": {},
  "contract": {}
}
```

`workbench check`、MCP `codifold_check`、`validate.py` 共用它，避免三处各拼一遍。

## 7. 覆盖率与连贯性

- 覆盖率不变：契约块没有 `code_mapping`，不参与覆盖；来源块继续拥有覆盖。
- `mapping_report` 的“不可达块”检查把 `contract` 和 `struct` / `toolbox` / `function` 一样跳过：契约行是并排的定义，不是执行链。
- 连贯性把契约视图计入总数；契约视图必须通过别处的 `jump` / `emit` 到达，否则报错。
- 叙事检查不检查契约视图的死胡同（它不是 flow）。
- 导出附录 A 的“无代码映射的块”排除契约视图；改为列出“契约块缺少来源”。

## 8. `export-md`

契约视图不再输出编号步骤，改为表格。阅读顺序：主线 → 流程/入口 → 契约 → 函数细节 → 结构/定义 → 工具箱。

类型：

```markdown
### 类型

#### Job —— 任务记录

来源：mod-storage:11

| 字段 | 类型/取值 | 必填 | 说明 |
|---|---|---|---|
| id | int | 是 | 任务编号 |
| status | enum: queued / running / done / failed / cancelled | 是 |  |
```

接口：

```markdown
### 接口

| 名称 | 方法 | 路径 | 鉴权 | 请求 | 响应 | 错误 | 处理 |
|---|---|---|---|---|---|---|---|
| 创建任务 | POST | /jobs | 是 | JobCreate | Job | 400、409 | fn-api-create-job:1 |
```

- `--kind contract` 可以单独导出契约。
- 被 `--view` / `--kind` 排除的来源标“（未导出）”。
- `--with-code` 附录 C 不变；契约表只列来源引用，不重复贴代码。
- 附录 A 增加契约检查的错误/警告。

## 9. 前端

- 侧栏新增“契约”分组；`contract` 视图不再进流程画布。
- 契约视图渲染成表格：
  - “类型”区：每个类型一张字段表，标题用块名 + 描述；
  - “接口”区：一张总表，列方法、路径、鉴权、请求、响应、错误、处理函数。
- 点击任意行选中对应块；右侧显示描述和“来源 / 处理函数”链接。
- 点击来源：切换到目标视图并选中目标块，右侧代码栏显示目标块代码。
- 编辑模式第一版仍用“编辑视图 JSON”；块级契约 JSON 表单放到下一阶段。
- 表格沿用玻璃主题；窄屏横向滚动。

## 10. 工作台与 MCP

- 草稿块允许 `contract` 和 `evidence`；编译时原样透传，最后由 `block_config.validate` 校验。
- `handler` / `evidence` 第一版只支持已有视图的数字 `id`；同批次 `key` 引用后续再加。
- `brief` 的视图配置会带上契约字段，AI 可以直接看到。
- `check` 的 JSON 增加 `contract` 段和合并后的 `errors` / `warnings`。
- `export-md` 输出表格。
- 不新增 MCP 工具；`codifold_apply` / `codifold_check` / `codifold_export_md` 覆盖全部流程。

## 11. Flat 兼容

- `block_config._Walker` 保留并校验 `contract` / `evidence`。
- `flat.from_nested` 已经按块复制未知字段，会自动保留；`flat.validate_flat` 会通过嵌套校验回到同一套规则。
- 契约视图在 flat 里只有 `root` 容器；不允许 branch / finally 容器。
- 现有块操作（加块/删块）不生成契约字段；契约视图的编辑先用视图 JSON。

## 12. 实施阶段

1. **Schema + 校验**：`VIEW_KINDS`、`contract` 载荷、`evidence`、`contract.py`、`checks.py`、测试。
2. **导出 + 工作台**：`export-md` 表格、草稿透传、`check` 集成、taskflow 试点契约视图。
3. **前端**：侧栏分组、表格渲染、行选中、来源跳转；`npm run build` + 浏览器验收。
4. **文档**：`docs/contract-schema.md`、README、workbench.md、MCP 文档。

每阶段单独提交，方便回滚和审核。

## 13. 验收

- 单元测试覆盖：非法载荷、重复类型/接口、坏引用、缺失 handler/evidence、非契约视图写 contract、契约块写 flow 字段。
- taskflow 增加一个 `contract-api`，覆盖现有 HTTP 接口和任务类型；`check --strict` 0 错误 0 警告，连贯性 1.0000。
- `export-md` 的契约表格只读文字即可理解；来源引用可定位。
- 前端契约页能选中行、跳来源、显示处理函数；流程页不受影响。
- MCP 的 `codifold_apply` / `codifold_check` / `codifold_export_md` 对契约视图工作正常。

## 14. 待确认

1. 第一版只做 `type` + `endpoint`，其余角色后置。推荐：是。
2. 契约块用 `evidence` / `handler`，不写 `code_mapping`，避免重复覆盖。推荐：是。
3. 契约视图必须能从 main 到达，参与连贯性。推荐：是。
4. 阅读顺序把契约放在函数细节之前。推荐：是。
5. 前端第一版只读表格，编辑走“编辑视图 JSON”。推荐：是。
