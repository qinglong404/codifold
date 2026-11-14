"""Regressions for concurrent writers, incomplete drafts and rollback."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from codifold import block_config, checks, editor
from codifold.locking import resource_lock

ROOT = Path(__file__).resolve().parent.parent


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "CODIFOLD_STATE_DIR": str(self.base / "state"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.workspace = self.base / "workspace"
        editor.create_workspace(str(self.workspace), "测试", "测试项目")

    def test_another_process_waits_then_rejects_its_stale_revision(self):
        loaded = block_config.load(str(self.workspace), "main")
        ready = self.base / "ready"
        script = '''
import copy, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from codifold import block_config, editor
workspace, revision, ready = sys.argv[2:]
config = block_config.load(workspace, 'main')['config']
config['blocks'][0]['name'] = 'stale child'
Path(ready).touch()
try:
    editor.save_view(workspace, config, revision=revision)
    print('unexpected success', flush=True)
except editor.RevisionConflict:
    print('revision conflict', flush=True)
'''
        child = None
        try:
            with resource_lock("workspace:" + str(self.workspace.resolve())):
                child = subprocess.Popen(
                    [sys.executable, "-B", "-c", script, str(ROOT),
                     str(self.workspace), loaded["revision"], str(ready)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding="utf-8",
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "child did not reach the write")
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.2)
                config = copy.deepcopy(loaded["config"])
                config["blocks"][0]["name"] = "new parent"
                editor.save_view(str(self.workspace), config, revision=loaded["revision"])
            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "revision conflict")
            final = block_config.load(str(self.workspace), "main")
            self.assertEqual(final["config"]["blocks"][0]["name"], "new parent")
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)

    def test_disconnected_view_can_be_saved_as_draft_but_strict_apply_rolls_back(self):
        config = {"view": {"id": "fn-draft", "name": "细节", "description": "未接通", "kind": "function"},
                  "blocks": [{"id": 1, "type": "normal", "name": "草稿", "description": "待接通"}]}
        result = editor.save_view(str(self.workspace), config)
        self.assertTrue(any("连贯性" in item for item in result["warnings"]))
        self.assertFalse(checks.report(str(self.workspace), strict=True)["ok"])
        target = self.workspace / "fn-draft.blocks.json"
        previous = target.read_bytes()
        config["blocks"][0]["name"] = "changed"
        with self.assertRaisesRegex(ValueError, "连贯性"):
            editor.save_views(str(self.workspace), [config], strict=True)
        self.assertEqual(target.read_bytes(), previous)

    def test_invalid_contract_rolls_back_for_single_and_batch_save(self):
        config = {"view": {"id": "contract-api", "name": "类型", "description": "重复", "kind": "contract"},
                  "blocks": [{"id": index, "type": "normal", "name": "Job", "description": "类型",
                              "contract": {"kind": "type", "fields": [{"name": "id", "type": "int"}]}}
                             for index in (1, 2)]}
        before = (self.workspace / "main.blocks.json").read_bytes()
        for save in (editor.save_view, lambda path, item: editor.save_views(path, [item])):
            with self.subTest(save=save):
                with self.assertRaisesRegex(ValueError, "类型名重复"):
                    save(str(self.workspace), config)
                self.assertFalse((self.workspace / "contract-api.blocks.json").exists())
                self.assertEqual((self.workspace / "main.blocks.json").read_bytes(), before)
        # The failed transaction released its lock and normal editing still works.
        loaded = block_config.load(str(self.workspace), "main")
        editor.save_view(str(self.workspace), loaded["config"], revision=loaded["revision"])
