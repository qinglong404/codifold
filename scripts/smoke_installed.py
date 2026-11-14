"""Run with the installed wheel's Python, from outside the source checkout."""
from __future__ import annotations

import json
from importlib.metadata import version
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    import codifold
    from codifold import block_config, checks, mcp_server
    from codifold.paths import RESOURCE_ROOT

    assert RESOURCE_ROOT.name == "_resources", RESOURCE_ROOT
    assert version("codifold") == codifold.__version__
    assert block_config.load()["codes"], "default example/code missing"
    for example in ("gradebook-chain", "taskflow"):
        report = checks.report(str(RESOURCE_ROOT / "examples" / example), strict=True)
        assert report["ok"], report["errors"] + report["warnings"]
    command = Path(sys.executable).parent / ("codifold.exe" if os.name == "nt" else "codifold")
    version_output = subprocess.check_output([str(command), "--version"], text=True)
    assert codifold.__version__ in version_output, version_output

    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": mcp_server.DEFAULT_PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "installed-smoke", "version": "1"},
    }}]
    for index, resource in enumerate(mcp_server.RESOURCES, 2):
        messages.append({"jsonrpc": "2.0", "id": index, "method": "resources/read",
                         "params": {"uri": resource["uri"]}})
    result = subprocess.run(
        [sys.executable, "-B", "-m", "codifold.mcp_server"],
        input="\n".join(json.dumps(item) for item in messages) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == len(messages), result.stdout
    assert all("result" in reply for reply in replies), replies
    assert replies[0]["result"]["serverInfo"]["version"] == codifold.__version__
    assert all(reply["result"]["contents"][0]["text"] for reply in replies[1:])

    with tempfile.TemporaryDirectory() as temporary:
        environment = {**os.environ, "CODIFOLD_STATE_DIR": str(Path(temporary) / "state")}
        with (Path(temporary) / "server.log").open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(command), "serve", "--port", "0"], stdout=log, stderr=log,
                env=environment,
            )
            try:
                deadline = time.monotonic() + 10
                match = None
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"http://127\.0\.0\.1:\d+/", output)
                    if match or process.poll() is not None:
                        break
                    time.sleep(0.05)
                assert match, output
                url = match.group(0)
                with urlopen(url, timeout=5) as response:
                    page = response.read().decode("utf-8")
                asset = re.search(r'(?:src|href)="(/assets/[^\"]+)"', page)
                assert asset, page
                with urlopen(url.rstrip("/") + asset.group(1), timeout=5) as response:
                    assert response.status == 200
                with urlopen(url + "api/workspaces", timeout=5) as response:
                    examples = json.load(response)["examples"]
                assert len(examples) == 3, examples
                example = next(item for item in examples if item["entry"] == "main")
                query = urlencode({"path": example["path"], "view": example["entry"]})
                with urlopen(url + "api/blocks-config?" + query, timeout=5) as response:
                    assert json.load(response)["codes"]
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print(f"Installed Codifold {codifold.__version__}: CLI, HTTP, assets, examples and MCP guides OK")


if __name__ == "__main__":
    main()
