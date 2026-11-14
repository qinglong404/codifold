# 参与贡献

欢迎 Issue、Discussion 和 PR。开工前先读 [README.md](README.md) 和 [docs/conversion-guide.md](docs/conversion-guide.md)——后者是“项目 → 流程”转换的完整画法规范，也是这个工具的核心思想所在。

## 开发环境

- Python ≥ 3.10（后端只用标准库）
- Node ≥ 20.19（只有改前端时需要）

```bash
python -B -m unittest discover -s tests -q      # 后端单测
python3 -m codifold.workbench check examples/gradebook-chain --strict   # 示例门禁
cd frontend && npm ci && npm run build          # 前端构建
```

## 约定

- **文档与界面文案用中文**；块命名用“动词 + 对象”（如“读取学生数据”），描述写“为什么/结果”，不逐句翻译代码。
- **示例工作区**：`examples/gradebook` 是默认演示（有意保留 55% 覆盖率，供对照教学），后端测试依赖它的视图 id 和覆盖率断言，不要改动；新示例放独立目录（参考 `examples/gradebook-chain`、`examples/taskflow`），且必须能通过 `workbench check <目录> --strict`。
- **转换新项目**时按 conversion-guide 第 10 节的任务书执行：入口链路组织、代码行全覆盖、连贯性 1.0000。
- 后端改动保持“只读写 JSON、不执行被讲解项目”的边界；服务器保持只监听本机回环。

## 提交 PR

1. Fork 后建分支；一个 PR 聚焦一件事。
2. 提交前跑上面三条验证命令，全部通过。
3. PR 描述里写清动机和验证结果；改了校验规则时，附上对示例工作区的影响。
