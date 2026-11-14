import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config


SOURCE = "\n".join(f"line {number}" for number in range(1, 21)) + "\n"  # 20 行


def write_manifest(directory: Path, files=("student.py",), root=".", entry=None):
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": root},
        "files": list(files),
        "views": {"suffix": ".blocks.json"},
    }
    if entry:
        manifest["views"]["entry"] = entry
    (directory / "codifold.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def write_config(directory: Path, config, manifest=True) -> str:
    (directory / "student.py").write_text(SOURCE, encoding="utf-8")
    if manifest:
        write_manifest(directory)
    project = config.get("project", {})
    view = config.get("view") or {
        "id": project.get("view_id", "main"),
        "name": project.get("title", "视图"),
        "description": project.get("summary") or "描述",
    }
    target = directory / "main.blocks.json"
    target.write_text(json.dumps({"view": view, "blocks": config["blocks"]},
                                 ensure_ascii=False), encoding="utf-8")
    return str(target)


def normal(ident=1, mapping=None, **extra):
    result = {"id": ident, "type": "normal", "name": "块", "description": "描述"}
    if mapping is not None:
        result["code_mapping"] = mapping
    result.update(extra)
    return result


def branch(ident=3, select="single", steps=None, **extra):
    result = {"id": ident, "type": "branch", "name": "分支", "description": "描述",
              "select": select, "branches": [{"steps": steps or [normal(ident + 1)]}]}
    result.update(extra)
    return result


def try_branch(ident=2, branches=None, finally_steps=None, **extra):
    result = {"id": ident, "type": "branch", "kind": "try", "select": "single",
              "name": "try", "description": "描述",
              "branches": branches or [{"role": "body", "steps": [normal(ident + 1)]}]}
    if finally_steps is not None:
        result["finally"] = finally_steps
    result.update(extra)
    return result


class BlockConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def load(self, config):
        return block_config.load(write_config(self.directory, config))

    def test_default_config_loads_with_resolved_code(self):
        data = block_config.load()
        self.assertEqual(data["source"]["kind"], "default")
        self.assertEqual(data["order"], [1, 2, 3, 14, 15])
        self.assertEqual(len(data["config"]["blocks"]), 5)
        block = data["config"]["blocks"][2]
        self.assertEqual(block["type"], "branch")
        self.assertEqual(block["select"], "single")
        self.assertEqual(len(block["branches"]), 6)
        self.assertEqual([step["id"] for step in block["branches"][0]["steps"]], [4, 5, 6])
        self.assertEqual(block["branches"][5]["steps"][0]["next"], 15)
        self.assertEqual(data["config"]["blocks"][3]["next"], 2)
        self.assertIn("1", data["codes"])
        self.assertEqual(data["codes"]["15"]["ranges"][0]["start"], 106)

    def test_order_follows_top_level_array_order(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(9), normal(2), normal(5),
        ]})
        self.assertEqual(data["order"], [9, 2, 5])

    def test_lines_accept_numbers_and_ranges_in_written_order(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(mapping={"file": "student.py", "lines": [1, 2, "6-9"]}),
        ]})
        code = data["codes"]["1"]
        self.assertEqual([(span["start"], span["end"]) for span in code["ranges"]],
                         [(1, 1), (2, 2), (6, 9)])
        self.assertEqual(code["ranges"][2]["lines"][0]["text"], "line 6")
        self.assertEqual(data["config"]["blocks"][0]["code_mapping"]["lines"], [1, 2, "6-9"])

    def test_line_spec_rejects_bad_values(self):
        for lines in ([], [0], [-2], ["9-6"], ["6-"], [1.5], ["x"], [True], "6-9"):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [
                    normal(mapping={"file": "student.py", "lines": lines})]})

    def test_ids_are_globally_unique_across_nested_blocks(self):
        nested = branch(3, steps=[branch(4, steps=[normal(5)])])
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [normal(1), nested, normal(5)]})

    def test_type_is_required_and_restricted(self):
        for kind in (None, "other"):
            item = normal()
            item.pop("type")
            if kind:
                item["type"] = kind
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [item]})

    def test_branch_requires_select_and_branches(self):
        for broken in ({"select": "single", "branches": []},
                       {"select": "single", "branches": [{"steps": []}]},
                       {"select": "both", "branches": [{"steps": [normal(4)]}]},
                       {"branches": [{"steps": [normal(4)]}]},
                       {"select": "single"}):
            item = {"id": 3, "type": "branch", "name": "分支", "description": "描述", **broken}
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [normal(1), item]})

    def test_branch_may_carry_code_but_not_next(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            branch(3, code_mapping={"file": "student.py", "lines": [1]})]})
        self.assertIn("3", data["codes"])
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                branch(3, next=1), normal(1)]})

    def test_normal_must_not_carry_branch_fields(self):
        for extra in ({"select": "single"}, {"branches": [{"steps": [normal(4)]}]}):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [normal(1, **extra)]})

    def test_conditions_are_kept_per_list(self):
        item = {"id": 3, "type": "branch", "name": "分支", "description": "描述",
                "select": "single",
                "branches": [
                    {"condition": "输入 1", "steps": [normal(4)]},
                    {"steps": [normal(5)]},
                ]}
        data = self.load({"project": {"title": "T"}, "blocks": [item]})
        lists = data["config"]["blocks"][0]["branches"]
        self.assertEqual(lists[0]["condition"], "输入 1")
        self.assertNotIn("condition", lists[1])

    def test_next_must_reference_an_existing_id(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1), normal(2, next=1),
        ]})
        self.assertEqual(data["config"]["blocks"][1]["next"], 1)
        for bad in (9, 0, "1", True):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [
                    normal(1), normal(2, next=bad)]})
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [normal(1, next=1)]})

    def test_next_null_is_terminal_and_preserved(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1), normal(2, next=None),
        ]})
        blocks = data["config"]["blocks"]
        self.assertNotIn("next", blocks[0])
        self.assertIn("next", blocks[1])
        self.assertIsNone(blocks[1]["next"])

    def test_branch_rejects_next_null(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [branch(3, next=None)]})

    def test_jump_is_shared_and_preserved(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1), branch(3, jump={"id": 1}),
        ]})
        self.assertEqual(data["config"]["blocks"][1]["jump"], {"id": 1})

    def test_jump_target_must_exist_in_same_view(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [normal(1, jump={"id": 9})]})

    def test_jump_requires_positive_id(self):
        for bad in (0, "2", True, None):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [
                    normal(1), normal(2, jump={"id": bad})]})
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [normal(1, jump={})]})

    def test_jump_and_next_can_coexist(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1, next=2, jump={"id": 2}), normal(2),
        ]})
        block = data["config"]["blocks"][0]
        self.assertEqual(block["next"], 2)
        self.assertEqual(block["jump"], {"id": 2})

    def test_single_file_rejects_cross_view_jump(self):
        with self.assertRaises(ValueError) as error:
            self.load({"project": {"title": "T"}, "blocks": [
                normal(1, jump={"view": "other", "id": 1})]})
        self.assertIn("文件夹项目", str(error.exception))

    def test_on_is_kept_on_first_block(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1, on="device.click"), normal(2),
        ]})
        self.assertEqual(data["config"]["blocks"][0]["on"], "device.click")

    def test_on_is_rejected_outside_first_block(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [normal(1), normal(2, on="x")]})

    def test_on_is_rejected_in_nested_steps(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                branch(3, steps=[normal(4, on="x")])]})

    def test_view_semantics_is_optional_and_validated(self):
        base = {"id": "main", "name": "视图", "description": "描述"}
        checked = block_config.validate(
            {"view": {**base, "semantics": "router"}, "blocks": [normal(1)]})
        self.assertEqual(checked["view"]["semantics"], "router")
        self.assertNotIn("semantics", block_config.validate(
            {"view": base, "blocks": [normal(1)]})["view"])
        with self.assertRaises(ValueError):
            block_config.validate(
                {"view": {**base, "semantics": "chain"}, "blocks": [normal(1)]})

    def test_emit_is_kept_on_normal_block(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            normal(1, on="click"), normal(2, emit=[{"id": 1}]),
        ]})
        self.assertEqual(data["config"]["blocks"][1]["emit"], [{"id": 1}])

    def test_branch_rejects_emit(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                branch(3, emit=[{"id": 4}])]})

    def test_emit_requires_valid_targets(self):
        for bad in ([], "x", [{}], [{"id": 0}], [{"id": 1, "view": "Bad ID"}]):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [
                    normal(1, on="click"), normal(2, emit=bad)]})

    def test_emit_target_must_exist_in_same_view(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                normal(1, on="click"), normal(2, emit=[{"id": 9}])]})

    def test_emit_target_must_be_event_entry(self):
        with self.assertRaises(ValueError) as error:
            self.load({"project": {"title": "T"}, "blocks": [
                normal(1), normal(2, emit=[{"id": 1}])]})
        self.assertIn("不是事件入口", str(error.exception))

    def test_single_file_rejects_cross_view_emit(self):
        with self.assertRaises(ValueError) as error:
            self.load({"project": {"title": "T"}, "blocks": [
                normal(1, on="click"), normal(2, emit=[{"view": "other", "id": 1}])]})
        self.assertIn("文件夹项目", str(error.exception))

    def test_try_structure_is_preserved(self):
        item = try_branch(branches=[
            {"role": "body", "steps": [normal(3), normal(4)]},
            {"role": "except", "condition": "ValueError", "steps": [normal(5)]},
        ], finally_steps=[normal(6)])
        data = self.load({"project": {"title": "T"}, "blocks": [item]})
        block = data["config"]["blocks"][0]
        self.assertEqual(block["kind"], "try")
        self.assertEqual([item["role"] for item in block["branches"]], ["body", "except"])
        self.assertEqual(block["branches"][1]["condition"], "ValueError")
        self.assertEqual([step["id"] for step in block["finally"]], [6])

    def test_try_allows_finally_without_except(self):
        data = self.load({"project": {"title": "T"}, "blocks": [
            try_branch(finally_steps=[normal(4)])]})
        self.assertEqual(len(data["config"]["blocks"][0]["branches"]), 1)

    def test_try_requires_single_select(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                try_branch(select="multi", finally_steps=[normal(4)])]})

    def test_try_body_must_be_first_and_unique(self):
        cases = [
            [{"role": "except", "steps": [normal(3)]}, {"role": "body", "steps": [normal(4)]}],
            [{"role": "body", "steps": [normal(3)]}, {"role": "body", "steps": [normal(4)]}],
            [{"role": "except", "steps": [normal(3)]}],
        ]
        for branches in cases:
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [try_branch(branches=branches)]})

    def test_try_requires_roles_on_every_list(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                try_branch(branches=[{"steps": [normal(3)]}], finally_steps=[normal(4)])]})

    def test_try_body_rejects_condition(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                try_branch(branches=[{"role": "body", "condition": "x", "steps": [normal(3)]}],
                           finally_steps=[normal(4)])]})

    def test_try_requires_except_or_finally(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                try_branch(branches=[{"role": "body", "steps": [normal(3)]}])]})

    def test_try_finally_must_be_non_empty(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [try_branch(finally_steps=[])]})

    def test_non_try_branch_rejects_role_and_finally(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                branch(3, branches=[{"role": "body", "steps": [normal(4)]}])]})
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                branch(3, **{"finally": [normal(4)]})]})

    def test_normal_rejects_kind_and_finally(self):
        for extra in ({"kind": "try"}, {"finally": [normal(2)]}):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [normal(1, **extra)]})

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [branch(3, kind="loop")]})

    def test_try_finally_blocks_participate_in_validation(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                try_branch(branches=[{"role": "body", "steps": [normal(3)]}],
                           finally_steps=[normal(3)])]})
        data = self.load({"project": {"title": "T"}, "blocks": [
            try_branch(branches=[{"role": "body", "steps": [normal(3)]}],
                       finally_steps=[normal(4, mapping={"file": "student.py", "lines": [1]})])]})
        self.assertIn("4", data["codes"])
        data = self.load({"project": {"title": "T"}, "blocks": [
            try_branch(branches=[{"role": "body", "steps": [normal(3, jump={"id": 4})]}],
                       finally_steps=[normal(4)])]})
        self.assertEqual(data["config"]["blocks"][0]["branches"][0]["steps"][0]["jump"]["id"], 4)

    def test_nested_branch_is_supported(self):
        item = branch(3, steps=[
            branch(4, select="multi", steps=[normal(5), normal(6, next=5)]),
            normal(7),
        ])
        data = self.load({"project": {"title": "T"}, "blocks": [item]})
        nested = data["config"]["blocks"][0]["branches"][0]["steps"][0]
        self.assertEqual(nested["type"], "branch")
        self.assertEqual(nested["branches"][0]["steps"][1]["next"], 5)

    def test_code_file_must_stay_inside_config_directory(self):
        for file in ("../run.py", "/etc/passwd", "a/../../b.py"):
            with self.assertRaises(ValueError):
                self.load({"project": {"title": "T"}, "blocks": [
                    normal(mapping={"file": file, "lines": [1]})]})

    def test_code_mapping_requires_manifest(self):
        target = write_config(self.directory, {"project": {"title": "T"}, "blocks": [
            normal(mapping={"file": "student.py", "lines": [1]})]}, manifest=False)
        with self.assertRaises(ValueError) as error:
            block_config.load(target)
        self.assertIn("codifold.json", str(error.exception))

    def test_code_mapping_file_must_be_declared(self):
        with self.assertRaises(ValueError) as error:
            self.load({"project": {"title": "T"}, "blocks": [
                normal(mapping={"file": "other.py", "lines": [1]})]})
        self.assertIn("未在 codifold.json 中声明", str(error.exception))

    def test_missing_code_file_and_overflow_are_rejected(self):
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                normal(mapping={"file": "missing.py", "lines": [1]})]})
        target = write_config(self.directory, {"project": {"title": "T"}, "blocks": [
            normal(mapping={"file": "missing.py", "lines": [1]})]})
        write_manifest(self.directory, files=("missing.py",))
        with self.assertRaises(FileNotFoundError):
            block_config.load(target)
        with self.assertRaises(ValueError):
            self.load({"project": {"title": "T"}, "blocks": [
                normal(mapping={"file": "student.py", "lines": [21]})]})


if __name__ == "__main__":
    unittest.main()
