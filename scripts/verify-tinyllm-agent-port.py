"""Check that the Python agent in TinyLLM ch44 behaves like the Rust agent of learn-agent-rust P03.

Runs the `run_agent` / `parse_response` / `over_http` regions of
docs/public/tinyllm/code/llm-agent-interaction.py against the loopback fixture of
docs/public/learn-agent-rust/code/model-evaluation/lab.py, for every scenario in its
PROTOCOL table, and compares (stop reason, file reads, HTTP requests) with the
outcome the Rust program is expected to produce. Needs only the standard library.

Usage: python scripts/verify-tinyllm-agent-port.py
"""

import importlib.util
import json
import re
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/public/tinyllm/code/llm-agent-interaction.py"
LAB = ROOT / "docs/public/learn-agent-rust/code/model-evaluation/lab.py"


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    namespace = {"json": json, "socket": socket, "urllib": urllib, "BaseHTTPRequestHandler": BaseHTTPRequestHandler,
                 "chat_completions": None}
    for name in ("protocol", "agent", "http"):
        code = re.search(rf"# region {name}\n(.*?)# endregion {name}\n", source, re.S).group(1)
        exec(compile(code, f"{SCRIPT.name}#{name}", "exec"), namespace)
    spec = importlib.util.spec_from_file_location("p03_lab", LAB)
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    case = json.loads((LAB.parent / "cases.json").read_text())["cases"][0]
    server = lab.Fixture()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    failures = 0
    try:
        for mode, (_, stop, reads, requests) in lab.PROTOCOL.items():
            url = f"http://127.0.0.1:{server.server_port}/fixture/{mode}"
            s = namespace["run_agent"](namespace["over_http"](url), case["readme"])
            got = (s["stop"], s["reads"], s["attempts"])
            ok = got == (stop, reads, requests)
            failures += not ok
            print(f"{'ok ' if ok else 'BAD'} {mode:15} 停止 {got[0]:22} 读 {got[1]}  请求 {got[2]}"
                  + ("" if ok else f"   Rust 预期 {stop} / {reads} / {requests}"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(f"{len(lab.PROTOCOL) - failures}/{len(lab.PROTOCOL)} 个场景与 Rust 版的预期一致")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
