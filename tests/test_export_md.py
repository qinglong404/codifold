import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config, export_md, flat, workbench

SOURCE = '''"""Demo source."""
import json

DATA = "x"


def load():
    """Load."""
    if not DATA:
        return []
    return json.loads(DATA)
'''


def normal(ident, name="步骤", description="描述", **extra):
    block = {"id": ident, "type": "normal", "name": name,
             "description": description}
    block.update(extra)
    return block


def view(view_id, blocks, *, kind=None, name=None, description="视图说明"):
    payload = {"id": view_id, "name": name or view_id,
               "description": description}
    if kind:
        payload["kind"] = kind
    return {"view": payload, "blocks": blocks}


def write_workspace(directory: Path, views, *, entry="main", flat_format=False):
    (directory / "app.py").write_text(SOURCE, encoding="utf-8")
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": ["app.py"],
        "views": {"suffix": ".blocks.json", "entry": entry},
    }
    if flat_format:
        manifest["views"]["format"] = "flat"
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for config in views:
        data = flat.from_nested(config) if flat_format else config
        (directory / f"{config['view']['id']}.blocks.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")


def sample_views():
    return [
        view("main", [
            normal(1, "启动", "从脚本入口进入。",
                   code_mapping={"file": "app.py", "lines": ["1-10"]},
                   flow={"view": "entry-run", "id": 1}),
            normal(2, "结束", "流程结束。", next=None),
        ], kind="main", name="主流程", description="从启动讲到结束。"),
        view("entry-run", [
            {"id": 1, "type": "branch", "name": "有数据吗？",
             "description": "检查数据是否存在。", "select": "single",
             "code_mapping": {"file": "app.py", "lines": [9]},
             "branches": [
                 {"condition": "没有", "steps": [
                     normal(2, "返回空", "没有数据时返回空列表。", next=None,
                            code_mapping={"file": "app.py", "lines": [10]}),
                 ]},
                 {"condition": "有", "steps": [
                     normal(3, "解析", "读取并解析数据。", next=None,
                            jump={"view": "fn-load", "id": 1},
                            code_mapping={"file": "app.py", "lines": [11]}),
                 ]},
             ]},
        ], kind="entry", name="运行入口", description="检查后进入函数。"),
        view("fn-load", [
            normal(1, "函数入口", "加载。", next=None,
                   jump={"view": "mod-defs", "id": 1},
                   code_mapping={"file": "app.py", "lines": ["7-8"]}),
        ], kind="function", name="加载函数", description="加载的实现。"),
        view("mod-defs", [
            normal(1, "常量", "数据常量。", next=None,
                   code_mapping={"file": "app.py", "lines": [3]}),
        ], kind="struct", name="定义", description="模块定义。"),
    ]


class ExportMdTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_export_orders_views_and_renders_navigation(self):
        write_workspace(self.directory, sample_views())
        text, summary = export_md.build(str(self.directory))

        self.assertEqual(summary["views"], 4)
        self.assertEqual(summary["blocks"], 7)
        self.assertIn('<a id="view-main"></a>', text)
        self.assertIn("1. [main · 主流程](#view-main)", text)
        self.assertLess(text.index("## 1. main"), text.index("## 2. entry-run"))
        self.assertLess(text.index("## 2. entry-run"), text.index("## 3. fn-load"))
        self.assertLess(text.index("## 3. fn-load"), text.index("## 4. mod-defs"))
        self.assertIn("[1] 启动 —— 从脚本入口进入。", text)
        self.assertIn("主线继续 → entry-run:1", text)
        self.assertIn("**如果：没有**", text)
        self.assertIn("**如果：有**", text)
        self.assertIn("展开细节 → fn-load:1", text)
        self.assertIn("展开细节 → mod-defs:1", text)
        self.assertNotIn("````", text)
        self.assertNotIn("def load", text)
        again, _ = export_md.build(str(self.directory))
        self.assertEqual(text, again)

    def test_export_with_code_appendix_and_truncation(self):
        write_workspace(self.directory, sample_views())
        text, summary = export_md.build(
            str(self.directory), with_code=True, max_code_lines=2)

        self.assertIn("## 附录 C. 代码证据", text)
        self.assertIn("#### main:1 · 启动", text)
        self.assertIn("`app.py:1-10`", text)
        self.assertIn("import json", text)
        self.assertIn("（本块代码已截断，最多 2 行）", text)
        self.assertIn("#### fn-load:1 · 函数入口", text)
        self.assertIn("def load():", text)

    def test_view_and_kind_filters(self):
        write_workspace(self.directory, sample_views())
        text, _ = export_md.build(str(self.directory), views=["entry-run"])
        self.assertIn("## 1. entry-run", text)
        self.assertNotIn("## 1. main", text)
        self.assertIn("展开细节 → fn-load:1（未导出）", text)
        self.assertNotIn("## 2.", text)

        text, _ = export_md.build(str(self.directory), kinds=["function"])
        self.assertIn("## 1. fn-load", text)
        self.assertNotIn("## 1. main", text)

    def test_try_labels_and_finally(self):
        write_workspace(self.directory, [
            view("main", [
                normal(1, "启动", "进入尝试。", next=None,
                       jump={"view": "fn-try", "id": 1}),
            ], kind="main", name="主流程", description="主线。"),
            view("fn-try", [
                {"id": 1, "type": "branch", "kind": "try", "select": "single",
                 "name": "读取（可能失败）", "description": "读取并处理错误。",
                 "branches": [
                     {"role": "body", "steps": [
                         normal(2, "读取", "正常读取。", next=None,
                                code_mapping={"file": "app.py", "lines": [9]}),
                     ]},
                     {"role": "except", "condition": "ValueError", "steps": [
                         normal(3, "回退", "失败时回退。", next=None,
                                code_mapping={"file": "app.py", "lines": [10]}),
                     ]},
                 ],
                 "finally": [
                     normal(4, "关闭", "最后关闭。", next=None,
                            code_mapping={"file": "app.py", "lines": [11]}),
                 ]},
            ], kind="function", name="尝试", description="try 细节。"),
        ])
        text, _ = export_md.build(str(self.directory), views=["fn-try"])
        self.assertIn("**正常执行**", text)
        self.assertIn("**异常处理：ValueError**", text)
        self.assertIn("**最后一定执行**", text)

    def test_flat_workspace_uses_nested_projection(self):
        write_workspace(self.directory, sample_views(), flat_format=True)
        text, summary = export_md.build(str(self.directory))
        self.assertIn("**如果：没有**", text)
        self.assertIn("主线继续 → entry-run:1", text)
        self.assertEqual(summary["views"], 4)

    def test_filters_and_missing_view(self):
        write_workspace(self.directory, sample_views())
        with self.assertRaisesRegex(ValueError, "找不到视图"):
            export_md.build(str(self.directory), views=["missing"])
        with self.assertRaisesRegex(ValueError, "筛选后没有"):
            export_md.build(str(self.directory), kinds=["toolbox"])

    def test_cli_writes_file_and_stdout(self):
        write_workspace(self.directory, sample_views())
        output = self.directory / "exports" / "flow.md"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(workbench.main([
                "export-md", str(self.directory), "--out", str(output),
            ]), 0)
        self.assertTrue(output.exists())
        self.assertIn("# 测试项目 流程图文字稿", output.read_text(encoding="utf-8"))
        self.assertIn("已导出 4 个视图", stderr.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(workbench.main([
                "export-md", str(self.directory), "--view", "main",
            ]), 0)
        self.assertIn("## 1. main", stdout.getvalue())
        self.assertNotIn("## 1. entry-run", stdout.getvalue())

    def test_cli_missing_workspace_returns_one(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(workbench.main([
                "export-md", str(self.directory / "missing"),
            ]), 1)
        self.assertIn("找不到工作区", stderr.getvalue())

    def test_coverage_and_coherence_appendix(self):
        write_workspace(self.directory, sample_views())
        text, summary = export_md.build(str(self.directory))
        self.assertIn("## 附录 A. 自动检查", text)
        self.assertIn("- 覆盖率：", text)
        self.assertIn("- 连贯性：4/4（1.0000）", text)
        self.assertEqual(summary["coherence"]["score"], 1.0)
        self.assertIn("### 无代码映射的块", text)

    def test_orphan_view_is_exported_and_marked(self):
        views = sample_views()
        views.append(view("mod-extra", [
            normal(1, "额外定义", "没有被主线引用。", next=None),
        ], kind="struct", name="额外定义", description="孤立视图。"))
        write_workspace(self.directory, views)
        text, _ = export_md.build(str(self.directory))
        self.assertIn("## 5. mod-extra · 额外定义", text)
        self.assertIn("（未从主线到达）", text)
        self.assertIn("**注意**：这个视图无法从主线到达。", text)
        self.assertIn("### 未从主线到达的视图", text)

    def test_emit_and_parallel_branch_labels(self):
        write_workspace(self.directory, [
            view("main", [
                normal(1, "发布", "发布事件。",
                       emit=[{"view": "entry-run", "id": 1}]),
                {"id": 2, "type": "branch", "name": "并行处理",
                 "description": "两条支路同时发生。", "select": "multi",
                 "branches": [
                     {"condition": "第一条", "steps": [
                         normal(3, "一", "第一条。", next=None),
                     ]},
                     {"condition": "第二条", "steps": [
                         normal(4, "二", "第二条。", next=None),
                     ]},
                 ]},
            ], kind="main", name="主流程", description="主线。"),
            view("entry-run", [
                normal(1, "入口", "处理事件。", next=None, on="test.event"),
            ], kind="entry", name="入口", description="入口。"),
        ])
        text, _ = export_md.build(str(self.directory))
        self.assertIn("事件通知 → entry-run:1", text)
        self.assertIn("**并行分支：第一条**", text)
        self.assertIn("**并行分支：第二条**", text)


if __name__ == "__main__":
    unittest.main()
