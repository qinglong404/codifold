# Codifold 真实项目转换说明

> 适用对象：第一次接触 Codifold 的新会话或新协作者。只读这一份就能开工。
> 目标：把源码转换成“从入口一路追踪到终点”的中文流程，并满足代码行全覆盖。

---

## 0. 开工前必须知道的四件事

1. **只读源码。** 不运行、不 import、不调用被讲解的项目；只用读文件、`grep`、编辑器查看。Codifold 本身也只读 JSON。
2. **组织方式是“入口链路”，不是“代码目录”。** 不要按“头文件 → 类 → 函数定义”的顺序画图；从一个真实入口开始，沿着执行路径走到结束。
3. **覆盖率是硬指标。** 写进 `codifold.json` 的 `files` 里，每一行可执行代码都必须归属到某个块；目标是每个文件 `ratio = 1.0`。
4. **产出是 JSON，验收靠命令。** 写完必须跑 `python3 -m codifold.validate --strict`，不靠肉眼判断。新工作区默认 flat 视图；见 [flat-schema.md](flat-schema.md)。

---

## 1. 核心模型：入口链路，用到再展开

### 1.1 一条链路是什么

一条链路 = **一个入口可达的完整执行图**，不是一条直线。

- 从入口开始：`main`、脚本入口、路由处理函数、按钮/事件回调、消息消费者、定时任务、库的公开 API。
- 沿着调用、判断、循环、异常一路走到返回/退出。
- 分支是这条链路上的分叉，不是另起一条链；循环是回到链路某一点的边。
- 一条链路可以调用另一个函数；被调函数的内部实现**按需展开**成细节视图。

### 1.2 视图角色与三种跨视图链接

先给视图定角色，侧栏和叙事检查都依赖它：

