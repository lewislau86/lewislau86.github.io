"""Regenerate the mini-redis tutorial figures (pure Python, no third-party packages).

Run from any directory: python scripts/generate-mini-redis-figures.py
All figures are hand-built SVG written to docs/public/mini-redis/figures/; text stays
selectable. Each figure replaces a former ASCII diagram in docs/mini-redis/.
"""

from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/mini-redis/figures"
BLUE = "#2563eb"
TEAL = "#0f766e"
ORANGE = "#b45309"
RED = "#b91c1c"
PURPLE = "#7c3aed"
GRAY = "#64748b"
INK = "#172033"
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'
MONO = '"Cascadia Mono", "SFMono-Regular", Menlo, Consolas, monospace'
FILL = {BLUE: "#eff6ff", TEAL: "#ecfdf5", ORANGE: "#fffbeb", RED: "#fef2f2", PURPLE: "#f5f3ff", GRAY: "#f8fafc", INK: "#ffffff"}


# ---------- 基础工具（与 TinyLLM、Burn 配图脚本同一风格） ----------

def svg(name, title, description, height, body, width=960):
    markers = "".join(
        f'<marker id="arrow-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{c}"/></marker>'
        for c in (BLUE, TEAL, ORANGE, RED, PURPLE, GRAY, INK))
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs>{markers}</defs>
<rect width="{width}" height="{height}" rx="16" fill="#f8fafc"/>
<g font-family='{FONT}' fill="{INK}" text-anchor="middle">{body}</g></svg>'''
    ET.fromstring(document)
    (OUT / name).write_text(document + "\n", encoding="utf-8")


def text(x, y, value, size=18, color=INK, weight="normal", anchor="middle", mono=False):
    size = max(size, 14)  # 正文栏约 690px 宽，960 宽的图会缩小约 0.7 倍，太小的字看不清
    # 等宽字体多数不含中文，只给纯 ASCII 文本使用
    family = f' font-family=\'{MONO}\'' if mono and value.isascii() else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{family}>{escape(value)}</text>')


def box(x, y, w, h, color=GRAY, fill=None, dash=False, width=2, rx=10):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    fill = fill or FILL.get(color, "#ffffff")
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{color}" stroke-width="{width}"{extra}/>'


def node(x, y, w, h, label, sub=None, color=GRAY, mono=True, size=17):
    """带标题和可选说明的方框；x, y 为左上角。"""
    out = box(x, y, w, h, color, "#ffffff" if color == GRAY else None)
    if sub:
        out += text(x + w / 2, y + h / 2 - 3, label, size, INK, "bold", mono=mono)
        out += text(x + w / 2, y + h / 2 + 18, sub, 13.5, GRAY)
    else:
        out += text(x + w / 2, y + h / 2 + 6, label, size, INK, "bold", mono=mono)
    return out


def line(d, color=GRAY, width=2.5, dash=False, arrow=True):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    mark = f' marker-end="url(#arrow-{color[1:]})"' if arrow else ""
    return f'<path d="{d}" stroke="{color}" stroke-width="{width}" fill="none"{mark}{extra}/>'


def arrow(x1, y1, x2, y2, color=GRAY, width=2.5, dash=False):
    return line(f"M{x1} {y1}L{x2} {y2}", color, width, dash)


def badge(x, y, n, color=BLUE):
    return (f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>'
            + text(x, y + 5, str(n), 14, "#ffffff", "bold"))


def title(value, y=40):
    return text(480, y, value, 23, INK, "bold")


# ---------- 第 0 章 ----------

def tcp_connect():
    body = title("两端各自准备 socket，合在一起才是一条 TCP 连接")
    server = [("bind", "监听地址"), ("取 permit", "连接配额"), ("accept", "等待新连接"), ("socket", "已连接"), ("Handler", "包装连接"), ("spawn", "独立任务")]
    client = [("服务器地址", "host:port"), ("connect", "发起握手"), ("socket", "已连接"), ("Connection", "读写帧"), ("Client", "命令 API")]
    body += text(40, 92, "服务端", 18, TEAL, "bold", "start")
    xs = [40, 190, 340, 490, 640, 790]
    for i, (a, b) in enumerate(server):
        body += node(xs[i], 105, 130, 62, a, b, TEAL if a == "socket" else GRAY)
        if i:
            body += arrow(xs[i - 1] + 130, 136, xs[i] - 4, 136)
    body += text(40, 342, "客户端", 18, BLUE, "bold", "start")
    cxs = [190, 340, 490, 640, 790]
    for i, (a, b) in enumerate(client):
        body += node(cxs[i], 355, 130, 62, a, b, BLUE if a == "socket" else GRAY)
        if i:
            body += arrow(cxs[i - 1] + 130, 386, cxs[i] - 4, 386)
    body += line("M555 170 V350", ORANGE, 4, arrow=False)
    body += line("M555 176 V170", ORANGE, 4) + line("M555 344 V350", ORANGE, 4)
    body += box(585, 226, 300, 64, ORANGE)
    body += text(735, 252, "一条 TCP 连接", 18, ORANGE, "bold")
    body += text(735, 277, "操作系统负责握手与字节传输", 14.5, GRAY)
    body += text(480, 460, "服务端从 accept 拿到 socket 后交给 Handler；客户端从 connect 拿到 socket 后交给 Connection。", 16, GRAY)
    svg("tcp-connect.svg", "TCP 连接的建立",
        "服务端依次 bind、取连接配额、accept 得到 socket，再包装为 Handler 并 spawn；客户端 connect 得到 socket，再包装为 Connection 和 Client。两端的 socket 共同构成一条 TCP 连接。", 490, body)


def shared_state():
    body = title("多个任务各持一个 Db 句柄，指向同一份 Shared")
    holders = [("Handler A 的 Db", 110), ("Handler B 的 Db", 200), ("后台清理任务", 290)]
    for label, y in holders:
        body += node(40, y, 220, 58, label, None, BLUE if "Handler" in label else PURPLE, mono=False)
        body += arrow(262, y + 29, 340, 214, GRAY)
    body += text(300, 150, "Arc 克隆", 14, GRAY)
    body += box(345, 80, 575, 330, TEAL)
    body += text(370, 110, "Shared（只有一份）", 19, TEAL, "bold", "start")
    body += box(370, 125, 380, 265, ORANGE, "#ffffff")
    body += text(390, 152, "Mutex<State>", 16, ORANGE, "bold", "start", mono=True)
    body += text(520, 152, "读写前先加锁", 15, ORANGE, "bold", "start")
    rows = [("entries", "key → Bytes 与可选到期时刻", "第 6 章"),
            ("expirations", "按时间排序的 (到期时刻, key)", "第 7 章"),
            ("pub_sub", "频道名 → broadcast Sender", "第 8 章"),
            ("shutdown", "后台任务停止标记", "第 10 章")]
    for i, (k, v, c) in enumerate(rows):
        y = 170 + i * 52
        body += box(390, y, 340, 42, GRAY, "#f8fafc", rx=8, width=1.5)
        body += text(405, y + 27, k, 15.5, INK, "bold", "start", mono=True)
        body += text(530, y + 27, v, 13.5, GRAY, anchor="start")
    body += node(770, 200, 130, 96, "Notify", "提醒清理任务", PURPLE)
    body += text(835, 330, "不在锁里", 13, GRAY)
    body += text(480, 448, "克隆 Db 只复制 Arc 指针；所有连接读写的是同一张表，修改需要先拿到 Mutex。", 16, GRAY)
    svg("shared-state.svg", "Db 与共享状态的结构",
        "Handler A、Handler B 和后台清理任务各持有一个 Db，它们通过 Arc 指向同一份 Shared。Shared 内的 Mutex 保护 State，State 包含 entries、expirations、pub_sub 和 shutdown 四项；Notify 位于锁外，用来提醒清理任务。", 475, body)


def pubsub_flow():
    body = title("两条 TCP 连接、两个 Handler，由进程内 broadcast 接起来")
    body += node(30, 110, 190, 62, "订阅客户端", "Client::subscribe", BLUE, mono=False)
    body += node(30, 330, 190, 62, "发布客户端", "Client::publish", ORANGE, mono=False)
    body += node(410, 110, 220, 62, "订阅 Handler", "Subscribe::apply 长期循环", BLUE, mono=False)
    body += node(410, 330, 220, 62, "发布 Handler", "Publish::apply", ORANGE, mono=False)
    body += node(740, 210, 195, 82, "Db：pub_sub", "频道 news → broadcast", TEAL, mono=False)
    body += arrow(222, 130, 406, 130, BLUE) + text(258, 121, "SUBSCRIBE news", 13.5, BLUE, anchor="start", mono=True) + badge(240, 116, 1, BLUE)
    body += line("M632 141 C690 141 700 200 736 225", BLUE) + text(690, 160, "取得 Receiver", 13, BLUE, anchor="start")
    body += arrow(222, 350, 406, 350, ORANGE) + text(258, 341, "PUBLISH news hello", 13.5, ORANGE, anchor="start", mono=True) + badge(240, 336, 2, ORANGE)
    body += line("M632 361 C690 361 700 300 736 280", ORANGE) + text(690, 352, "Sender.send", 13, ORANGE, anchor="start", mono=True)
    body += line("M736 245 C680 220 660 190 634 168", TEAL, 2.5, dash=True) + text(652, 215, "消息进入 Receiver", 13, TEAL, anchor="end")
    body += arrow(406, 160, 222, 160, BLUE) + text(258, 185, "message 帧（主动推送）", 13, BLUE, anchor="start") + badge(240, 180, 3, BLUE)
    body += arrow(406, 380, 222, 380, ORANGE) + text(258, 405, "Integer：接收者数", 13, ORANGE, anchor="start") + badge(240, 400, 4, ORANGE)
    body += text(480, 450, "①② 都是 TCP 上的请求；broadcast 只在服务端进程内传递；③ 是订阅连接上的推送，④ 才是 PUBLISH 自己的响应。", 15, GRAY)
    svg("pubsub-flow.svg", "发布订阅的消息路径",
        "订阅客户端发送 SUBSCRIBE，订阅 Handler 从 Db 取得 broadcast Receiver 并长期等待；发布客户端发送 PUBLISH，发布 Handler 调用 Sender.send；消息经进程内 broadcast 到达订阅 Handler，后者向订阅客户端推送 message 帧；发布 Handler 向发布客户端返回接收者数。", 480, body)


# ---------- 第 3 章 ----------

def set_request_path():
    body = title("一次 SET：同一任务内是函数调用，跨进程只有字节")
    body += box(30, 70, 300, 520, BLUE, "#ffffff", dash=True)
    body += text(180, 98, "客户端进程 · 调用任务", 16, BLUE, "bold")
    body += box(630, 70, 300, 520, TEAL, "#ffffff", dash=True)
    body += text(780, 98, "服务端进程 · 此连接的 Handler 任务", 16, TEAL, "bold")
    left = ["Client::set", "set_cmd", "Set::into_frame", "Connection::write_frame"]
    for i, s in enumerate(left):
        y = 120 + i * 62
        body += node(60, y, 240, 44, s, color=BLUE, size=15)
        if i:
            body += arrow(180, y - 18, 180, y - 2, BLUE)
    right = ["Connection::read_frame", "Command::from_frame", "Set::parse_frames", "Command::apply", "Set::apply → Db::set", "Connection::write_frame"]
    for i, s in enumerate(right):
        y = 120 + i * 62
        body += node(660, y, 240, 44, s, color=TEAL, size=15)
        if i:
            body += arrow(780, y - 18, 780, y - 2, TEAL)
    body += box(345, 290, 270, 54, ORANGE)
    body += text(480, 314, "*3 $3 set $6 course $4 rust", 13, ORANGE, "bold", mono=True)
    body += text(480, 334, "RESP 字节", 13, GRAY)
    body += line("M300 328 H345", ORANGE, 3) + line("M615 300 C640 300 630 142 656 142", ORANGE, 3)
    body += node(60, 470, 240, 44, "Client::read_response", color=BLUE, size=15)
    body += node(60, 530, 240, 44, "检查 OK → 继续 GET", color=BLUE, mono=False, size=15)
    body += arrow(180, 514, 180, 528, BLUE)
    body += box(392, 470, 176, 44, ORANGE)
    body += text(480, 498, "+OK\\r\\n", 15, ORANGE, "bold", mono=True)
    body += line("M660 452 C600 452 600 492 570 492", ORANGE, 3) + line("M392 492 H302", ORANGE, 3)
    body += text(480, 618, "蓝、绿框内的箭头都是普通函数调用；橙色箭头是 TCP 上的字节，两边没有共享任何 Rust 对象。", 15, GRAY)
    svg("set-request-path.svg", "SET 请求的完整路径",
        "客户端任务依次调用 Client::set、set_cmd、Set::into_frame、Connection::write_frame，把 RESP 字节写入 TCP；服务端 Handler 任务依次 read_frame、Command::from_frame、Set::parse_frames、Command::apply、Set::apply 和 Db::set，再写回 +OK；客户端 read_response 检查 OK 后继续 GET。", 640, body)


# ---------- 第 4 章 ----------

def resp_bytes():
    body = title("GET course 在网络上的 25 个字节")
    segs = [("*2\\r\\n", 4, "数组：2 个元素", PURPLE), ("$3\\r\\n", 4, "下一项 3 字节", BLUE), ("GET\\r\\n", 5, "第 1 项内容", BLUE),
            ("$6\\r\\n", 4, "下一项 6 字节", TEAL), ("course\\r\\n", 8, "第 2 项内容", TEAL)]
    unit = 34
    x = 55
    for label, n, desc, c in segs:
        w = n * unit
        body += box(x, 100, w, 64, c, rx=6)
        body += text(x + w / 2, 140, label, 18, c, "bold", mono=True)
        body += text(x + w / 2, 192, f"{n} 字节", 13.5, GRAY)
        body += text(x + w / 2, 218, desc, 14.5, INK)
        x += w + 6
    body += line("M55 250 H895", GRAY, 1.5, arrow=False)
    body += text(55, 280, "解析顺序：", 16, INK, "bold", "start")
    body += text(140, 280, "先看首字节类型（* 数组、$ 定长字符串），再按长度取内容，用 \\r\\n 确认边界。", 15.5, INK, anchor="start")
    body += text(55, 312, "长度前缀让解析器不必扫描内容，也能正确处理内容里本身含有 \\r\\n 的值。", 15.5, GRAY, anchor="start")
    svg("resp-bytes.svg", "RESP 帧的字节结构",
        "GET course 编码为 25 字节：*2\\r\\n 表示两元素数组，$3\\r\\n 后跟 GET\\r\\n，$6\\r\\n 后跟 course\\r\\n。类型前缀和长度前缀让解析器知道每一项在哪里结束。", 340, body)


def frame_buffer():
    body = title("read_frame：不完整就保留，完整就只消费一帧")
    unit = 17
    rows = [
        ("第 1 次读取后", [("*2\\r\\n$3\\r\\nGE", 12, GRAY)], "Frame::check → Incomplete：一个字节也不消费，继续 read_buf", ORANGE),
        ("第 2 次追加后", [("*2\\r\\n$3\\r\\nGET\\r\\n$6\\r\\ncourse\\r\\n", 25, TEAL), ("*1\\r\\n$4\\r\\nPING\\r\\n", 14, PURPLE)],
         "check 通过 → parse 出 GET，advance 25 字节", TEAL),
        ("交付 GET 之后", [("*1\\r\\n$4\\r\\nPING\\r\\n", 14, PURPLE)], "下一次 read_frame 直接解析 PING，不必等网络", PURPLE),
    ]
    for i, (label, segs, note, c) in enumerate(rows):
        y = 90 + i * 130
        body += text(40, y + 34, label, 16, INK, "bold", "start")
        x = 170
        for s, n, sc in segs:
            w = n * unit
            body += box(x, y, w, 52, sc, rx=6)
            body += text(x + w / 2, y + 33, s, 12.5, sc, "bold", mono=True)
            x += w + 4
        body += text(170, y + 82, note, 15, c, anchor="start")
    body += text(480, 485, "buffer 是 Connection 自己持有的 BytesMut；TCP 不保留消息边界，边界由 RESP 的长度前缀决定。", 15, GRAY)
    svg("frame-buffer.svg", "读缓冲区中的帧边界",
        "第一次只读到 *2\\r\\n$3\\r\\nGE，判断为不完整并全部保留；第二次追加后缓冲区里有完整的 25 字节 GET 帧和一个 PING 帧，只消费 GET 的 25 字节；剩下的 PING 在下一次 read_frame 时直接解析。", 510, body)


# ---------- 第 5 章 ----------

def server_tasks():
    body = title("一个主流程，一个接入循环，每个连接一个任务")
    body += node(40, 90, 150, 50, "main", color=GRAY, size=16)
    body += node(240, 90, 170, 50, "server::run", color=GRAY, size=16)
    body += arrow(190, 115, 236, 115)
    body += box(460, 70, 460, 92, ORANGE)
    body += text(480, 96, "tokio::select! 同时等待两件事，先完成者胜出", 15, ORANGE, "bold", "start")
    body += node(480, 108, 200, 44, "Listener::run", color=ORANGE, size=15)
    body += node(700, 108, 200, 44, "关闭信号（Ctrl+C）", color=ORANGE, mono=False, size=15)
    body += arrow(410, 115, 456, 115)
    body += line("M580 152 V205", ORANGE, 2.5)
    body += box(380, 210, 400, 56, ORANGE, "#ffffff")
    body += text(580, 244, "loop { acquire → accept → spawn }", 15.5, ORANGE, "bold", mono=True)
    lanes = [("任务 A", 80, BLUE), ("任务 B", 380, TEAL), ("任务 C", 680, PURPLE)]
    for name, x, c in lanes:
        body += line(f"M580 266 C580 300 {x + 100} 290 {x + 100} 322", c, 2.5, dash=True)
        body += box(x, 325, 200, 150, c)
        body += text(x + 100, 352, f"Handler {name[-1]}::run", 15, c, "bold", mono=True)
        body += text(x + 100, 382, "read_frame", 14, INK, mono=True)
        body += text(x + 100, 408, "→ Command::apply", 14, INK, mono=True)
        body += text(x + 100, 434, "→ write_frame", 14, INK, mono=True)
        body += text(x + 100, 460, f"{name}：只服务一个连接", 13, GRAY)
    body += text(792, 236, "spawn：新任务", 13.5, GRAY, anchor="start")
    body += text(480, 512, "一个 Handler 在 .await 上等待某个客户端时，运行时会去推进其他任务，所以服务器能同时服务多人。", 15, GRAY)
    svg("server-tasks.svg", "服务端的任务结构",
        "main 调用 server::run，后者用 select 同时等待 Listener::run 和关闭信号；Listener 循环取得配额、accept 并为每个连接 spawn 一个 Handler 任务，Handler A、B、C 各自循环读帧、执行命令、写回响应。", 540, body)


# ---------- 第 6 章 ----------

def lock_scope():
    body = title("锁只覆盖内存操作，网络等待放在锁外")
    def bar(y, segments, label, c):
        out = text(40, y + 30, label, 16, c, "bold", "start")
        x = 230
        for s, w, fill in segments:
            out += f'<rect x="{x}" y="{y}" width="{w}" height="46" rx="6" fill="{fill}" stroke="#cbd5e1"/>'
            out += text(x + w / 2, y + 29, s, 14.5)
            x += w
        return out
    lock, free, net = "#fde68a", "#ffffff", "#bfdbfe"
    body += bar(90, [("加锁", 80, lock), ("找到值", 90, lock), ("await 网络发送 ……", 330, lock), ("解锁", 80, lock)], "不合适的顺序", RED)
    body += line("M230 150 H810", RED, 3, arrow=False)
    body += text(520, 176, "整段都持锁：其他连接的 GET/SET 只能排队，慢客户端拖住所有人", 15, RED)
    body += bar(225, [("加锁", 80, lock), ("找到值", 90, lock), ("克隆 Bytes 句柄", 140, lock), ("解锁", 80, lock), ("await 网络发送 ……", 280, net)], "本地实际顺序", TEAL)
    body += line("M230 285 H620", TEAL, 3, arrow=False)
    body += text(425, 311, "持锁时间很短", 15, TEAL)
    body += text(760, 311, "等待网络时不占锁", 15, BLUE)
    body += f'<rect x="230" y="350" width="22" height="16" fill="{lock}" stroke="#cbd5e1"/>' + text(262, 364, "持有 Mutex", 14, GRAY, anchor="start")
    body += f'<rect x="380" y="350" width="22" height="16" fill="{net}" stroke="#cbd5e1"/>' + text(412, 364, "等待 TCP", 14, GRAY, anchor="start")
    body += text(480, 410, "Bytes 克隆只增加引用计数，不复制数据；这是“先取出，再离开锁去等”能成立的前提。", 15, GRAY)
    svg("lock-scope.svg", "锁的作用范围",
        "错误做法在持有 Mutex 期间 await 网络发送，其他连接只能等待；mini-redis 的做法是加锁、找到值、克隆 Bytes 句柄后立即解锁，再在锁外 await 网络发送。", 440, body)


# ---------- 第 7 章 ----------

def expiration_tasks():
    body = title("SET 只登记和提醒，真正删除由后台任务完成")
    body += box(30, 75, 900, 105, BLUE, dash=True)
    body += text(50, 100, "连接任务 A", 15, BLUE, "bold", "start")
    steps = ["Set::apply", "Db::set", "更新 entries 与索引", "notify_one", "写回 OK"]
    xs = [50, 225, 400, 600, 775]
    for i, s in enumerate(steps):
        body += node(xs[i], 112, 160, 48, s, color=BLUE, mono=s[0].isascii(), size=14.5)
        if i:
            body += arrow(xs[i - 1] + 160, 136, xs[i] - 4, 136, BLUE)
    body += line("M680 162 C680 215 700 230 692 288", PURPLE, 2.5, dash=True)
    body += text(710, 220, "通知，不是调用", 13.5, PURPLE, anchor="start")
    body += box(160, 250, 640, 170, PURPLE)
    body += text(180, 275, "后台任务 purge_expired_tasks（Db::new 时 spawn），循环：", 14.5, PURPLE, "bold", "start")
    body += node(180, 292, 185, 46, "purge_expired_keys", color=PURPLE, size=13.5)
    body += node(395, 292, 175, 46, "得到下一个 deadline", color=PURPLE, mono=False, size=13.5)
    body += node(600, 292, 185, 46, "sleep_until / notified", color=PURPLE, size=13)
    body += arrow(365, 315, 391, 315, PURPLE) + arrow(570, 315, 596, 315, PURPLE)
    body += line("M692 338 V380 H272 V342", PURPLE, 2.5)
    body += text(482, 400, "醒来后重新读取共享状态", 13, PURPLE)
    body += box(30, 445, 900, 70, TEAL, dash=True)
    body += text(50, 470, "连接任务 B", 15, TEAL, "bold", "start")
    body += node(200, 456, 170, 46, "Get::apply", color=TEAL, size=14.5)
    body += node(400, 456, 170, 46, "Db::get", color=TEAL, size=14.5)
    body += arrow(370, 479, 396, 479, TEAL)
    body += text(590, 485, "看到的是清理之前或之后的 entries", 14, TEAL, anchor="start")
    svg("expiration-tasks.svg", "过期清理涉及的三个任务",
        "连接任务 A 执行 SET 时更新 entries 与过期索引，再用 Notify 提醒后台任务后立即回 OK；后台任务循环执行 purge_expired_keys、计算下一个到期时间并等待 sleep_until 或通知；连接任务 B 的 GET 读到的是清理之前或之后的状态。", 535, body)


def ttl_timeline():
    body = title("覆盖写入会替换过期索引：旧的等待醒来也不会误删")
    body += line("M80 140 H900", GRAY, 2.5)
    marks = [(80, "0 ms"), (200, "100 ms"), (420, "1000 ms"), (820, "10100 ms")]
    for x, t in marks:
        body += line(f"M{x} 130 V150", GRAY, 2, arrow=False) + text(x, 120, t, 15, GRAY, mono=True)
    body += text(640, 158, "（时间轴未按比例）", 12.5, GRAY)
    events = [(80, "SET a old PX 1000", "索引 {(1000, a)}", BLUE),
              (200, "SET a new PX 10000", "删 (1000, a)，插 (10100, a)", ORANGE),
              (420, "旧的等待醒来", "按当前索引检查：a 未到期，不删", TEAL),
              (820, "清理任务被调度", "删除 a 及 (10100, a)", RED)]
    for i, (x, a, b, c) in enumerate(events):  # 先画连线，避免压在方框上
        body += line(f"M{x} 145 V{190 + (i % 2) * 110}", c, 2, dash=True, arrow=False)
    for i, (x, a, b, c) in enumerate(events):
        y = 190 + (i % 2) * 110
        bx = min(max(x - 130, 20), 680)
        body += box(bx, y, 260, 76, c)
        body += text(bx + 130, y + 30, a, 15, c, "bold", mono=a.startswith("SET"))
        body += text(bx + 130, y + 56, b, 13.5, INK, mono=b.startswith("索引"))
    body += text(480, 420, "删除前总是重新读取共享状态，所以过期决定只取决于“当前”索引，而不是当初是谁在等待。", 15, GRAY)
    svg("ttl-timeline.svg", "覆盖写入时的过期时间线",
        "0 毫秒 SET a old PX 1000，索引记录 (1000, a)；100 毫秒 SET a new PX 10000，删除旧索引并插入 (10100, a)；1000 毫秒旧的等待醒来，检查当前索引后不删除 a；10100 毫秒清理任务删除 a 及其索引。", 445, body)


# ---------- 第 9 章 ----------

def client_forms():
    body = title("三种客户端 API，最后都落到同一个 Client")
    rows = [("异步业务", "Client::get", None, BLUE),
            ("多任务共用连接", "BufferedClient::get", "mpsc → 后台 run 任务", ORANGE),
            ("同步代码", "BlockingClient::get", "runtime.block_on", PURPLE)]
    for i, (who, api, via, c) in enumerate(rows):
        y = 85 + i * 105
        body += text(40, y + 36, who, 16, c, "bold", "start")
        body += node(180, y + 6, 210, 50, api, color=c, size=15)
        if via:
            body += node(420, y + 6, 200, 50, via, color=c, mono=False, size=14)
            body += arrow(390, y + 31, 416, y + 31, c)
            body += line(f"M620 {y + 31} C660 {y + 31} 650 191 676 191", c, 2.5)
        else:
            body += line(f"M390 {y + 31} C560 {y + 31} 620 191 676 191", c, 2.5)
    body += node(680, 166, 120, 50, "Client", color=TEAL, size=16)
    body += node(680, 246, 120, 50, "Connection", color=TEAL, size=15)
    body += arrow(740, 216, 740, 242, TEAL)
    body += node(820, 246, 110, 50, "TCP", "→ 服务端", TEAL)
    body += arrow(800, 271, 816, 271, TEAL)
    body += text(480, 420, "BufferedClient 解决“多个任务共用一个连接”，BlockingClient 解决“同步代码调用异步实现”；两者都不重写协议。", 15, GRAY)
    svg("client-forms.svg", "三种客户端的关系",
        "异步业务直接调用 Client::get；多任务业务调用 BufferedClient::get，经 mpsc 交给后台 run 任务再调用 Client；同步代码调用 BlockingClient::get，经 runtime.block_on 调用 Client。三者最终都通过 Client 和 Connection 访问 TCP。", 445, body)


def buffered_client():
    body = title("BufferedClient：请求排进一条队列，回复各走各的 oneshot")
    callers = [("调用者 A", "Get", 95, BLUE), ("调用者 B", "Set", 195, ORANGE), ("调用者 C", "Get", 295, PURPLE)]
    for name, cmd, y, c in callers:
        body += node(40, y, 150, 56, name, f"命令 {cmd} + 回信地址", c, mono=False, size=15)
        body += line(f"M192 {y + 28} C280 {y + 28} 300 223 356 223", c, 2.5)
    body += box(360, 195, 190, 56, ORANGE)
    body += text(455, 222, "有界 mpsc 队列", 15, ORANGE, "bold")
    body += text(455, 242, "排队、限流", 13, GRAY)
    body += arrow(550, 223, 596, 223, ORANGE)
    body += node(600, 190, 200, 66, "run(client, rx)", "逐个执行请求", TEAL)
    body += node(820, 190, 110, 66, "Client", "一条连接", TEAL)
    body += line("M660 188 C600 110 320 141 194 141", BLUE, 2, dash=True)
    body += line("M680 258 C620 290 320 245 194 245", ORANGE, 2, dash=True)
    body += line("M720 258 C690 350 320 345 194 345", PURPLE, 2, dash=True)
    body += text(560, 112, "oneshot 回复", 13, GRAY)
    body += arrow(800, 223, 816, 223, TEAL)
    body += text(480, 400, "实线：请求进入同一队列，顺序执行，响应不会错配；虚线：每个请求自带的 oneshot 把结果送回原调用者。", 15, GRAY)
    svg("buffered-client.svg", "BufferedClient 的消息流",
        "调用者 A、B、C 各自把命令和一个 oneshot 回信地址发进同一个有界 mpsc 队列；后台 run 任务持有唯一的 Client，按顺序执行请求，再通过各自的 oneshot 把结果送回对应调用者。", 425, body)


# ---------- 第 10 章 ----------

def shutdown_sequence():
    body = title("停机靠两组通道：一组发通知，一组等全部退出")
    body += box(30, 70, 430, 380, GRAY, "#ffffff")
    body += text(50, 98, "谁持有什么（server::run 创建）", 16, INK, "bold", "start")
    body += node(50, 115, 180, 50, "broadcast Sender", "notify_shutdown", ORANGE)
    body += text(245, 135, "只有 Listener 持有", 13.5, GRAY, anchor="start")
    body += node(50, 185, 180, 50, "Receiver × N", "每个 Shutdown", ORANGE)
    body += text(245, 205, "每个 Handler 一个", 13.5, GRAY, anchor="start")
    body += arrow(140, 165, 140, 182, ORANGE)
    body += node(50, 275, 180, 50, "mpsc Sender", "shutdown_complete_tx", BLUE)
    body += text(245, 295, "Listener 持原件", 13.5, GRAY, anchor="start")
    body += node(50, 345, 180, 50, "Sender 克隆 × N", "_shutdown_complete", BLUE)
    body += text(245, 365, "每个 Handler 一个", 13.5, GRAY, anchor="start")
    body += arrow(140, 325, 140, 342, BLUE)
    body += text(245, 425, "mpsc Receiver：server::run 保留", 13.5, BLUE, anchor="start")
    steps = [("Ctrl+C / shutdown Future 完成", GRAY), ("退出接入循环，不再创建 Handler", GRAY),
             ("drop broadcast Sender → 每个 Handler 收到通知", ORANGE), ("Handler 返回，释放连接、配额和 mpsc Sender", ORANGE),
             ("最后一个 mpsc Sender 被 drop", BLUE), ("recv() 得到 None → server::run 结束", BLUE)]
    body += text(500, 98, "发生顺序", 16, INK, "bold", "start")
    for i, (s, c) in enumerate(steps):
        y = 115 + i * 56
        body += badge(515, y + 20, i + 1, c)
        body += box(540, y, 390, 40, c, rx=8, width=1.5)
        body += text(555, y + 26, s, 14.5, INK, anchor="start")
    body += text(480, 480, "没有人真的“发送完成消息”：Sender 全部被 drop，Receiver 就会收到 None，这本身就是“全部退出”的信号。", 15, GRAY)
    svg("shutdown-sequence.svg", "优雅停机的通道与顺序",
        "server::run 创建 broadcast 通道用于通知停机，Listener 持有 Sender，每个 Handler 持有一个 Receiver；再创建 mpsc 通道用于等待退出，每个 Handler 持有一个 Sender 克隆。收到关闭信号后，接入循环退出并 drop broadcast Sender，各 Handler 收到通知后返回并释放各自的 mpsc Sender，最后一个 Sender 消失时 server::run 的 recv 得到 None 并结束。", 505, body)


# ---------- 第 11 章 ----------

def redis_topologies():
    body = title("从单机到集群：每一步解决一个新问题")
    panels = [("单机", "mini-redis 所在的位置", 30), ("主从复制", "数据有副本，读可分流", 260), ("Sentinel", "自动发现故障并切换主节点", 490), ("Cluster", "16384 个槽分片到多个主节点", 720)]
    for name, desc, x in panels:
        body += box(x, 70, 210, 330, GRAY, "#ffffff")
        body += text(x + 105, 100, name, 18, INK, "bold")
        body += text(x + 105, 384, desc, 13, GRAY)
    body += node(75, 130, 120, 44, "Client", color=BLUE, size=15)
    body += node(75, 240, 120, 50, "Redis", color=TEAL, mono=False, size=16)
    body += arrow(135, 174, 135, 236, BLUE)
    body += node(305, 130, 120, 44, "Client", color=BLUE, size=15)
    body += node(305, 220, 120, 50, "Primary", color=TEAL, size=15)
    body += node(305, 310, 120, 50, "Replica", color=PURPLE, size=15)
    body += arrow(365, 174, 365, 216, BLUE) + arrow(365, 270, 365, 306, PURPLE)
    body += text(435, 294, "复制", 12.5, PURPLE, anchor="start")
    body += node(510, 125, 170, 44, "Sentinel × 3", color=ORANGE, size=14)
    body += node(510, 220, 80, 50, "P", color=TEAL, size=16)
    body += node(600, 220, 80, 50, "R", color=PURPLE, size=16)
    body += line("M550 169 V216", ORANGE, 2, dash=True) + line("M640 169 V216", ORANGE, 2, dash=True)
    body += text(595, 310, "监测、投票、切换", 13, ORANGE)
    body += text(595, 334, "客户端向 Sentinel 询问主节点", 12.5, GRAY)
    body += node(765, 125, 120, 44, "Client", color=BLUE, size=15)
    for i, (n, slot) in enumerate([("A", "0–5460"), ("B", "5461–10922"), ("C", "10923–16383")]):
        y = 205 + i * 56
        body += node(745, y, 160, 46, f"主节点 {n}", slot, TEAL, mono=False, size=13.5)
    body += line("M825 169 V201", BLUE, 2)
    svg("redis-topologies.svg", "Redis 的四种部署形态",
        "单机：客户端访问一个 Redis 节点；主从复制：Primary 把数据复制到 Replica；Sentinel：多个 Sentinel 监测主从并在故障时切换主节点；Cluster：16384 个哈希槽分布在多个主节点上，客户端按槽访问对应节点。", 425, body)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (tcp_connect, shared_state, pubsub_flow, set_request_path, resp_bytes, frame_buffer, server_tasks,
               lock_scope, expiration_tasks, ttl_timeline, client_forms, buffered_client, shutdown_sequence,
               redis_topologies):
        fn()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
