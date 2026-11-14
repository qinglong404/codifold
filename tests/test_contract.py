import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codifold import (block_config, checks, contract, draft, editor, export_md,
                      flat, workbench)

SOURCE = '"""Demo."""\nVALUE = 1\ndef start():\n    return VALUE\n'


def normal(ident, name="步骤", description="说明", mapping=None, **extra):
    block = {"id": ident, "type": "normal", "name": name,
             "description": description}
    if mapping is not None:
        lines = mapping if isinstance(mapping, list) else [mapping]
        block["code_mapping"] = {"file": "app.py", "lines": lines}
    block.update(extra)
    return block


def type_payload():
    return {"kind": "type", "fields": [
        {"name": "id", "type": "int", "required": True},
        {"name": "status", "type": "enum",
         "values": ["queued", "done"]},
    ]}


def endpoint_payload(**extra):
    payload = {
        "kind": "endpoint", "method": "POST", "path": "/jobs",
        "auth": True, "request": "JobCreate", "response": "Job",
        "status": 201,
        "errors": [{"status": 400, "when": "参数非法"}],
        "handler": {"view": "fn-handler", "id": 1},
    }
    payload.update(extra)
    return payload


def contract_view():
    return {
        "view": {"id": "contract-api", "name": "任务 API 契约",
                 "description": "类型与接口的静态契约。", "kind": "contract"},
        "blocks": [
            normal(1, "Job", "任务记录。", contract=type_payload(),
                   evidence=[{"view": "mod-defs", "id": 1}]),
            normal(2, "JobCreate", "创建参数。",
                   contract={"kind": "type", "fields": [
                       {"name": "type", "type": "string", "required": True},
                   ]},
                   evidence=[{"view": "mod-defs", "id": 1}]),
            normal(3, "创建任务", "校验后写入。",
                   contract=endpoint_payload()),
        ],
    }


def base_views():
    return [
        {
            "view": {"id": "main", "name": "主流程",
                     "description": "从启动到结束。", "kind": "main"},
            "blocks": [
                normal(1, "启动", "启动。", mapping=1,
                       jump={"view": "mod-defs", "id": 1}),
                normal(2, "结束", "结束。", mapping=2, next=None),
            ],
        },
        {
            "view": {"id": "mod-defs", "name": "模块定义",
                     "description": "类型和处理器。", "kind": "struct"},
            "blocks": [
                normal(1, "类型定义", "类型定义。", mapping=3,
                       jump={"view": "contract-api", "id": 1}),
                normal(2, "处理函数", "处理函数。", mapping=4,
                       jump={"view": "fn-handler", "id": 1}),
            ],
        },
        {
            "view": {"id": "fn-handler", "name": "处理函数",
                     "description": "接口实现。", "kind": "function"},
            "blocks": [normal(1, "处理入口", "处理入口。", next=None)],
        },
        contract_view(),
    ]


def write_workspace(directory: Path, views=None, *, entry="main",
                    flat_format=False):
    (directory / "app.py").write_text(SOURCE, encoding="utf-8")
    manifest = {
        "project": {"name": "契约测试", "description": "测试描述", "root": "."},
        "files": ["app.py"],
        "views": {"suffix": ".blocks.json", "entry": entry},
    }
    if flat_format:
        manifest["views"]["format"] = "flat"
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for config in views if views is not None else base_views():
        data = flat.from_nested(config) if flat_format else config
        (directory / f"{config['view']['id']}.blocks.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")