| `view.kind` | 回答的问题 | 规则 |
|---|---|---|
| `main` | 程序整体怎么跑 | 一个项目一个；从运行入口走到进程退出 |
| `flow` | 跨模块业务链路怎么走 | 可作为 `flow` 目标 |
| `entry` | 某个事件/命令/线程入口怎么跑 | 从 `main` 或另一条 `flow` 接出；首块可写 `on` |
| `function` | 这个函数具体怎么做 | 只能作为 `jump` 目标，不能当主线 |
| `struct` | 模块声明、常量、类型 | 不参与执行链 |
| `contract` | 静态结构和约束长什么样 | 不参与执行链；块写 `contract` + `evidence`，见 [workbench.md](workbench.md#契约视图) |
| `toolbox` | 没入口能到达的代码 | 单独说明 |

**一个项目先有一条系统主线。** `main` 从运行入口开始，遇到命令表、路由表、线程启动等分发点就分支；每个分支末尾用 `flow` 接到对应 `entry`。多个入口不是平铺在侧栏里让读者自己找，而是从主线分出去。

跨视图只有三种链接：

| 字段 | 语义 | 用在什么地方 |
|---|---|---|
| `flow` | **主线继续** | `main` → `entry-*`，`entry-serve` → HTTP/worker/scheduler 入口；目标必须是 `main` / `flow` / `entry` |
| `jump` | **查看实现** | 调用块 → `fn-*` 细节；不画线，不影响执行顺序 |
| `emit` | 事件发出 | 普通块 → 带 `on` 的事件入口；是副作用，不是主线继续 |

- `flow` 和 `jump` 都是导航，不画执行线；执行顺序仍然由 `next` 在视图内表达。
- 跨视图不能用 `next`。
- 同一个块可以同时有 `flow` 和 `jump`；双击优先走 `flow`，右侧“查看实现”再进细节。
- **主线不能停在“只有 jump 的出口”**。`main` / `flow` 的终点要么是真实的 `next: null`，要么是 `flow` 继续。
- **连贯性必须为 1.0000**：从 `main` 出发，沿 `flow` / `jump` / `emit` 的 `view` 边，必须能到达项目里的每一个视图。深度不限；到不了就是孤立视图，需要补入口、分支或单独的块接上。

**动态分发表必须分支。** 命令表（`COMMANDS`）、路由表（`ROUTES`）、步骤注册表（`PIPELINES`/`STEPS`）、插件扫描（`pkgutil`）、事件订阅表，都是“读表 → 调处理函数”。不要停在“调用处理函数”这一块；要按注册项建分支，每个分支再用 `flow`/`jump` 接到对应入口或细节。否则主线到分发点就断了，后面只能靠读者翻侧栏。

### 1.3 入口从哪里找

| 入口类型 | 常见线索 |
|---|---|
| 进程入口 | `if __name__ == "__main__"`、`main()`、`argparse` / `click` / `typer` 命令 |
| Web/API 入口 | `@app.route`、`@router.get`、`@RestController`、`Handler`、`lambda_handler` |
| 事件入口 | `on_click`、`addEventListener`、`on_message`、signal/slot、消息队列 consumer |
| 生命周期入口 | 启动/关闭钩子、`init`、`setup`、`startup`、`shutdown` |
| 后台入口 | 线程/协程任务、定时器、cron、worker |
| 库入口 | 包导出的公开函数/类方法（`__all__`、`index.ts` 的 export） |

入口先列清单，再决定它在主线里的位置：CLI 子命令、HTTP 路由、事件、后台线程分别建 `entry-*` 视图；`main` 负责从命令行/启动入口分发到它们。`views.entry` 只决定打开项目时默认显示哪个视图。

### 1.4 为什么不是“头文件 → 类 → 函数定义”

因为读者想知道的是“程序怎么跑”，而不是“代码怎么摆放”。

- 头文件、import、类声明、函数签名本身不是执行步骤。
- 它们只在两种情况下需要块：
  1. 它们在运行时真的执行（模块级初始化、注册、装饰器副作用、常量计算）；
  2. 覆盖规则要求这些行有归属（Python 的 `import`、`def`、docstring 都算代码行）。
- 即使需要块，也放在“模块/类型/工具”这类结构视图里，或挂到细节视图的入口块，不打断主链路。
- 例：模块 docstring 与 `import` 放 `struct`；每个函数的签名/docstring 放对应 `fn-*` 的“函数入口”块；`DATA_FILE` 这种模块常量单独放 `struct` 的定义块，`load_students` / `save_students` 的每次使用都用 `jump` 指回定义。`main` 的第一块仍是 `if __name__ == "__main__"` 这个运行入口。

### 1.5 什么时候展开成细节视图

| 情况 | 做法 |
|---|---|
| 函数有真实逻辑、被链路调用 | 一个 `fn-*` 细节视图 |
| 同一个函数被多处调用 | 一个细节视图，多处 `jump` 指向它 |
| 函数只有 1–3 行、只是取值/转发 | 内联到调用步，不单独建视图 |
| 事件处理函数 | 独立 `entry-*` 视图，首块写 `on` |
| 模块 docstring、`import`、类型定义 | `struct` / `mod-*` 声明视图 |
| 模块级常量 | 单独一块放 `struct` 定义区；每个使用处 `jump` 指回，不要塞进条件/分支块 |
| 函数签名与 docstring | 映射到该函数细节视图的“函数入口”块 |
| 动态分发表 | 按注册项建分支，分支尾接 `flow` / `jump` |
| 没有任何入口能到达的代码 | `toolbox` / `unused` 视图，仍然要覆盖，并在汇报里注明“未接入链路” |

**“用到再展开”描述的是组织方式，不是覆盖范围。** 每个有逻辑的函数最终都要有归属：要么内联，要么细节视图，要么工具视图。

**视图数量也是质量指标。** 如果一个项目的 `fn-*` 视图数量远多于链路块数量，通常说明把 1–3 行的取值/转发函数也拆开了；先把它们内联，再决定哪些函数值得单独成图。

---

## 2. 产出物与工作区

```text
project/
  codifold.json          项目元数据 + 源码绑定 + 视图入口
  main.blocks.json       入口链路视图
  fn-add.blocks.json     某函数的细节视图
  fn-save.blocks.json
  src/...                被讲解的源码（只读）
```

### 2.0 新建工作区（第一次转换必做）

`brief` / `apply` / `check` 都要求目录里**至少有一个 `*.blocks.json` 视图文件**；只放 `codifold.json` 会被判“目录里没有 .blocks.json 视图文件”。所以新工作区先凑齐三样：

1. `codifold.json`：`project.name` / `project.description` / `root`、`files`（只写要覆盖的源码）、`views.suffix` / `views.entry`；
2. 一个起始视图文件，例如 `main.blocks.json`：一个普通块 + `code_mapping` + `next: null`；
3. 被讲解的源码（只读，不运行）。

```bash
mkdir -p /path/to/work && cd /path/to/work
# 写 codifold.json 和 main.blocks.json 后，确认可以跑通：
python3 -m codifold.workbench check <工作区目录> --strict
```

也可以在前端“工作区 → 新建”里创建：它会生成 `codifold.json` 和一个单块视图；默认 `files: []`，进编辑模式后在“项目设置”里逐行添加源码文件，之后代码映射下拉框才会出现文件。

### 2.1 `codifold.json`

```json
{
  "project": {
    "name": "学生成绩管理",
    "description": "从命令行入口追踪菜单、增删改查、统计与保存。",
    "root": "."
  },
  "files": ["gradebook.py"],
  "views": {
    "suffix": ".blocks.json",
    "entry": "main"
  }
}
```

- `project.root`：源码根目录，相对 `codifold.json`；默认 `"."`，允许 `".."` 或绝对路径。
- `files`：需要覆盖的源码文件，相对 `root`；不能是绝对路径、不能含 `..`、必须存在、不能重复。
- 只有 `files` 里声明过的文件才能被 `code_mapping` 引用。
- `views.entry`：默认打开的视图 id；省略时取文件名排序后的第一个视图。

### 2.2 视图文件

> 新工作区默认是 flat 视图（`blocks` + `containers`），见 [flat-schema.md](flat-schema.md)。下面的嵌套写法用于旧视图兼容和 workbench 草稿；`apply` 写入 flat 工作区时会自动编译。

```json
{
  "view": {
    "id": "main",
    "name": "主流程",
    "description": "脚本启动 → 菜单循环 → 六种功能 → 保存退出。",
    "kind": "main"
  },
  "blocks": [
    {
      "id": 1,
      "type": "normal",
      "name": "读取学生数据",
      "description": "启动时从磁盘加载；详见 fn-load。",
      "jump": {"view": "fn-load", "id": 1},
      "code_mapping": {"file": "gradebook.py", "lines": [83]}
    }
  ]
}
```

- `view.id`：`^[a-z][a-z0-9_-]{0,63}$`，项目内唯一；`jump`/`flow`/`emit` 用它引用。
- `view.kind`：`main` / `flow` / `entry` / `function` / `struct` / `toolbox`；建议显式写。省略时按 id 前缀推断。
- 文件名建议与 `view.id` 一致，但不强制；视图按 `views.suffix` 自动发现。
- `view.name` / `view.description` 必填。

### 2.3 命名约定

| 视图 | `kind` | 用途 |
|---|---|---|
| `main` | `main` | 系统主入口链路 |
| `entry-<name>` | `entry` | 其他入口（路由、事件、命令、线程） |
| `fn-<name>` | `function` | 函数/方法细节 |
| `mod-<name>` | `struct` | 模块初始化、类型、常量 |
| `flow-<topic>` | `flow` | 跨模块的业务链路（如“结算流程”） |
| `toolbox-<name>` | `toolbox` | 未接入入口的工具代码 |

块命名用“动词 + 对象”：`读取学生数据`、`校验成绩范围`、`写回 students.json`。不要用“执行第 87 行”“调用函数”这类名字。

### 2.4 用转换工作台写视图

大项目不要手写整份最终 JSON。工作台让 AI 只写局部草稿：块用短 `key` 互相引用，行号用 `map` 简写；工具负责分配数字 `id`、解析 `next`/`jump`/`emit`、写文件和整项目复检。

```bash
# 当前视图的结构、未覆盖行、下一个可用 id
python3 -m codifold.workbench brief <工作区> --view main --snippets

# 只编译不写，检查最终 JSON
python3 -m codifold.workbench apply <工作区> draft.json --dry-run

# 写入；失败自动回滚
python3 -m codifold.workbench apply <工作区> draft.json

# 一次写多个视图，允许视图之间 jump
python3 -m codifold.workbench apply <工作区> bundle.json

# 最终门禁
python3 -m codifold.workbench check <工作区> --strict
```

草稿字段、引用规则和完整示例见 [workbench.md](workbench.md)。更新已有视图时，被其他视图 `jump`/`flow`/`emit` 引用的块必须保留原来的 `id`；**分批写入时，指回已有视图的引用要写数字 `id`**（`{"view": "mod-api", "id": 19}`），`view:key` 只在同一批次的视图之间有效。

也可以让 AI 客户端走 MCP 而不是命令行：`codifold_brief`（读简报）、`codifold_apply`（默认 `dry_run=true`，只返回编译结果）、`codifold_check`。配置和参数见 [workbench.md](workbench.md#mcp-服务器)。

---

## 3. JSON 速查

### 3.1 公共字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 正整数；整个视图内唯一，含分支步骤和 finally |
| `type` | 是 | `normal` 或 `branch` |
| `name` | 是 | 中文短名，动词 + 对象 |
| `description` | 是 | 一到两句，说明意图/结果，不翻译代码 |
| `code_mapping` | 否 | `{"file": "...", "lines": [1, "3-5"]}`；单块最多 400 行 |
| `jump` | 否 | 查看实现的导航链接；不画线、不影响执行 |
| `flow` | 否 | 跨视图主线继续；目标必须是 `main` / `flow` / `entry`；不画线 |
| `on` | 否 | 事件入口名；只能写在视图第一个顶层块，最长 80 字符 |

### 3.2 普通块 `normal`

| 字段 | 说明 |
|---|---|
| `next` | 不写 = 顺序下一块；整数 = 跳到该 id；`null` = 显式终止 |
| `emit` | 事件发出目标数组，元素 `{"id": 8}` 或 `{"view": "handler", "id": 1}`；目标必须带 `on` |

- `next` 只能指向**同一视图**里的块，不能指向自己。
- 普通块不能写 `select` / `branches` / `finally`；`kind` 目前只给 try 用。

> **最容易错的点：`null` 是“在这里终止”，不是“没写”。** 普通中间步骤直接省略 `next`；只有 `return` / `raise` / 退出程序 / `break` 到循环外才写 `null`。给中间步骤写 `"next": null` 会截断链路，后面的块会被判为不可达（覆盖率可能仍是 100%，但 `--strict` 会失败）。

### 3.3 分支块 `branch`

```json
{
  "id": 7,
  "type": "branch",
  "select": "single",
  "name": "按选择分发",
  "description": "六种功能、退出和无效输入。",
  "code_mapping": {"file": "gradebook.py", "lines": [87, 91, 93, 97, 100, 102, 104]},
  "branches": [
    {"condition": "输入 1", "steps": [
      {"id": 8, "type": "normal", "name": "输入姓名", "description": "读取姓名。",
       "code_mapping": {"file": "gradebook.py", "lines": [88]}}
    ]},
    {"condition": "其他输入", "steps": [
      {"id": 9, "type": "normal", "name": "提示无效选择", "description": "回到菜单。",
       "code_mapping": {"file": "gradebook.py", "lines": [105]}}
    ]}
  ]
}
```

- `select: "single"`：只走一条；`"multi"`：所有列表并行执行（只用于真实的并发/并行）。
- `branches` 非空；每条 `steps` 非空；`condition` 可省略，显示在扇出线上。
- 分支块不能写 `next` / `emit`。
- 列表尾默认汇入外层下一块；尾块写 `next` 则不汇合。用这个特性做循环回边和提前返回。

### 3.4 try / except / finally

```json
{
  "id": 2,
  "type": "branch",
  "kind": "try",
  "select": "single",
  "name": "读取配置文件",
  "description": "文件缺失时用默认值。",
  "branches": [
    {"role": "body", "steps": [
      {"id": 3, "type": "normal", "name": "读取配置", "description": "解析文件内容。"}
    ]},
    {"role": "except", "condition": "FileNotFoundError", "steps": [
      {"id": 4, "type": "normal", "name": "使用默认配置", "description": "回退到内置默认值。"}
    ]}
  ],
  "finally": [
    {"id": 5, "type": "normal", "name": "记录配置来源", "description": "无论成功失败都记录来源。"}
  ]
}
```

- `select` 必须是 `single`。
- 恰好一条 `role: "body"`，且必须是第一条；body 不能写 `condition`。
- 其余列表必须是 `role: "except"`；`condition` 可省略。
- 至少要有一条 except 或一个非空 `finally`；允许 try/finally 没有 except。
- body / except 列表尾汇入 finally 第一块；finally 出口继续外层下一块。
- finally 里是普通序列，不能写 `on`。

### 3.5 硬限制

| 限制 | 值 |
|---|---|
| 每个视图的块数 | ≤ 300 |
| 嵌套深度 | ≤ 5（顶层算第 1 层） |
| 单块映射行数 | ≤ 400 |
| 视图文件大小 | ≤ 2 MB |
| 代码文件大小 | ≤ 1 MB |
| `view.id` | `^[a-z][a-z0-9_-]{0,63}$` |
| `on` 长度 | ≤ 80 字符 |

### 3.6 执行与布局语义

- 顶层块按数组顺序从上到下；默认连到同序列下一块。
- 分支块扇出到各列表第一块；列表尾默认汇合到外层下一块。
- `next` 覆盖默认后继：整数跳转、`null` 终止。
- `jump` / `emit` 不画执行线，不参与可达性。
- 事件链分开：发出块写 `emit`，处理视图首块写 `on`。
- 所有结构用线条表达，没有“块中块”容器。

---

## 4. 六步转换流程

### Step 1：盘点源码

- 列出纳入范围的文件，写入 `files`；记录行数。
- 用 `grep` 找入口：`main`、`__main__`、路由装饰器、事件注册、`startup`、`schedule`。
- 列出函数/方法及其调用点：`grep -n "函数名("`。
- 标出模块级代码：import、常量、注册、装饰器副作用、单例初始化。
- 不读源码就画块是禁止的；每个映射必须来自实际读过的行。

### Step 2：列入口，定视图

- 每个入口一个链路视图；主入口用 `main`，其余 `entry-*`。
- 事件处理函数用 `on`，事件名与发出方 `emit` 对应。
- 确定哪些函数进细节视图，哪些内联。

### Step 3：画主链路

- 从入口第一块开始，按执行顺序排块。
- 调用一个复杂函数时，放一个“调用步”，写 `jump` 指向细节视图。
- 判断用 `branch`；循环用“回边 + 退出路径”；异常用 try。
- 终止用 `next: null`。

### Step 4：展开细节

- 每个细节视图从函数入口块开始，按函数体执行顺序排。
- `return` / `raise` 是终点，写 `next: null`。
- 被调用的子函数继续 `jump` 展开；不要复制正文。
- 细节视图可以 `jump` 回调用点，方便读者返回；但这只是导航。

### Step 5：覆盖扫描

- 跑 `validate --json`，看每个文件的 `uncovered` / `overlaps` / `outside`。
- 对每个未覆盖区间，找到对应源码，补块或补映射。
- 对每段重复映射，确定唯一归属：条件行归分支块，body 行归步骤块，`def`+docstring 归入口块。
- 反复直到所有文件 `ratio = 1.0`、三个问题列表为空。

### Step 6：验收

- `--strict` 退出码为 0。
- 浏览器打开入口视图，检查连线、分支标签、循环回边、代码栏。
- 输出交付报告（见第 8 节）。

---

## 5. 代码覆盖：规则与判定

### 5.1 哪些行算代码

**Python（`.py`）**：用 `tokenize` 计算。

- 空行、纯注释行不算。
- `import`、`def`、`class`、装饰器行算。
- docstring 和多行字符串算（token 跨越的行都算）。
- 行尾注释所在行仍算。

**其他语言**：逐行判断。

- 非空且不以 `#`、`//`、`/*`、`*`、`--`、`;` 开头的行算代码。
- 因此 C/C++ 的 `#include`、`#define` 行不算覆盖；块注释中以 `*` 开头的行也不算。
- 这意味着：不要给这些行写 `code_mapping`，否则会报“映射到非代码行”。

### 5.2 全覆盖的定义

对 `files` 里的每个文件：

- `uncovered` 为空：每个代码行至少被一个块映射。
- `overlaps` 为空：没有一行被两个块同时映射。
- `outside` 为空：没有映射到空行/注释行。
- `ratio = 1.0`。

再加两条全局检查：

- 每个 `main` / `flow` / `entry` 视图没有不可达块（`unreachable` 为空）；`function` / `struct` 是实现或声明集合，允许并排的独立块。
- 跨视图 `jump` 的目标 id 存在。

### 5.3 映射写法：区间不能夹空行

`lines` 支持整数和 `"a-b"` 区间，区间是连续的。

```jsonc
// 错：1-9 包含第 8 行空行，会产生 outside 警告
"lines": ["1-9"]

// 对：拆成多段，跳过空行 8
"lines": ["1-5", 6, 7, 9]
```

其他注意事项：

- 一个块可以写多个不连续区间：`[87, 91, 93, 97]`。
- 多行表达式可以整段映射，但段内不能有空行/纯注释行。
- 单块最多 400 行；大函数拆成多个步骤块。
- 同一行只能有一个归属。分支的 `if/elif/else` 行归分支块，分支体归步骤块。
- 循环的 `for` / `while` 行归循环控制块；循环体归步骤块。

### 5.4 门禁命令

```bash
python3 -m codifold.validate <工作区目录>            # 人类可读
python3 -m codifold.validate <工作区目录> --json     # 机器可读
python3 -m codifold.validate <工作区目录> --strict   # 有警告也失败，最终门禁
```

`--strict` 下，未覆盖、重复映射、映射到非代码行、以及 main/flow/entry 的执行不可达块都会让退出码变成 1。最终交付必须是 0。

---

## 6. 画法规范（质量线）

### 6.1 粒度

- 一个块 = 一个有意义的动作或一次判断，不是一条语句，也不是一整个文件。
- 链路视图控制在 ~15 个顶层块以内；超过就按子系统拆成细节视图。
- 分支列表控制在 ~6 条以内；超过考虑“分发视图 + 子链路”。
- 优先嵌套深度 ≤ 3；硬上限是 5。

### 6.2 命名与描述

| 好 | 坏 |
|---|---|
| `读取学生数据` | `执行第 12 行` |
| `校验成绩是否在 0-100` | `判断条件` |
| `写回 students.json` | `调用 save_students` |
| `姓名已存在，返回失败` | `返回` |
| `统计人数与平均分` | `处理数据` |

描述写“为什么/结果”，不要逐句翻译代码。引用细节视图时写“详见 fn-add”。

### 6.3 分支

- 条件必须可观察：`输入 1`、`分数 < 0`、`文件不存在`、`FileNotFoundError`。
- 不要写“条件成立/不成立”。
- 每个分支列表的尾块要明确出口：继续、回边、或 `next: null`。

### 6.4 循环

标准画法：

1. 循环头块（映射 `for` / `while` 行）。
2. 一个“还有下一项？”分支：有 → 循环体；没有 → 循环之后。
3. 循环体尾块 `next` 回循环头。

`break` 用 `next` 指向循环之后的块；`continue` 用 `next` 回循环头。

不要用一条没有出口的环；可达性检查会暴露问题。

### 6.5 异常

- 只有源码真的有 try/except/finally 时才用 `kind: "try"`。
- `try:` 行映射到 try 分支块；body / except 的正文映射到各自步骤。
- `raise` 用终止块，`next: null`，描述写清抛出的异常和条件。
- 不要为了“看起来完整”虚构异常分支。

### 6.6 事件与调用

- 普通函数调用：链路里的普通步骤 + `jump` 到细节视图。
- 事件：发出块 `emit`，处理视图首块 `on`；事件名保持一致。
- 不要把普通调用写成 `emit`，也不要用 `jump` 假装执行顺序。
- `multi` 只用于真实并行（线程、`Promise.all`、`asyncio.gather`、并行分支）；普通 if/elif 用 `single`。

### 6.7 导航

- 细节视图的终点可以 `jump` 回调用点，方便双击返回；这是可选的导航，不是执行。
- 跨视图 `jump` 的目标 id 必须存在；项目级校验会检查。

---

## 7. 学生成绩管理：完整样例

源码：`examples/gradebook/gradebook.py`，110 行，其中 **89 行是代码行**（空行不计）。

### 7.1 现状与目标

当前示例 `examples/gradebook/gradebook.blocks.json`：

- 覆盖 49 / 89 行（55.1%）。
- 40 行未映射：模块头、`find/delete/list/summary`、`main` 入口等。
- 12 段重复映射：分支块映射了 87–106，步骤又映射了分支体。

目标：**89 / 89，重复 0，非代码行 0，不可达 0，`--strict` 通过。**

> 注意：`examples/gradebook` 是默认示例，后端测试依赖它的视图 id、块顺序和覆盖率断言。新的转换请先放在独立工作区（例如 `examples/gradebook-chain`），经用户确认后再替换默认示例并同步更新测试。

### 7.2 视图拆分

| 视图 | 内容 | 映射行 |
|---|---|---|
| `struct` | 模块 docstring、`import`、`DATA_FILE` 常量；声明区，不执行 | 1–7、9 |
| `main` | 脚本入口、主函数入口、菜单循环、分发、退出 | 81–110（跳过 107–108） |
| `fn-load` | 函数签名 + 函数体 | 12–16 |
| `fn-save` | 函数签名 + 函数体 | 19–24 |
| `fn-find` | 函数签名 + 函数体 | 27–32 |
| `fn-add` | 函数签名 + 函数体 | 35–41 |
| `fn-update` | 函数签名 + 函数体 | 44–51 |
| `fn-delete` | 函数签名 + 函数体 | 54–61 |
| `fn-list` | 函数签名 + 函数体 | 64–70 |
| `fn-summary` | 函数签名 + 函数体 | 73–78 |

10 个视图，89 行全部有唯一归属。模块声明在 `struct`；函数签名随 `fn-*` 入口块；`DATA_FILE` 在 `struct` 单独成块，`fn-load` / `fn-save` 的使用处用 `jump` 指回。

### 7.3 `main` 行号归属表

| id | 类型 | 名称 | 映射行 | 出口 |
|---|---|---|---|---|
| 1 | normal | 脚本运行入口 | `109-110` | 顺序 |
| 2 | normal | 主函数入口 | `81-82` | 顺序 |
| 3 | normal | 读取学生数据 | `83` | jump `fn-load:1` |
| 4 | normal | 循环与菜单 | `84-85` | 顺序 |
| 5 | normal | 读取选择 | `86` | 顺序 |
| 6 | branch | 按选择分发 | `87, 91, 93, 97, 100, 102, 104` | 扇出 |
| 7 | normal | 输入姓名 | `88` | 顺序到 8 |
| 8 | normal | 输入成绩 | `89` | 顺序到 9 |
| 9 | normal | 新增并提示 | `90` | next 4；jump `fn-add:1` |
| 10 | normal | 列出学生 | `92` | next 4；jump `fn-list:1` |
| 11 | normal | 输入姓名（修改） | `94` | 顺序到 12 |
| 12 | normal | 输入新成绩 | `95` | 顺序到 13 |
| 13 | normal | 修改并提示 | `96` | next 4；jump `fn-update:1` |
| 14 | normal | 输入姓名（删除） | `98` | 顺序到 15 |
| 15 | normal | 删除并提示 | `99` | next 4；jump `fn-delete:1` |
| 16 | normal | 统计 | `101` | next 4；jump `fn-summary:1` |
| 17 | normal | 跳出循环 | `103` | next 19 |
| 18 | normal | 提示无效选择 | `105` | next 4 |
| 19 | normal | 保存并退出 | `106` | `null`；jump `fn-save:1` |

要点：

- **第一块就是运行入口**（`if __name__ == "__main__"`），不是模块头；模块 docstring/import 在 `struct`，`main` 的签名/docstring 在 id 2。
- 分支块只映射 `if/elif/else` 行，分支体归各自步骤，避免重复映射。
- 非 0 分支的尾块 `next: 4` 回到循环头；0 分支 `next: 19` 跳出。
- 所有分支尾块都显式写了 `next`，所以不会自动汇合到分支后的 id 19。

### 7.4 细节视图完整示例：`fn-add.blocks.json`

```json
{
  "view": {
    "id": "fn-add",
    "name": "新增学生",
    "description": "add_student：查重、追加、保存，返回是否成功。"
  },
  "blocks": [
    {
      "id": 1,
      "type": "normal",
      "name": "函数入口",
      "description": "入参：学生列表、姓名、成绩；返回是否新增成功。",
      "code_mapping": {"file": "gradebook.py", "lines": ["35-36"]}
    },
    {
      "id": 2,
      "type": "branch",
      "select": "single",
      "name": "姓名是否已存在",
      "description": "复用 find_student 查重；详见 fn-find。",
      "jump": {"view": "fn-find", "id": 1},
      "code_mapping": {"file": "gradebook.py", "lines": [37]},
      "branches": [
        {
          "condition": "已存在",
          "steps": [
            {
              "id": 3,
              "type": "normal",
              "name": "返回失败",
              "description": "不修改列表，返回 False。",
              "next": null,
              "code_mapping": {"file": "gradebook.py", "lines": [38]}
            }
          ]
        },
        {
          "condition": "不存在",
          "steps": [
            {
              "id": 4,
              "type": "normal",
              "name": "追加学生",
              "description": "把姓名和成绩加入列表。",
              "code_mapping": {"file": "gradebook.py", "lines": [39]}
            },
            {
              "id": 5,
              "type": "normal",
              "name": "写回磁盘",
              "description": "调用 save_students；详见 fn-save。",
              "jump": {"view": "fn-save", "id": 1},
              "code_mapping": {"file": "gradebook.py", "lines": [40]}
            },
            {
              "id": 6,
              "type": "normal",
              "name": "返回成功",
              "description": "返回 True。",
              "next": null,
              "code_mapping": {"file": "gradebook.py", "lines": [41]}
            }
          ]
        }
      ]
    }
  ]
}
```

### 7.5 其余函数的画法

| 函数 | 结构要点 |
|---|---|
| `load_students` | 入口签名（12–13）→ 分支“文件存在？”（14），jump `struct:2` → 不存在：返回空列表（15）；存在：读取解析（16），jump `struct:2` |
| `save_students` | 入口签名（19–20）→ 写回磁盘（21–24），jump `struct:2` → 终止 |
| `find_student` | 入口签名（27–28）→ 分支“还有学生？”（29）→ 有：分支“姓名匹配？”（30）→ 匹配返回学生（31）；不匹配回循环；没有：返回 None（32） |
| `update_score` | 入口签名（44–45）→ 查找（46）→ 分支“找到？”（47）→ 未找到返回 False（48）；找到：改分（49）→ 保存（50）→ 返回 True（51） |
| `delete_student` | 入口签名（54–55）→ 查找（56）→ 分支“找到？”（57）→ 未找到返回 False（58）；找到：移除（59）→ 保存（60）→ 返回 True（61） |
| `list_students` | 入口签名（64–65）→ 分支“列表为空？”（66）→ 空：提示并返回（67–68）；非空：逐条打印（69–70） |
| `class_summary` | 入口签名（73–74）→ 分支“列表为空？”（75）→ 空：返回零值（76）；非空：算平均分（77）→ 返回统计（78） |

每个细节视图的第一块“函数入口”直接映射该函数的 `def` + docstring。模块常量单独放 `struct` 的定义块：`DATA_FILE`（第 9 行）在“数据文件路径”块；`load_students` 的文件判断/读取块和 `save_students` 的写回块都用 `jump` 指回 `struct:2`。定义块不参与执行链，也不跟条件混在一起。

### 7.6 覆盖核对

- `struct`：7（模块 docstring 与 import）+ 1（`DATA_FILE`）= 8 行。
- `main`：2（脚本入口）+ 2（主函数签名）+ 1（读数据）+ 2（循环菜单）+ 1（读选择）+ 7（条件行）+ 12（分支体）+ 1（保存退出）= 28 行。
- 细节视图：5 + 6 + 6 + 7 + 8 + 8 + 7 + 6 = 53 行（含 18 行函数签名/docstring）。
- 合计 8 + 28 + 53 = 89 行，与 `total` 一致。
- 每个文件的 `uncovered` / `overlaps` / `outside` 都应为空。

按这一节生成 10 个视图后，`python3 -m codifold.validate <目录> --strict` 的结果是：`89/89 (100.0%)`、错误 0、警告 0。可作为画法是否正确的基线。

---

## 8. 验收与交付

### 8.1 命令

```bash
# 结构 + 覆盖率 + 连贯性
python3 -m codifold.validate <工作区目录>

# 机器可读，便于逐个文件检查
python3 -m codifold.validate <工作区目录> --json

# 最终门禁：任何警告都失败（同 workbench check）
python3 -m codifold.workbench check <工作区目录> --strict

# 连贯性：所有视图是否都能从 main 到达，必须是 1.0000
python3 -m codifold.workbench coherence <工作区目录> --json

# 导出只含名称和描述的文字稿，交给 AI 或人做文字审核
python3 -m codifold.workbench export-md <工作区目录> --out flow.md

# 浏览器查看（先启动服务）
python run.py
# http://127.0.0.1:5190/?project=<URL 编码后的绝对路径>&view=main
```

也可在前端“工作区”窗口里直接打开目录。

### 8.2 交付清单

```text
[ ] codifold.json 的 files 覆盖所有纳入范围的源码
[ ] 有一个 kind=main 的系统主线，views.entry 指向它
[ ] main 在命令/路由/线程等分发点分支，每个分支用 flow 接到对应 entry
[ ] 每个入口视图都能从 main 沿 flow 到达
[ ] 动态分发表（COMMANDS/ROUTES/STEPS/插件/事件）已经分支，没有停在“调用处理函数”
[ ] main/flow 视图没有“只有 jump 的出口”；终点是 next:null 或 flow
[ ] 每个有逻辑的函数/方法有细节视图或明确内联
[ ] 1–3 行的取值/转发函数已经内联，没有堆出大量 fn-* 视图
[ ] 所有块 id 唯一（含分支步骤、finally）
[ ] 每个文件的 uncovered / overlaps / outside 为空
[ ] 每个 main/flow/entry 视图 unreachable 为空
[ ] workbench check --strict 退出码 0（含叙事与连贯性）
[ ] 连贯性 = 1.0000，所有视图都能从 main 到达
[ ] 有对外契约时：契约视图覆盖所有对外类型/接口，`evidence` / `handler` 都能解析（见 [workbench.md](workbench.md#契约视图)）
[ ] 浏览器打开入口视图，侧栏分组、主线继续、布局/连线正常
[ ] 汇报：入口清单、视图清单（含 kind）、覆盖率表、未纳入范围及理由
```

### 8.3 汇报模板

```text
项目：<name>
源码范围：<files>
入口：<main / route / event ...>
视图：<N> 个（main, fn-*, mod-* ...）
覆盖：<file> 89/89 (100.0%)；<file2> ...
校验：errors 0, warnings 0, --strict exit 0
未纳入：<文件/目录及原因>
遗留：<无 / 具体问题>
```

---

## 9. 禁止事项与常见错误

| 禁止 / 错误 | 后果 | 正确做法 |
|---|---|---|
| 运行或 import 被讲解的项目 | 可能产生副作用，违反只读约束 | 只读源码 |
| 按“头文件→类→函数定义”顺序画 | 图不可读，丢失执行语义 | 从入口链路开始 |
| 把 import / 常量 / `def` 放在主链路开头 | 链路从声明开始，不是运行入口 | 模块声明放 `struct`，函数签名放入口块 |
| 函数签名/docstring 单独列成一张定义表 | 看函数体时找不到签名 | 映射到该函数入口块 |
| 常量定义和使用分开且没有跳转 | 使用时找不到出处 | 常量单独放 `struct` 定义块；每个使用处 `jump` 指回 |
| 主线在分发点就结束，只留一个 `jump` | 读者不知道下一步去哪 | 按子命令/路由/线程分支，分支尾用 `flow` 接入口 |
| 停在“调用处理函数” | 动态分发后的链路全断 | 按 `COMMANDS`/`ROUTES`/`PIPELINES`/插件注册项分支 |
| 每个函数都建 `fn-*`，侧栏平铺几十个 | 阅读退化成翻代码目录 | 1–3 行函数内联；函数细节默认折叠，只从 `jump` 进入 |
| 把函数细节当作主线继续 | 读者进入实现细节后无路可走 | 主线用 `flow`，细节用 `jump` |
| 视图之间没有入边 | 连贯性 < 1，读者永远找不到 | 从相关块补 `jump`/`flow`；独立内容在主流程占分支或块 |
| 一个函数一个块，不展开 | 实现细节缺失 | 关键函数建细节视图 |
| 每个语句一个块 | 块爆炸，超过 300 上限 | 按语义分组 |
| `if/elif` 行同时映射到分支块和步骤 | 重复映射警告 | 条件行归分支块，body 归步骤 |
| 映射区间夹空行/注释 | `outside` 警告 | 拆成多段区间 |
| 给 `#include` 写映射（非 Python） | `outside` 警告 | 这些行不算代码，不映射 |
| 分支块写 `next` / `emit` | 校验错误 | 出口写在分支尾块上 |
| `on` 写在非首块 | 校验错误 | 只能写在视图第一个顶层块 |
| `emit` 指向没有 `on` 的块 | 校验错误 | 目标必须是事件入口 |
| 跨视图用 `next` | 校验错误 | 跨视图只用 `flow` / `jump` / `emit` |
| 分批写入时用 `view:key` 引用已有视图 | 校验错误：跨视图 key 只能指向同一批次 | 指回已有视图写数字 `id`，如 `{"view": "mod-api", "id": 19}` |
| 中间步骤写 `"next": null` | 截断链路，后续块不可达 | 只有真正 return/退出才写 `null` |
| 用 `jump` 表示执行顺序 | 图上没有线，语义错误 | 执行顺序用默认边/`next` |
| 为了好看虚构分支 | 与源码不符 | 只画源码真实存在的路径 |
| 覆盖没满就交付 | 细节缺失 | 跑到 `ratio = 1.0` 且 `--strict` 通过 |
| 覆盖默认示例 `examples/gradebook` | 破坏测试/默认演示 | 新工作区，评审后再替换 |

---

## 10. 给新会话的任务书（可直接照此执行）

```text
你要把一个真实项目转换成 Codifold 工作区。只读 docs/conversion-guide.md 和源码，不运行目标项目。

1. 确认三件事：源码根目录、纳入覆盖的文件列表、输出工作区目录。
   用户未指定输出目录时，不要覆盖 examples/gradebook；新建独立目录并在汇报中说明。
2. 盘点：入口清单、函数/方法清单、调用关系、模块级代码。
3. 建 codifold.json：project.name/description/root、files、views.entry；
   并先放一个起始视图文件（例如 main.blocks.json：一个块 + code_mapping + next:null），
   否则 brief/apply 会因“目录里没有 .blocks.json 视图文件”失败。
   也可以在前端“工作区 → 新建”里创建，再在“项目设置”里补 files。
4. 用 `python3 -m codifold.workbench brief <目录> --view <入口视图> --snippets`
   （或 MCP 的 `codifold_brief`）看当前结构和未覆盖行；按 [workbench.md](workbench.md)
   写局部草稿，用 `apply` 写入（MCP 的 `codifold_apply` 默认 dry_run=true）。
   不要手写整份最终 JSON；更新已有视图时保留被外部引用的块 id，
   指回已有视图的引用写数字 `id`，不要用 `view:key`。
5. 先画 `kind: "main"` 的系统主线：运行入口 → 参数/配置 → 按子命令分发；
   每个分支尾用 `flow` 接到对应 `entry-*`。再画各入口链路；函数细节只作为 `jump` 目标。
6. 动态分发表必须分支：`COMMANDS`、`ROUTES`、`PIPELINES`/`STEPS`、插件扫描、事件订阅。
   不允许在“调用处理函数”处结束。
7. 按第 5 节做行归属：每行恰好一个块；区间跳过空行/注释；if/elif 行归分支块。
   1–3 行的取值/转发函数内联，不要为每个函数都建 `fn-*`。
8. 如果项目有对外的 JSON 接口、类型、配置键或前端组件，另建 `kind: "contract"` 的
   契约视图：块写 `contract`（`type` / `endpoint`）+ `evidence` / `handler`，
   不写 `code_mapping`。规则见 [workbench.md](workbench.md#契约视图)。
9. 反复跑 `python3 -m codifold.workbench brief <目录> --json` 和
   `python3 -m codifold.validate <目录> --json`，直到每个文件 ratio=1.0、
   uncovered/overlaps/outside 为空、每个 main/flow/entry 视图 unreachable 为空。
10. 最终跑 `python3 -m codifold.workbench check <目录> --strict`，退出码必须为 0；
    浏览器打开入口视图检查侧栏分组、主线继续和连线。
11. 按第 8.3 节模板汇报，附校验输出和覆盖率表。
```
