"""Run the local Codifold reader."""
import argparse
import sys
from pathlib import Path

from codifold.server import create_server

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Codifold 中文流程阅读器")
    parser.add_argument("--port", type=int, default=5190)
    args = parser.parse_args()
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("前端尚未构建：请在 frontend 目录运行 npm ci 和 npm run build。")
        return 1
    try:
        server = create_server(args.port)
    except OSError as error:
        print(f"无法启动：{error}")
        return 1
    print(f"Codifold: http://127.0.0.1:{args.port}/", flush=True)
    print("本机运行 · 读取与编辑 JSON · 不执行被讲解的项目 · Ctrl+C 停止", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