class ContractValidationTests(unittest.TestCase):
    def validate(self, blocks, *, view_id="contract-api", kind="contract"):
        return block_config.validate({
            "view": {"id": view_id, "name": "契约",
                     "description": "契约说明", "kind": kind},
            "blocks": blocks,
        })

    def test_valid_payload_is_normalized(self):
        checked = self.validate(contract_view()["blocks"])
        self.assertEqual(checked["blocks"][0]["contract"]["kind"], "type")
        self.assertEqual(checked["blocks"][2]["contract"]["method"], "POST")
        self.assertEqual(checked["blocks"][2]["contract"]["handler"],
                         {"view": "fn-handler", "id": 1})

    def test_contract_view_requires_contract_payload(self):
        block = normal(1, "Job", "任务。")
        with self.assertRaisesRegex(ValueError, "缺少 contract"):
            self.validate([block])

    def test_contract_field_rejected_outside_contract_view(self):
        block = normal(1, "Job", "任务。", contract=type_payload(),
                       evidence=[{"view": "mod-defs", "id": 1}])
        with self.assertRaisesRegex(ValueError, "只能写在 kind=contract"):
            self.validate([block], view_id="flow-demo", kind="flow")

    def test_contract_block_rejects_flow_fields_and_mapping(self):
        cases = [
            ({"next": None}, "不能写 next"),
            ({"jump": {"view": "mod-defs", "id": 1}}, "不能写 jump"),
            ({"flow": {"view": "mod-defs", "id": 1}}, "不能写 flow"),
            ({"emit": [{"view": "mod-defs", "id": 1}]}, "不能写 emit"),
            ({"on": "demo.event"}, "不能写 on"),
            ({"code_mapping": {"file": "app.py", "lines": [1]}},
             "不能写 code_mapping"),
        ]
        for extra, message in cases:
            block = normal(1, "Job", "任务。", contract=type_payload(),
                           evidence=[{"view": "mod-defs", "id": 1}], **extra)
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ValueError, message):
                    self.validate([block])

    def test_type_payload_rules(self):
        cases = [
            ({"kind": "type", "fields": []}, "非空数组"),
            ({"kind": "type", "fields": [{"name": "id", "type": "int"},
                                         {"name": "id", "type": "str"}]},
             "name 重复"),
            ({"kind": "type", "fields": [{"name": "s", "type": "enum"}]},
             "values"),
            ({"kind": "type", "fields": [{"name": "s", "type": "str",
                                          "values": ["a"]}]},
             "只在 type=enum"),
            ({"kind": "type", "fields": [{"name": "id", "type": "int",
                                          "bogus": 1}]}, "未知字段"),
            ({"kind": "type", "fields": [{"name": "id", "type": "int",
                                          "required": "yes"}]}, "布尔值"),
            ({"kind": "type"}, "fields"),
        ]
        for payload, message in cases:
            block = normal(1, "Job", "任务。", contract=payload,
                           evidence=[{"view": "mod-defs", "id": 1}])
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    self.validate([block])

    def test_endpoint_payload_rules(self):
        cases = [
            ({"method": "TRACE"}, "method"),
            ({"path": "jobs"}, "path"),
            ({"status": 700}, "status"),
            ({"errors": [{"status": 200, "when": "x"}]}, "400-599"),
            ({"errors": [{"status": 400, "when": "x"},
                         {"status": 400, "when": "y"}]}, "重复"),
            ({"handler": "fn-handler:1"}, r"\{view, id\}"),
            ({"timeout": 3}, "未知字段"),
        ]
        for extra, message in cases:
            block = normal(3, "创建任务", "创建。",
                           contract=endpoint_payload(**extra))
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ValueError, message):
                    self.validate([contract_view()["blocks"][0], block])

    def test_branch_block_rejected_in_contract_view(self):
        branch = {
            "id": 2, "type": "branch", "name": "分支", "description": "分支。",
            "select": "single",
            "branches": [{"condition": "是", "steps": [
                normal(3, "步骤", "步骤。", contract=type_payload(),
                       evidence=[{"view": "mod-defs", "id": 1}]),
            ]}],
        }
        with self.assertRaisesRegex(ValueError, "必须是普通块"):
            self.validate([contract_view()["blocks"][0], branch])

    def test_flat_round_trip_preserves_payload(self):
        flat_config = flat.from_nested(contract_view())
        checked = flat.validate_flat(flat_config)
        self.assertEqual(checked["blocks"][0]["contract"]["kind"], "type")
        self.assertEqual(checked["blocks"][0]["evidence"],
                         [{"view": "mod-defs", "id": 1}])


class ContractReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        write_workspace(self.directory)

    def test_valid_workspace_passes_strict_check(self):
        report = contract.report(self.directory)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual([item["name"] for item in report["types"]],
                         ["Job", "JobCreate"])
        self.assertEqual(len(report["endpoints"]), 1)

        data = checks.report(self.directory, strict=True)
        self.assertTrue(data["ok"], data["errors"] + data["warnings"])
        self.assertEqual(data["contract"]["types"][0]["view"],
                         "contract-api")

    def test_duplicate_type_name(self):
        views = base_views()
        views[-1]["blocks"].append(
            normal(9, "Job", "重复类型。", contract=type_payload(),
                   evidence=[{"view": "mod-defs", "id": 1}]))
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertFalse(report["ok"])
        self.assertTrue(any("类型名重复" in error
                            for error in report["errors"]))
        self.assertFalse(checks.report(self.directory)["ok"])

    def test_duplicate_endpoint(self):
        views = base_views()
        views[-1]["blocks"].append(
            normal(4, "再来一次", "重复接口。",
                   contract=endpoint_payload()))
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(any("接口重复" in error for error in report["errors"]))

    def test_unresolved_type_reference(self):
        views = base_views()
        views[-1]["blocks"][2]["contract"]["response"] = "Missing"
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(any("response 类型不存在" in error
                            for error in report["errors"]))

    def test_handler_and_external_rules(self):
        views = base_views()
        payload = views[-1]["blocks"][2]["contract"]
        payload.pop("handler")
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(any("缺少 handler" in error for error in report["errors"]))

        views = base_views()
        payload = views[-1]["blocks"][2]["contract"]
        payload["external"] = True
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(any("不能写 handler" in error for error in report["errors"]))

        views = base_views()
        payload = views[-1]["blocks"][2]["contract"]
        payload.pop("handler")
        payload["external"] = True
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(report["ok"], report["errors"])

    def test_evidence_targets(self):
        cases = [
            ({"view": "missing", "id": 1}, "不存在的视图"),
            ({"view": "contract-api", "id": 2}, "不能指向契约视图"),
            ({"view": "mod-defs", "id": 99}, "不存在的 id"),
        ]
        for ref, message in cases:
            views = base_views()
            views[-1]["blocks"][0]["evidence"] = [ref]
            write_workspace(self.directory, views)
            report = contract.report(self.directory)
            with self.subTest(ref=ref):
                self.assertTrue(any(message in error
                                    for error in report["errors"]),
                                report["errors"])

        views = base_views()
        views[-1]["blocks"][0]["evidence"] = [{"view": "fn-handler", "id": 1}]
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(report["ok"])
        self.assertTrue(any("没有 code_mapping" in warning
                            for warning in report["warnings"]))

    def test_type_without_evidence_warns_and_strict_fails(self):
        views = base_views()
        views[-1]["blocks"][0].pop("evidence")
        write_workspace(self.directory, views)
        report = contract.report(self.directory)
        self.assertTrue(report["ok"])
        self.assertTrue(any("没有 evidence" in warning
                            for warning in report["warnings"]))
        self.assertTrue(checks.report(self.directory)["ok"])
        self.assertFalse(checks.report(self.directory, strict=True)["ok"])

    def test_entry_contract_warns(self):
        write_workspace(self.directory, entry="contract-api")
        report = contract.report(self.directory)
        self.assertTrue(any("入口视图 contract-api 是契约视图" in warning
                            for warning in report["warnings"]))

    def test_flat_workspace(self):
        write_workspace(self.directory, flat_format=True)
        report = contract.report(self.directory)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(len(report["types"]), 2)
        self.assertTrue(checks.report(self.directory, strict=True)["ok"])

    def test_check_cli_reports_contract_section(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main([
                "check", str(self.directory), "--json"]), 0)
        data = json.loads(output.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["contract"]["types"]), 2)
        self.assertEqual(len(data["contract"]["endpoints"]), 1)

    def test_export_contract_tables(self):
        text, summary = export_md.build(str(self.directory))
        self.assertIn("## 2. contract-api · 任务 API 契约", text)
        self.assertIn("### 类型", text)
        self.assertIn("| 字段 | 类型/取值 | 必填 | 说明 |", text)
        self.assertIn(
            "| 创建任务 [3] | POST | /jobs | 是 | JobCreate | Job（201） | "
            "400 参数非法 | fn-handler:1 | 校验后写入。 |", text)
        self.assertIn("来源：mod-defs:1", text)
        self.assertNotIn("- [1] Job ——", text)
        self.assertEqual(summary["contract"]["types"][0]["name"], "Job")
        self.assertIn("- 契约：2 个类型、1 个接口", text)

    def test_export_contract_filter_marks_unexported_refs(self):
        text, summary = export_md.build(
            str(self.directory), kinds=["contract"])
        self.assertIn("## 1. contract-api", text)
        self.assertNotIn("## 1. main", text)
        self.assertIn("来源：mod-defs:1（未导出）", text)
        self.assertIn("fn-handler:1（未导出）", text)
        self.assertEqual(summary["views"], 1)

    def test_check_cli_fails_on_contract_error(self):
        views = base_views()
        views[-1]["blocks"].append(
            normal(9, "Job", "重复类型。", contract=type_payload(),
                   evidence=[{"view": "mod-defs", "id": 1}]))
        write_workspace(self.directory, views)
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(workbench.main([
                "check", str(self.directory)]), 1)

    def test_draft_compiles_contract_block(self):
        spec = {
            "view": {"id": "contract-extra", "name": "额外契约",
                     "description": "额外类型。", "kind": "contract"},
            "blocks": [{
                "key": "job", "name": "Extra", "description": "额外类型。",
                "contract": {"kind": "type", "fields": [
                    {"name": "id", "type": "int", "required": True},
                ]},
                "evidence": [{"view": "mod-defs", "id": 1}],
            }],
        }
        configs = draft.compile_drafts(str(self.directory), [spec])
        self.assertEqual(configs[0]["blocks"][0]["contract"]["kind"], "type")
        self.assertEqual(configs[0]["blocks"][0]["evidence"],
                         [{"view": "mod-defs", "id": 1}])
        editor.save_views(str(self.directory), configs)
        report = contract.report(self.directory)
        self.assertTrue(report["ok"], report["errors"])
        self.assertIn("Extra", [item["name"] for item in report["types"]])

    def test_draft_rejects_evidence_without_contract(self):
        spec = {
            "view": {"id": "contract-extra", "name": "额外契约",
                     "description": "额外类型。", "kind": "contract"},
            "blocks": [{
                "key": "job", "name": "Extra", "description": "额外类型。",
                "evidence": [{"view": "mod-defs", "id": 1}],
            }],
        }
        with self.assertRaisesRegex(ValueError, "必须和 contract 一起使用"):
            draft.compile_drafts(str(self.directory), [spec])


if __name__ == "__main__":
    unittest.main()
