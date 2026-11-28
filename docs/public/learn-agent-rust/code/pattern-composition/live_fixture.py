"""Loopback OpenAI-compatible fixture for `cargo run --locked -- live`.

Usage: python3 live_fixture.py -- cargo run --locked -- live
Starts a chat/completions server on 127.0.0.1, points OPENAI_BASE_URL/OPENAI_MODEL at it,
runs the command, then prints what the server received. It answers by the 角色 marker in the
system messages, the same rules as the Rust stand-in model; it checks wiring, not model quality.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECEIVED = []


def text_of(message):
    content = message.get("content")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def answer(body):
    messages = body["messages"]
    system = "\n".join(text_of(m) for m in messages if m["role"] in ("system", "developer"))
    role = system.split("角色：")[1].split()[0] if "角色：" in system else "?"
    RECEIVED.append(role)
    if role.endswith("_checker"):
        member = role[: -len("_checker")]
        finding = "tokio 需要升到 1.40" if member == "deps" else "启动命令改成 serve"
        return {"content": json.dumps({"member": member, "revision": "r2", "finding": finding}, ensure_ascii=False)}
    if role == "writer":
        sources = ["deps", "docs"] if '"failed"' in system else []
        return {"content": json.dumps({"text": "升级到 3.0：tokio 升到 1.40，启动命令改成 serve。", "sources": sources},
                                      ensure_ascii=False)}
    if messages[-1]["role"] == "tool":
        return {"content": "已发布。"}
    draft = json.loads(system.split("定稿：")[1].splitlines()[0])
    arguments = json.dumps({"target": "releases/3.0.md", "content": draft["text"]}, ensure_ascii=False)
    return {"content": None, "tool_calls": [{"id": "call_publish", "type": "function",
                                             "function": {"name": "publish_report", "arguments": arguments}}]}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or body.get("stream"):
            self.send_error(400, "fixture expects non-streaming /v1/chat/completions")
            return
        message = {"role": "assistant", **answer(body)}
        reply = {"id": f"fixture-{len(RECEIVED)}", "object": "chat.completion", "created": 0,
                 "model": body["model"],
                 "choices": [{"index": 0, "message": message,
                              "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        data = json.dumps(reply, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    command = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ, OPENAI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
               OPENAI_MODEL="fixture-model", OPENAI_API_KEY="fixture-key")
    result = subprocess.run(command, env=env)
    server.shutdown()
    print("fixture: requests=" + str(len(RECEIVED)) + " roles=[" + ",".join(sorted(RECEIVED)) + "]")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
