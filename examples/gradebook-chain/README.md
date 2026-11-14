# 学生成绩管理（链路版）

按 [docs/conversion-guide.md](../../docs/conversion-guide.md) 的入口链路方法生成的评审样例，用于和默认的 `examples/gradebook` 对比。

- 源码复用 `../gradebook/gradebook.py`，不复制、不修改。
- 10 个视图：`struct` 声明区（docstring / import / `DATA_FILE`）+ `main` 运行链路 + 8 个 `fn-*` 函数细节。
- `main` 从 `if __name__ == "__main__"` 开始，不从模块头开始；`main` 的签名/docstring 在“主函数入口”块。
- 每个 `fn-*` 的“函数入口”块直接映射该函数的 `def` + docstring。
- `DATA_FILE` 在 `struct` 单独成块（“数据文件路径”）；`load_students` 的判断/读取块和 `save_students` 的写回块用 `jump` 指回 `struct:2`。定义不塞进条件块。
- 覆盖：`gradebook.py` 89 / 89 行（100.0%），无重复映射、无非代码行映射、无不可达块。

校验：

```bash
python3 -m codifold.validate examples/gradebook-chain --strict
```

查看：

```bash
python3 run.py
# http://127.0.0.1:5190/?project=<仓库绝对路径>/examples/gradebook-chain&view=main
```

也可以通过前端“工作区”窗口打开本目录。评审通过前不替换默认示例。
