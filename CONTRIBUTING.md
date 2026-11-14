# 参与贡献

Codifold 是初期 Demo，欢迎问题反馈、工具修复和有过程记录的案例。开始前请读 [README](README.md) 与 [当前状态](docs/current-status.md)。

## 当前探索重点

陌生项目如何转换成清晰逻辑图还没有可靠方法。当前优先自己边写小项目边维护逻辑图，记录成功与失败，再从多个案例中提炼规律，最后形成 SKILL。

现有转换指南是实验参考；请不要把机械门禁通过描述成语义正确或转换方法已经验证。贡献案例时使用 [案例模板](docs/case-study-template.md)，记录源码快照、画法取舍、失败修改和实际阅读反馈。未完成案例可以明确标注阶段，进入独立实验目录；合入 `examples/` 的完整示例则需要通过严格检查。

## 开发环境与验证

Python ≥ 3.10，后端只用标准库；修改前端需要 Node ≥ 20.19。

```bash
python -m pip install -e .
python -B -m unittest discover -s tests -q
python -m codifold.workbench check examples/gradebook-chain --strict
python -m codifold.workbench check examples/taskflow --strict
cd frontend
npm ci
npm run build
```

CI 会运行 Linux、Windows、macOS 后端测试，并构建 sdist / wheel、在干净环境中测试安装后的 CLI、HTTP 页面、静态资源、示例和 MCP 指南。修改前端时请同步提交 `frontend/dist`；它让源码下载后无需 Node 即可运行。

本地验证安装包：

```bash
python -m pip install build
python -m build
python -m venv /tmp/codifold-demo-smoke
/tmp/codifold-demo-smoke/bin/python -m pip install dist/*.whl
cd /tmp
/tmp/codifold-demo-smoke/bin/python /path/to/Codifold/scripts/smoke_installed.py
```

Windows 用相应虚拟环境的 `Scripts/python.exe`，并在仓库外的临时目录运行冒烟脚本。

## 开发边界

- 文档与界面文案使用中文。块命名描述行为与结果，避免逐句翻译源码。
- `examples/gradebook` 是保留不完整映射的教学对照；测试依赖其视图 id 和覆盖率，不直接改成全覆盖。新完整示例放独立目录。
- 后端不执行被讲解项目，服务保持只监听本机回环；不提供整目录删除。
- 工作区修改走公共写入接口，版本检查、草稿编译和回滚都应处于同一工作区锁保护下。
- 编辑允许覆盖未完成和视图未接通的草稿；契约与引用硬错误仍阻止保存。最终检查用 `check --strict`。
- Python 包、CLI 和 MCP 共用 `codifold/__init__.py` 的版本；更新版本时同步前端 package 与 lockfile。
- JSON 格式仍在探索；改变格式或校验规则时说明对现有示例的影响。

## 提交 PR

一个 PR 聚焦一个问题，说明最终行为、验证结果和未验证的部分。新画法先作为案例中的假设讨论，有多个案例支持后再考虑提炼为 SKILL。
