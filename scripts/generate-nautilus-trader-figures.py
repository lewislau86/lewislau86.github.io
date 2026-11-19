"""Regenerate figures for 深入理解 NautilusTrader (pure Python, no third-party packages).

Run from any directory: python scripts/generate-nautilus-trader-figures.py
Hand-built SVG written to docs/public/nautilus-trader/figures/; text stays selectable.
Style follows scripts/generate-thinking-acting-figures.py.

Every name in these figures (crate, directory, struct, field) was checked against the
nautilus_trader `develop` branch, commit 5997d82 (2026-11-17).
"""

from html import escape
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/nautilus-trader/figures"
BLUE = "#2563eb"
TEAL = "#0f766e"
ORANGE = "#b45309"
RED = "#b91c1c"
GRAY = "#64748b"
INK = "#172033"
LIGHT = {"blue": "#eff6ff", "teal": "#f0fdfa", "orange": "#fff7ed", "gray": "#f1f5f9", "white": "#ffffff"}
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'
MONO = '"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace'
WARNINGS = []


def text_width(value, size, mono=False):
    """Rough rendered width: CJK ≈ 1 em, ASCII ≈ 0.55 em (0.6 em for monospace)."""
    ascii_em = 0.6 if mono else 0.55
    return sum(size if ord(ch) > 0x2E80 else size * ascii_em for ch in value)


def svg(name, title, description, height, body, width=960):
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{GRAY}"/></marker>
<marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker>
<marker id="arrow-orange" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ORANGE}"/></marker>
<marker id="arrow-teal" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{TEAL}"/></marker></defs>
<rect width="{width}" height="{height}" rx="16" fill="#f8fafc"/>
<g font-family='{FONT}' fill="{INK}" text-anchor="middle">{body}</g></svg>'''
    ET.fromstring(document)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(document + "\n", encoding="utf-8")
    print("wrote", OUT / name)


def text(x, y, value, size=16, color=INK, weight="normal", anchor="middle", mono=False, limit=None):
    size = max(size, 14)
    if limit is not None and text_width(value, size, mono) > limit:
        WARNINGS.append(f"text may overflow ({text_width(value, size, mono):.0f} > {limit:.0f}): {value}")
    family = f' font-family=\'{MONO}\'' if mono else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{family}>{escape(value)}</text>')


def rect(x, y, w, h, fill="white", stroke=GRAY, rx=10, width=1.5, dash=False):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{LIGHT.get(fill, fill)}" stroke="{stroke}" stroke-width="{width}"{extra}/>')


def box(x, y, w, h, lines, fill="white", stroke=GRAY, size=15, color=INK, mono_from=1, dash=False):
    """A box with a bold first line and optional monospace detail lines, centred."""
    out = rect(x, y, w, h, fill, stroke, dash=dash)
    n = len(lines)
    gap = size + 6
    top = y + h / 2 - (n - 1) * gap / 2 + size * 0.35
    for i, line in enumerate(lines):
        mono = i >= mono_from and line.isascii()
        out += text(x + w / 2, top + i * gap, line, size if i == 0 else size - 1,
                    color if i == 0 else GRAY, "bold" if i == 0 else "normal", mono=mono, limit=w - 12)
    return out


def arrow(x1, y1, x2, y2, color=GRAY, width=1.6, dash=False, both=False):
    marker = {GRAY: "arrow", BLUE: "arrow-blue", ORANGE: "arrow-orange", TEAL: "arrow-teal"}[color]
    extra = ' stroke-dasharray="6 5"' if dash else ""
    start = f' marker-start="url(#{marker})"' if both else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
            f'stroke-width="{width}"{extra} marker-end="url(#{marker})"{start}/>')


def poly_arrow(points, color=GRAY, width=1.5, dash=False):
    marker = {GRAY: "arrow", BLUE: "arrow-blue", ORANGE: "arrow-orange", TEAL: "arrow-teal"}[color]
    extra = ' stroke-dasharray="6 5"' if dash else ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"{extra} '
            f'marker-end="url(#{marker})"/>')


# ---------------------------------------------------------------------------
# 第 0 章 · 图 1：一个节点的全貌
# ---------------------------------------------------------------------------
def system_overview():
    b = text(480, 38, "一个 NautilusTrader 节点：Python 控制面、PyO3 边界、Rust 内核与后台 I/O", 20, INK, "bold")
    # Python 与 PyO3 两层
    b += rect(40, 58, 880, 54, "orange", ORANGE)
    b += text(60, 82, "Python 应用层", 16, ORANGE, "bold", "start")
    b += text(60, 102, "python/nautilus_trader/", 14, GRAY, anchor="start", mono=True)
    b += text(600, 92, "Strategy / DataActor 子类 · 配置 · 节点编排 · 报表 · 自定义适配器", 15, INK, limit=600)
    b += rect(40, 122, 880, 40, "gray", GRAY)
    b += text(60, 147, "PyO3 绑定", 16, INK, "bold", "start")
    b += text(560, 147, "扩展模块 nautilus_trader._libnautilus = crates/pyo3 汇总各 crate 的 src/python/", 15, GRAY, limit=640)
    # 节点外框
    b += rect(40, 176, 880, 384, "white", INK, rx=14, width=1.8)
    b += text(60, 198, "一个进程只跑一个节点", 14, GRAY, anchor="start")
    b += box(60, 208, 300, 46, ["BacktestEngine / BacktestNode", "crates/backtest"], "gray")
    b += box(370, 208, 270, 46, ["LiveNode + AsyncRunner", "crates/live"], "gray")
    # 内核
    b += rect(60, 266, 580, 282, "blue", BLUE, rx=12, width=1.8)
    b += text(76, 290, "NautilusKernel（crates/system）", 16, BLUE, "bold", "start")
    b += text(624, 290, "全部在核心线程上串行执行", 14, BLUE, anchor="end")
    b += box(80, 302, 540, 52, ["Trader：Actor · Strategy · ExecAlgorithm", "crates/trading · crates/common/src/actor"], "white", BLUE)
    b += rect(80, 366, 540, 34, "#dbeafe", BLUE, rx=8)
    b += text(350, 389, "MessageBus（线程局部）：点对点 · 发布/订阅 · 请求/响应", 15, BLUE, "bold", limit=530)
    xs = [80, 216, 352, 488]
    for x, (name, path) in zip(xs, [("DataEngine", "data"), ("RiskEngine", "risk"),
                                    ("ExecutionEngine", "execution"), ("OrderEmulator", "execution")]):
        b += box(x, 412, 132, 50, [name, path], "white", BLUE, size=14)
    for x, w, (name, path) in [(80, 172, ("Cache", "common/src/cache")),
                               (264, 172, ("Portfolio", "crates/portfolio")),
                               (448, 172, ("Clock", "Virtual / Live"))]:
        b += box(x, 476, w, 56, [name, path], "white", BLUE, size=14)
    for x in (146, 282, 418, 554):
        b += arrow(x, 400, x, 410, BLUE, 1.4, both=True)
    b += arrow(350, 354, 350, 364, BLUE, 1.4, both=True)
    # Tokio 一侧
    b += rect(660, 208, 240, 340, "teal", TEAL, rx=12, dash=True)
    b += text(780, 232, "Tokio 运行时（后台线程）", 15, TEAL, "bold")
    b += box(676, 246, 208, 58, ["DataClient", "crates/adapters/<venue>"], "white", TEAL, size=14)
    b += box(676, 316, 208, 58, ["ExecutionClient", "crates/adapters/<venue>"], "white", TEAL, size=14)
    b += box(676, 386, 208, 50, ["网络：HTTP / WebSocket", "crates/network"], "white", TEAL, size=14)
    b += box(676, 448, 208, 50, ["写库 · 写数据目录", "持久化后台任务"], "white", TEAL, size=14, mono_from=9)
    b += text(780, 528, "只通过 channel 把事件送回核心", 14, TEAL)
    b += arrow(676, 290, 642, 380, ORANGE, 1.8)
    b += arrow(676, 350, 642, 386, ORANGE, 1.8)
    # 外部世界
    b += box(60, 574, 400, 44, ["回测：成交由节点内的 SimulatedExchange 撮合"], "gray", size=15)
    b += box(500, 574, 420, 44, ["实盘：交易所 · 券商（REST / WebSocket / 私有 TCP）"], "gray", size=15)
    b += arrow(780, 548, 780, 572, GRAY, 1.6, both=True)
    svg("system-overview.svg", "NautilusTrader 节点全貌",
        "最上层是 Python 应用，经 PyO3 扩展模块进入 Rust。一个进程一个节点，节点外壳是 BacktestEngine 或 LiveNode，"
        "内部的 NautilusKernel 在单一核心线程上运行 Trader、MessageBus、各引擎、Cache、Portfolio 和 Clock；"
        "适配器客户端、网络和持久化写入跑在 Tokio 后台线程，只通过 channel 把事件送回核心线程。",
        636, b)


# ---------------------------------------------------------------------------
# 第 0 章 · 图 2：crate 分层
# ---------------------------------------------------------------------------
def rust_crates():
    b = text(480, 38, "crates/ 下的 24 个 crate 与 21 个适配器：按 Cargo.toml 的依赖分层，依赖只朝下", 20, INK, "bold")
    layers = [
        ("外围", ORANGE, "orange", ["adapters/* ×21", "pyo3", "testkit", "plugin", "cli"],
         "交易所与券商适配器；Python 扩展汇总；测试工具；插件接口；命令行"),
        ("外壳", BLUE, "blue", ["system", "backtest", "live", "event_store"],
         "NautilusKernel 与 Trader；回测引擎；实盘节点与对账；事件存储"),
        ("引擎", BLUE, "blue", ["data", "execution", "portfolio", "risk", "trading"],
         "数据引擎；执行引擎、撮合与订单仿真；组合；风控；策略与执行算法"),
        ("后端", TEAL, "teal", ["persistence", "infrastructure"],
         "Parquet 数据目录与流式写入；Redis / PostgreSQL 缓存与总线后端"),
        ("公共服务", INK, "gray", ["common"],
         "MessageBus、Cache、Clock、Actor / Component、客户端 trait、实盘 runner"),
        ("工具库", TEAL, "teal", ["network", "cryptography", "serialization", "indicators", "analysis"],
         "HTTP / WebSocket / Socket；TLS；Arrow 与 SBE；技术指标；绩效统计"),
        ("地基", INK, "gray", ["core", "macros", "model"],
         "时间戳、UUID、正确性检查；过程宏；领域模型（值类型、行情、订单、仓位…）"),
    ]
    y = 62
    for name, color, fill, crates, note in layers:
        b += rect(40, y, 856, 62, fill, color, rx=12)
        b += text(60, y + 37, name, 17, color, "bold", "start")
        x = 160
        for c in crates:
            w = text_width(c, 15, True) + 26
            b += rect(x, y + 10, w, 26, "white", color, rx=7, width=1.2)
            b += text(x + w / 2, y + 28, c, 15, INK, mono=True)
            x += w + 10
        if x > 880:
            WARNINGS.append(f"crate chips overflow in layer {name}")
        b += text(160, y + 54, note, 14, GRAY, anchor="start", limit=720)
        y += 70
    b += arrow(918, 72, 918, y - 16, GRAY, 1.6)
    label = text(0, 0, "依赖方向", 14, GRAY)
    b += label.replace('<text x="0.0" y="0.0"', f'<text x="0" y="0" transform="translate(936 {(72 + y) / 2:.1f}) rotate(90)"', 1)
    b += text(480, y + 16, "另有 crates/lib.rs 组成的伞形 crate nautilus-trader（只重导出 core、common、model），以及 examples/tutorials。",
              14, GRAY, limit=880)
    svg("rust-crates.svg", "Rust crate 分层",
        "crates 目录按 Cargo.toml 的依赖分成七层：地基 core、macros、model；工具库 network、cryptography、serialization、indicators、analysis；"
        "公共服务 common；后端 persistence、infrastructure；引擎 data、execution、portfolio、risk、trading；"
        "外壳 system、backtest、live、event_store；外围是 21 个适配器以及 pyo3、testkit、plugin、cli。依赖只从上层指向下层。",
        y + 36, b)


# ---------------------------------------------------------------------------
# 第 0 章 · 图 3：Python 对象与 Rust 状态的三种关系
# ---------------------------------------------------------------------------
def python_projection():
    b = text(480, 38, "Python 里拿到的对象和 Rust 状态有三种关系", 20, INK, "bold")
    cols = [
        (40, "① 值对象：跨边界就复制", ORANGE, "orange",
         [("Python 侧", "QuoteTick、Price、订单", False), ("绑定方式", "#[pyclass(from_py_object)]", True),
          ("Rust 侧", "同名 struct 的另一份拷贝", False)],
         ["策略收到的 quote、", "cache.order() 返回的订单，", "都是那一刻的快照"], True),
        (345, "② 句柄：共享同一份状态", BLUE, "blue",
         [("Python 侧", "Cache、Portfolio、Clock", False), ("绑定方式", "PyCache(Rc<RefCell<Cache>>)", True),
          ("Rust 侧", "内核里唯一的那个 Cache", False)],
         ["句柄本身不存数据，", "每次读都去借 Rust 的状态，", "unsendable：不能跨线程"], False),
        (650, "③ 基类：Rust 回调 Python", TEAL, "teal",
         [("Python 侧", "class MyStrategy(Strategy)", True), ("PyStrategy.inner", "Rc<UnsafeCell<Inner>>", True),
          ("Rust 侧", "StrategyCore + 弱引用 py_self", False)],
         ["Inner 实现 Strategy trait，", "事件到来时用 call_method1", "调回 Python 的 on_quote 等"], True),
    ]
    for x, title, color, fill, chain, notes, both in cols:
        b += rect(x, 62, 290, 392, fill, color, rx=14)
        b += text(x + 145, 92, title, 17, color, "bold", limit=270)
        for i, (label, content, mono) in enumerate(chain):
            yy = 114 + i * 94
            b += rect(x + 16, yy, 258, 62, "white", color, rx=9, width=1.3)
            b += text(x + 145, yy + 24, label, 14, GRAY, mono=label.startswith("Py") and "." in label)
            b += text(x + 145, yy + 48, content, 14 if mono else 15, INK, "bold" if not mono else "normal",
                      mono=mono, limit=250)
            if i < 2:
                b += arrow(x + 145, yy + 64, x + 145, yy + 92, color if color != TEAL else GRAY, 1.6, both=both)
        for j, line in enumerate(notes):
            b += text(x + 145, 404 + j * 20, line, 14, GRAY, limit=270)
    b += text(480, 482, "所以：不要缓存旧的订单对象等它“自己变”；要最新状态就再向 cache 要一次。", 15, RED, "bold", limit=900)
    svg("python-projection.svg", "Python 对象与 Rust 状态的三种关系",
        "第一种是值对象，例如 QuoteTick、Price、LimitOrder，Python 与 Rust 之间传递时各自持有一份拷贝；"
        "第二种是句柄，例如 Cache、Portfolio、Clock，Python 对象只包着 Rc<RefCell<…>>，读的是内核里唯一的那份状态；"
        "第三种是可继承的基类 Strategy，Rust 端的 PyStrategyInner 实现 Strategy trait，通过弱引用回调 Python 子类的 on_quote 等方法。",
        502, b)


# ---------------------------------------------------------------------------
# 第 0 章 · 图 4：Cache 的内部布局
# ---------------------------------------------------------------------------
def cache_layout():
    b = text(480, 38, "Cache 内部：主表存对象，索引只存 ID，行情存成定长环形队列", 20, INK, "bold")
    # 左：Cache 主表
    b += rect(40, 60, 430, 470, "blue", BLUE, rx=14)
    b += text(255, 88, "struct Cache（crates/common/src/cache/mod.rs）", 15, BLUE, "bold", limit=400)
    rows = [
        ("instruments", "AHashMap<InstrumentId, InstrumentAny>"),
        ("books", "AHashMap<InstrumentId, OrderBook>"),
        ("quotes / trades", "AHashMap<InstrumentId, BoundedVecDeque<…>>"),
        ("bars", "AHashMap<BarType, BoundedVecDeque<Bar>>"),
        ("orders", "AHashMap<ClientOrderId, SharedCell<OrderAny>>"),
        ("positions", "AHashMap<PositionId, SharedCell<Position>>"),
        ("accounts", "AHashMap<AccountId, SharedCell<AccountAny>>"),
        ("index", "CacheIndex"),
        ("database", "Option<Box<dyn CacheDatabaseAdapter>>"),
    ]
    y = 104
    for name, ty in rows:
        hot = name in ("orders", "positions", "index")
        b += rect(56, y, 398, 42, "white", BLUE if hot else GRAY, rx=8, width=1.6 if hot else 1.1)
        b += text(68, y + 18, name, 14, BLUE if hot else INK, "bold", "start", mono=True)
        b += text(68, y + 36, ty, 14, GRAY, anchor="start", mono=True, limit=386)
        y += 46
    # 右上：订单对象
    b += rect(490, 60, 430, 210, "orange", ORANGE, rx=14)
    b += text(705, 88, "SharedCell<OrderAny> = Rc<RefCell<…>>", 15, ORANGE, "bold", mono=True, limit=400)
    b += box(506, 102, 398, 46, ["OrderAny::Limit(LimitOrder)", "price · expire_time · is_post_only …"], "white", ORANGE, size=14)
    b += box(506, 158, 398, 96, ["OrderCore", "events: Vec<OrderEventAny>",
                                  "status · filled_qty · leaves_qty · avg_px", "client_order_id · venue_order_id …"],
             "white", ORANGE, size=14)
    b += arrow(454, 304, 490, 200, ORANGE, 1.8)
    # 右下：索引
    b += rect(490, 286, 430, 244, "teal", TEAL, rx=14)
    b += text(705, 314, "CacheIndex：31 个只放 ID 的表", 15, TEAL, "bold")
    idx = ["venue_order_ids: VenueOrderId → ClientOrderId", "client_order_ids: ClientOrderId → VenueOrderId",
           "order_strategy / order_position / order_client", "strategy_orders / instrument_orders",
           "venue_orders / account_orders / …", "orders_open / orders_closed / orders_inflight",
           "orders_emulated / orders_pending_cancel", "positions_open / positions_closed"]
    for i, line in enumerate(idx):
        b += text(506, 340 + i * 23, line, 14, INK, anchor="start", mono=True, limit=402)
    b += arrow(454, 442, 490, 420, GRAY, 1.8)
    b += text(480, 556, "写入只由引擎在核心线程上完成；用户代码（Rust 的 CacheApi、Python 的 Cache）读到的是克隆出来的快照。",
              14, GRAY, limit=900)
    svg("cache-layout.svg", "Cache 的内部布局",
        "Cache 用哈希表按 ID 存标的、订单簿、行情环形队列、订单、仓位和账户；订单、仓位、账户包在 SharedCell 也就是 Rc<RefCell<…>> 里。"
        "一个订单是 OrderAny 枚举，里面是具体订单类型加上 OrderCore，OrderCore 保存事件列表和当前状态。"
        "CacheIndex 是 31 个只存 ID 的映射和集合，例如 venue_order_ids、orders_open、orders_inflight。",
        576, b)


# ---------------------------------------------------------------------------
# 第 0 章 · 图 5：订单簿的三层结构
# ---------------------------------------------------------------------------
def order_book_layout():
    b = text(480, 38, "OrderBook：两条 BTreeMap 价格阶梯，每个价位一个保持先后顺序的 IndexMap", 20, INK, "bold")
    b += box(330, 58, 300, 70, ["OrderBook", "instrument_id · book_type", "sequence · ts_last · update_count"], "gray", INK, size=15)
    for x, side, color, fill, prices in [(40, "bids: BookLadder（买）", BLUE, "blue", ["100.02", "100.01", "100.00"]),
                                         (500, "asks: BookLadder（卖）", ORANGE, "orange", ["100.03", "100.04", "100.05"])]:
        b += rect(x, 150, 420, 330, fill, color, rx=14)
        b += text(x + 210, 176, side, 16, color, "bold")
        b += text(x + 210, 198, "levels: BTreeMap<BookPrice, BookLevel>", 14, GRAY, mono=True, limit=400)
        for i, p in enumerate(prices):
            yy = 214 + i * 70
            b += rect(x + 16, yy, 120, 56, "white", color, rx=8)
            b += text(x + 76, yy + 24, p, 15, INK, "bold", mono=True)
            b += text(x + 76, yy + 44, "最优" if i == 0 else f"第 {i + 1} 档", 14, GRAY)
            b += arrow(x + 138, yy + 28, x + 158, yy + 28, color, 1.4)
            for k in range(3 - (i == 2)):
                ox = x + 162 + k * 82
                b += rect(ox, yy + 8, 74, 40, "white", GRAY, rx=6, width=1)
                b += text(ox + 37, yy + 33, f"#{(10 if x == 40 else 50) + i * 3 + k}", 14, INK, mono=True)
        b += text(x + 210, 440, "BookLevel.orders: IndexMap<OrderId, BookOrder>", 14, GRAY, mono=True, limit=400)
        b += text(x + 210, 462, "插入顺序 = 排队顺序（L3 逐笔；L2 每档只有一条）", 14, GRAY, limit=400)
        b += arrow(480 if x == 40 else 480, 128, x + 210, 150, GRAY, 1.4)
    b += text(480, 506, "BookPrice 的 Ord 在买方向反转，所以两边的第一个元素都是最优价；cache: HashMap<u64, BookPrice> 按订单号直接找到所在价位。",
              14, GRAY, limit=900)
    svg("order-book.svg", "OrderBook 的数据结构",
        "OrderBook 有 bids 和 asks 两条 BookLadder，每条是一个 BTreeMap，键为 BookPrice、值为 BookLevel。"
        "买方向的 BookPrice 比较顺序反转，因此两边的第一个元素都是最优价。每个 BookLevel 用 IndexMap 按插入顺序保存该价位上的 BookOrder，"
        "另有一个按订单号到价位的 HashMap，用来在修改和删除时直接定位。",
        526, b)


# ---------------------------------------------------------------------------
# 第 1 章 · crate 依赖图（各 crate Cargo.toml 的 [dependencies]，默认 feature，做过传递约简）
# ---------------------------------------------------------------------------
DEP_ROWS = [70, 155, 240, 325, 410, 495, 580, 665]
DEP_NODES = {
    # 名字: (中心 x, 行, 配色)
    "pyo3": (300, 0, "orange"), "adapters/*": (640, 0, "orange"),
    "backtest": (300, 1, "blue"), "live": (640, 1, "blue"), "event_store": (850, 1, "blue"),
    "system": (470, 2, "blue"),
    "data": (130, 3, "blue"), "risk": (360, 3, "blue"), "trading": (580, 3, "blue"),
    "persistence": (130, 4, "teal"), "execution": (360, 4, "blue"), "portfolio": (580, 4, "blue"),
    "infrastructure": (720, 4, "teal"), "network": (870, 4, "teal"),
    "serialization": (130, 5, "teal"), "common": (360, 5, "gray"), "analysis": (560, 5, "teal"),
    "indicators": (690, 5, "teal"), "cryptography": (820, 5, "teal"),
    "model": (360, 6, "gray"), "macros": (580, 6, "gray"),
}
DEP_EDGES = [
    ("pyo3", "backtest"), ("pyo3", "live"), ("adapters/*", "live"),
    ("backtest", "system"), ("live", "system"), ("live", "network"), ("event_store", "system"),
    ("system", "data"), ("system", "risk"), ("system", "trading"),
    ("data", "common"), ("risk", "execution"), ("risk", "portfolio"),
    ("trading", "execution"), ("trading", "portfolio"),
    ("persistence", "common"), ("persistence", "serialization"),
    ("execution", "common"), ("portfolio", "common"), ("portfolio", "analysis"),
    ("infrastructure", "common"), ("infrastructure", "cryptography"), ("network", "cryptography"),
    ("common", "model"), ("analysis", "model"), ("indicators", "model"),
]
DEP_OPTIONAL = [("data", "persistence")]
DEP_TO_CORE = ["serialization", "model", "network"]


def node_width(name):
    return max(112, text_width(name, 15, True) + 18)


def crate_dependencies():
    h = 38
    stroke = {"orange": ORANGE, "blue": BLUE, "teal": TEAL, "gray": INK}
    b = text(480, 36, "crate 依赖图：箭头从使用方指向被依赖方（默认 feature，省略能经由其他箭头推出的边）", 18, INK, "bold", limit=920)

    def anchor(name, top):
        x, row, _ = DEP_NODES[name]
        y = DEP_ROWS[row]
        return x, (y - h / 2 if top else y + h / 2)

    def edge(src, dst, color=GRAY, dash=False):
        x1, y1 = anchor(src, False)
        x2, y2 = anchor(dst, True)
        return arrow(x1, y1, x2, y2 - 2, color, 1.4, dash=dash)

    for src, dst in DEP_EDGES:
        b += edge(src, dst)
    for src, dst in DEP_OPTIONAL:
        b += edge(src, dst, ORANGE, dash=True)
    b += arrow(DEP_NODES["model"][0] + node_width("model") / 2 + 2, DEP_ROWS[6],
               DEP_NODES["macros"][0] - node_width("macros") / 2 - 4, DEP_ROWS[6], GRAY, 1.4)
    core_top = DEP_ROWS[7] - h / 2
    for name in DEP_TO_CORE:
        x, row, _ = DEP_NODES[name]
        if name == "network":
            x += node_width(name) / 2 - 10      # 绕开左下方的 cryptography
            b += arrow(x, DEP_ROWS[row] + h / 2, x, core_top - 2, GRAY, 1.4)
        else:
            b += arrow(x, DEP_ROWS[row] + h / 2, x, core_top - 2, GRAY, 1.4)
    for name, (x, row, fill) in DEP_NODES.items():
        y = DEP_ROWS[row]
        w = node_width(name)
        b += rect(x - w / 2, y - h / 2, w, h, fill, stroke[fill], rx=8, width=1.5)
        b += text(x, y + 5, name, 15, INK, mono=True, limit=w - 8)
    b += rect(80, core_top, 840, h, "gray", INK, rx=8, width=1.5)
    b += text(480, DEP_ROWS[7] + 5, "core（时间戳、UUID、正确性检查；几乎所有 crate 都直接依赖它）", 15, INK, limit=820)
    ly = DEP_ROWS[7] + 46
    b += arrow(90, ly, 140, ly, ORANGE, 1.4, dash=True)
    b += text(150, ly + 5, "可选依赖（streaming feature）", 14, GRAY, anchor="start")
    b += text(420, ly + 5, "pyo3 实际依赖几乎所有 crate，图中只画两条；testkit、plugin、cli 未画出", 14, GRAY, anchor="start", limit=520)
    svg("crate-dependencies.svg", "NautilusTrader crate 依赖图",
        "按各 crate 的 Cargo.toml 画出的依赖图，箭头从使用方指向被依赖方。最上面的 pyo3 和适配器依赖 backtest 或 live；"
        "backtest、live、event_store 依赖 system；system 依赖 data、risk、trading；risk 和 trading 依赖 execution 与 portfolio；"
        "data、execution、portfolio、persistence、infrastructure 都依赖 common；common、analysis、indicators 依赖 model；"
        "model 依赖 core 和 macros；network 依赖 cryptography 和 core。data 对 persistence 的依赖是可选的。",
        DEP_ROWS[7] + 70, b)


# ---------------------------------------------------------------------------
# 从零编译 · 图：两条构建流水线（依据 Makefile、python/pyproject.toml、python/generate_stubs.py）
# ---------------------------------------------------------------------------
def build_pipeline():
    b = text(480, 36, "从源码到能运行：Rust 一条路，Python 一条路，共用同一个 Cargo 工作区", 19, INK, "bold", limit=920)
    # 共用的底座
    b += rect(40, 56, 880, 64, "gray", INK, rx=12)
    b += text(60, 82, "共用", 16, INK, "bold", "start")
    b += text(130, 82, "rustup：rust-toolchain.toml 锁定 1.100.0", 15, INK, anchor="start", limit=330)
    b += text(520, 82, "Cargo.lock：937 个包，构建一律加 --locked", 15, INK, anchor="start", limit=390)
    b += text(130, 106, "make 的编译目标先跑 check-cargo-cooldown：拒绝发布不足冷却期的依赖版本", 14, GRAY, anchor="start", limit=780)
    # Rust 线
    b += rect(40, 136, 330, 404, "blue", BLUE, rx=14)
    b += text(205, 162, "Rust 部分（不需要 Python）", 16, BLUE, "bold")
    steps_r = [
        ("cargo build -p nautilus-model", "只编一个 crate，先验证工具链"),
        ("cargo run -p nautilus-backtest", "--example engine-ema-cross"),
        ("target/debug/examples/…", "一个独立的可执行文件，跑完一次回测"),
        ("cargo test / cargo nextest", "或 make cargo-test-core-local"),
    ]
    y = 178
    for i, (a, c) in enumerate(steps_r):
        b += rect(56, y, 298, 72, "white", BLUE, rx=9, width=1.3)
        b += text(205, y + 28, a, 14, INK, "bold", mono=True, limit=286)
        b += text(205, y + 52, c, 14, GRAY, limit=286)
        if i < len(steps_r) - 1:
            b += arrow(205, y + 74, 205, y + 88, BLUE, 1.5)
        y += 90
    # Python 线
    b += rect(390, 136, 530, 404, "orange", ORANGE, rx=14)
    b += text(655, 162, "Python 部分：make build-debug 依次做四件事", 16, ORANGE, "bold")
    steps_p = [
        ("① make sync", "uv sync：把 uv.lock 里的 72 个依赖装进 python/.venv（不装本包）"),
        ("② make py-stubs", "cargo run --bin python-stub-gen（maturin 那组 feature）→ 生成 .pyi"),
        ("③ maturin develop --profile nextest", "编译 crates/pyo3 → _libnautilus.*.so，放进包目录"),
        ("④ 在 python/.venv 里运行", "uv run --project python --no-sync python examples/backtest/…"),
    ]
    y = 178
    for i, (a, c) in enumerate(steps_p):
        b += rect(406, y, 498, 72, "white", ORANGE, rx=9, width=1.3)
        b += text(655, y + 28, a, 14, INK, "bold", mono=not any(ord(ch) > 0x2E80 for ch in a[1:]), limit=486)
        b += text(655, y + 52, c, 14, GRAY, limit=486)
        if i < len(steps_p) - 1:
            b += arrow(655, y + 74, 655, y + 88, ORANGE, 1.5)
        y += 90
    b += text(480, 566, "②和③都是完整的 Rust 编译，feature 取自 pyproject.toml 的 [tool.maturin]，含全部适配器；首次构建最耗时的是这两步。",
              14, GRAY, limit=900)
    svg("build-pipeline.svg", "从零编译的两条流水线",
        "上面是两条路共用的底座：rustup 按 rust-toolchain.toml 安装 1.100.0，Cargo.lock 锁定 937 个包，make 的编译目标先做依赖冷却期检查。"
        "左边是 Rust 部分：不需要 Python，直接用 cargo 编译某个 crate、运行 nautilus-backtest 的 engine-ema-cross 示例、跑测试。"
        "右边是 Python 部分，make build-debug 依次执行 make sync、生成类型存根、maturin develop 编译扩展模块，最后装进 python/.venv。",
        590, b)


# ---------------------------------------------------------------------------
# 第 2 章 · 富途适配器：在 crate 图里的位置、运行时位置、Python 绑定链
# （futu-opend、adapters/futu 是本书提议的新 crate，其余名字取自 develop 5997d82）
# ---------------------------------------------------------------------------
def crate_box(x, y, name, fill="white", color=GRAY, w=None, h=38, dash=False, size=15, mono=True):
    w = w or max(112, text_width(name, size, mono) + 22)
    out = rect(x - w / 2, y - h / 2, w, h, fill, color, rx=8, width=1.8 if dash else 1.4, dash=dash)
    out += text(x, y + 5, name, size, INK, "bold" if dash else "normal", mono=mono, limit=w - 8)
    return out, w


def futu_in_crates():
    b = text(480, 36, "富途适配器放在 crate 图的哪里：和 IB 适配器平级，挂在 live 之下", 19, INK, "bold", limit=920)
    nodes = {}

    def put(name, x, y, **kw):
        nonlocal b
        out, w = crate_box(x, y, name, **kw)
        b += out
        nodes[name] = (x, y, w)

    def link(a, c, color=GRAY, dash=False, label=None, lx=None, ly=None):
        nonlocal b
        xa, ya, _ = nodes[a]
        xc, yc, wc = nodes[c]
        if abs(ya - yc) < 1:
            x1 = xa + nodes[a][2] / 2 if xc > xa else xa - nodes[a][2] / 2
            x2 = xc - wc / 2 - 3 if xc > xa else xc + wc / 2 + 3
            b += arrow(x1, ya, x2, yc, color, 1.5, dash=dash)
        else:
            b += arrow(xa, ya + 19, xc, yc - 21, color, 1.5, dash=dash)
        if label:
            b += text(lx, ly, label, 14, color, anchor="start")

    put("pyo3", 330, 80, fill="orange", color=ORANGE)
    put("adapters/interactive_brokers", 170, 170, fill="blue", color=BLUE)
    put("adapters/futu", 470, 170, fill="#fde68a", color=ORANGE, dash=True)
    put("futu-opend", 720, 170, fill="#fde68a", color=ORANGE, dash=True)
    put("ibapi", 90, 260, fill="gray", color=GRAY)
    put("live", 330, 260, fill="blue", color=BLUE)
    put("system", 330, 345)
    b += rect(150, 412, 300, 38, "blue", BLUE, rx=8)
    b += text(300, 437, "data · execution · risk · portfolio · trading", 14, INK, mono=True, limit=290)
    nodes["engines"] = (300, 431, 300)
    put("common", 330, 515, fill="gray", color=INK)
    put("model · core", 330, 595, fill="gray", color=INK)
    link("pyo3", "adapters/interactive_brokers")
    link("pyo3", "adapters/futu", ORANGE, label="adapters feature", lx=420, ly=112)
    link("adapters/interactive_brokers", "ibapi")
    link("adapters/interactive_brokers", "live")
    link("adapters/futu", "live", ORANGE)
    link("adapters/futu", "futu-opend", ORANGE)
    link("live", "system")
    b += arrow(330, 364, 330, 410, GRAY, 1.5)
    b += arrow(330, 452, 330, 494, GRAY, 1.5)
    link("common", "model · core")
    b += poly_arrow([(520, 189), (540, 230), (540, 515), (394, 515)], ORANGE, 1.4, dash=True)
    b += text(548, 470, "实现 trait", 14, ORANGE, anchor="start")
    # 右侧说明
    b += rect(630, 236, 300, 440, "white", ORANGE, rx=12)
    b += text(646, 262, "要新增的两个 crate", 16, ORANGE, "bold", "start")
    lines = [
        ("futu-opend（独立协议库）", True),
        ("· 不依赖任何 nautilus crate", False),
        ("· tokio + prost：包头、SHA1、", False),
        ("　RSA/AES、心跳、请求与回包对应", False),
        ("· 地位等同 IB 适配器依赖的 ibapi", False),
        ("adapters/futu（nautilus-futu）", True),
        ("· 依赖 live、common、model、", False),
        ("　core 和 futu-opend", False),
        ("· 实现 common 里的 DataClient、", False),
        ("　ExecutionClient trait", False),
        ("· python feature 下才依赖 system", False),
        ("要改的现有文件", True),
        ("· 根 Cargo.toml；Makefile 的", False),
        ("　ADAPTER_CRATES", False),
        ("· crates/pyo3：Cargo.toml、lib.rs", False),
    ]
    y = 292
    for line, head in lines:
        if head and y > 300:
            y += 6
        b += text(646, y, line, 15 if head else 14, INK if head else GRAY, "bold" if head else "normal", "start", limit=276)
        y += 26
    b += text(480, 704, "橙色虚线框是新增的部分；箭头从使用方指向被依赖方。IB 适配器的依赖取自它的 Cargo.toml，富途照此设计。", 14, GRAY, limit=900)
    svg("futu-in-crates.svg", "富途适配器在 crate 依赖图中的位置",
        "富途适配器 adapters/futu 和 adapters/interactive_brokers 平级，被 pyo3 在 adapters feature 下依赖，自己依赖 live，"
        "并实现 common 里的 DataClient 和 ExecutionClient trait。它下面另有一个新增的独立协议库 futu-opend，对应 IB 适配器依赖的第三方 ibapi。"
        "live 依赖 system，system 依赖各引擎，引擎依赖 common，common 依赖 model 和 core。",
        724, b)


def futu_runtime():
    b = text(480, 36, "运行时：trait 方法在核心线程上立刻返回，网络活交给 Tokio，结果经 channel 回来", 19, INK, "bold", limit=920)
    # 核心线程
    b += rect(14, 58, 432, 520, "blue", BLUE, rx=14)
    b += text(30, 84, "核心线程（单线程）", 16, BLUE, "bold", "start")
    L, R, W = 40, 242, 190
    b += box(L, 100, W, 50, ["DataEngine"], "white", BLUE, size=15)
    b += box(R, 100, W, 50, ["ExecutionEngine"], "white", BLUE, size=15)
    b += box(L, 176, W, 56, ["DataClientAdapter", "data/src/client.rs"], "white", BLUE, size=14)
    b += box(R, 176, W, 56, ["ExecutionClientAdapter", "execution/src/client/"], "white", BLUE, size=14)
    b += box(L, 258, W, 64, ["FutuDataClient", "subscribe_quotes(…)", "同步，立刻返回"], "#fde68a", ORANGE, size=14, dash=True)
    b += box(R, 258, W, 64, ["FutuExecutionClient", "submit_order(…)", "同步，立刻返回"], "#fde68a", ORANGE, size=14, dash=True)
    for x in (L + W / 2, R + W / 2):
        b += arrow(x, 152, x, 174, BLUE, 1.5)
        b += arrow(x, 234, x, 256, BLUE, 1.5)
    b += box(L, 470, 392, 56, ["AsyncRunner（crates/live/src/runner.rs）", "从 channel 取事件，派发到引擎的端点"], "white", BLUE, size=14)
    b += poly_arrow([(L + 20, 468), (L + 20, 440), (26, 440), (26, 125), (L - 2, 125)], BLUE, 1.3, dash=True)
    b += poly_arrow([(R + W - 20, 468), (R + W - 20, 440), (438, 440), (438, 125), (R + W + 2, 125)], BLUE, 1.3, dash=True)
    b += text(236, 418, "DataEngine.process_data · ExecEngine.process", 14, BLUE, mono=True, limit=400)
    b += text(230, 556, "适配器只读缓存（CacheView），不写", 14, GRAY)
    # Tokio
    b += rect(470, 58, 300, 520, "teal", TEAL, rx=14, dash=True)
    b += text(486, 84, "Tokio 运行时", 16, TEAL, "bold", "start")
    b += box(484, 100, 272, 70, ["TaskGroup 里的任务", "订阅、下单、查询各起任务", "（不允许直接 tokio::spawn）"], "white", TEAL, size=14)
    b += box(484, 206, 272, 182, ["FutuSharedClient（共享连接）", "长度前缀编解码：包头 + protobuf", "serial_no → 等待中的请求", "定时发 KeepAlive（1004）", "推送按 proto_id 分发", "限流：下单 15 次 / 30 秒"],
             "#fde68a", ORANGE, size=14, dash=True)
    b += box(484, 420, 272, 104, ["推送解析", "行情推送 → QuoteTick 等", "2208 / 2218 → 订单事件或报告", "→ get_*_event_sender()"], "white", TEAL, size=14)
    b += poly_arrow([(L + W / 2, 324), (L + W / 2, 346), (456, 346), (456, 150), (482, 150)], ORANGE, 1.5)
    b += f'<line x1="{R + W:.1f}" y1="290" x2="456" y2="290" stroke="{ORANGE}" stroke-width="1.5"/>'
    b += text(330, 340, "spawn 到 TaskGroup", 14, ORANGE)
    b += arrow(620, 172, 620, 204, TEAL, 1.5, both=True)
    b += arrow(620, 390, 620, 418, TEAL, 1.5)
    b += arrow(482, 498, 434, 498, ORANGE, 1.8)
    # OpenD
    b += box(796, 200, 150, 96, ["OpenD", "127.0.0.1:11111", "本机网关进程"], "gray", INK, size=15)
    b += box(796, 380, 150, 60, ["富途服务器", "行情 · 交易"], "gray", INK, size=15)
    b += arrow(758, 248, 794, 248, GRAY, 1.8, both=True)
    b += text(776, 238, "TCP", 14, GRAY, mono=True)
    b += arrow(871, 298, 871, 378, GRAY, 1.6, both=True)
    b += text(480, 604, "橙色虚线框是富途要写的部分，其余都是现成的。", 14, GRAY)
    b += text(480, 626, "命令：引擎 → 适配器方法 → Tokio 任务 → 共享连接；事件：推送 → 解析 → channel → AsyncRunner → 引擎。", 14, GRAY, limit=920)
    svg("futu-runtime.svg", "富途适配器的运行时位置",
        "核心线程上，DataEngine 和 ExecutionEngine 经 DataClientAdapter、ExecutionClientAdapter 调用 FutuDataClient 和 FutuExecutionClient 的同步 trait 方法，"
        "这些方法把网络工作交给 Tokio 上 TaskGroup 里的任务后立刻返回。任务通过共享连接 FutuSharedClient 与本机 OpenD 通信，OpenD 再连富途服务器。"
        "推送被解析成 QuoteTick、订单事件或报告，经 channel 交给 AsyncRunner，再派发回引擎。",
        646, b)


def futu_python_binding():
    b = text(480, 36, "Python 怎么用上富途适配器：官方路线走 PyO3 注册表，另一条路是纯 Python 客户端", 19, INK, "bold", limit=920)
    b += rect(30, 58, 560, 586, "orange", ORANGE, rx=14)
    b += text(46, 84, "路线 A：Rust 适配器 + PyO3 绑定（和 IB 一样）", 16, ORANGE, "bold", "start")
    steps = [
        ("① 配置和工厂类型加 #[pyclass]", "config.rs、factories.rs：FutuDataClientConfig、FutuDataClientFactory…"),
        ("② src/python/mod.rs：#[pymodule] fn futu", "add_class；注册表登记工厂名 \"FUTU\" 和配置类名的提取函数"),
        ("③ crates/pyo3", "Cargo.toml 加可选依赖；lib.rs 挂成 _libnautilus.futu"),
        ("④ python/nautilus_trader/adapters/futu/", "__init__.py 转出；make py-stubs 生成 __init__.pyi"),
        ("⑤ 用户脚本", "builder.add_data_client(None, FutuDataClientFactory(), 配置)"),
        ("⑥ LiveNodeBuilder.add_data_client（现成）", "按工厂名和配置类名查注册表，取出 Rust 的工厂和配置"),
    ]
    y = 100
    for i, (head, detail) in enumerate(steps):
        b += rect(46, y, 528, 72, "white", ORANGE, rx=9, width=1.3)
        mono = not any(ord(ch) > 0x2E80 for ch in head[1:])
        b += text(60, y + 30, head, 15, INK, "bold", "start", mono=False, limit=500)
        b += text(60, y + 56, detail, 14, GRAY, anchor="start", limit=506)
        if i < len(steps) - 1:
            b += arrow(310, y + 74, 310, y + 84, ORANGE, 1.5)
        y += 86
    b += text(310, 626, "①②在适配器 crate 里；③改两个现有文件；④⑤是 Python；⑥是现成的", 14, GRAY, limit=540)
    b += rect(610, 58, 320, 586, "teal", TEAL, rx=14)
    b += text(626, 84, "路线 B：纯 Python 适配器", 16, TEAL, "bold", "start")
    right = [
        ("继承 nautilus_trader.live.clients", True),
        ("DataClient / ExecutionClient", False),
        ("DataClientFactory /", False),
        ("ExecutionClientFactory", False),
        ("注册时必须给名字", True),
        ("add_data_client(\"FUTU\", Factory,", False),
        ("  DataClientConfig(…))", False),
        ("节点用 PythonDataFactory 包一层", True),
        ("订阅和命令钩子是 async，跑在节点的", False),
        ("asyncio 循环上；拿到只读缓存，", False),
        ("输出经队列交给 Rust 引擎", False),
        ("可以直接用富途官方的 futu-api", True),
        ("Python SDK 连 OpenD，最快跑通；", False),
        ("代价是协议处理留在 Python 里", False),
        ("路线 C：独立的 Rust/PyO3 包", True),
        ("外观仍继承上面的 Python 基类，", False),
        ("只能和已安装 wheel 里的模型类", False),
        ("交换对象，不能共享 Rust trait 对象", False),
    ]
    y = 118
    for line, head in right:
        b += text(626, y, line, 15 if head else 14, INK if head else GRAY, "bold" if head else "normal", "start",
                  mono=(not head and line.isascii()), limit=296)
        y += 31 if head else 27
    svg("futu-python-binding.svg", "富途适配器的 Python 绑定",
        "路线 A 和 IB 适配器一样：在富途适配器的配置和工厂类型上加 pyclass，在 src/python/mod.rs 的 pymodule 里登记类并向全局注册表登记工厂和配置的提取函数，"
        "在 crates/pyo3 里加可选依赖并用 wrap_pymodule 挂成 _libnautilus.futu，再由 python/nautilus_trader/adapters/futu 转出；用户在 Python 里把工厂和配置交给 LiveNode.builder 的 add_data_client，"
        "节点按工厂名和配置类名查注册表，得到 Rust 的工厂和配置对象。路线 B 是继承 nautilus_trader.live.clients 里的 Python 基类写纯 Python 客户端；路线 C 是独立的 Rust/PyO3 包。",
        664, b)


# ---------------------------------------------------------------------------
# 第 0 章 · PyO3 绑定：构建时怎样拼成一个模块，运行时一次调用怎样往返
# ---------------------------------------------------------------------------
def pyo3_binding():
    b = text(480, 36, "PyO3 绑定：左边是模块怎样拼起来，右边是一次调用怎样在两种语言之间往返", 19, INK, "bold", limit=920)
    # 左：构建时
    b += rect(24, 58, 436, 600, "orange", ORANGE, rx=14)
    b += text(40, 84, "构建时（make build-debug）", 16, ORANGE, "bold", "start")
    left = [
        ("① 各 crate 的 src/python/", "#[pyclass] / #[pymethods] / #[pyfunction]", "只在 python feature 下编译"),
        ("② #[pymodule] fn model(…)", "m.add_class::<Price>()", "m.add_function(wrap_pyfunction!(…))"),
        ("③ crates/pyo3/src/lib.rs", "#[pymodule] fn _libnautilus", "wrap_pymodule! + 写入 sys.modules"),
        ("④ maturin → 一个 .so", "_libnautilus.cpython-314-….so", "放在 python/nautilus_trader/ 下"),
        ("⑤ python/nautilus_trader/model/", "from …_libnautilus.model import *", "fixup_module_names；.pyi 由存根生成器写"),
    ]
    y = 100
    for i, (h, l1, l2) in enumerate(left):
        b += rect(40, y, 404, 92, "white", ORANGE, rx=9, width=1.3)
        b += text(56, y + 28, h, 15, INK, "bold", "start", mono=h.isascii(), limit=380)
        b += text(56, y + 52, l1, 14, GRAY, anchor="start", mono=l1.isascii(), limit=380)
        b += text(56, y + 74, l2, 14, GRAY, anchor="start", mono=l2.isascii(), limit=380)
        if i < len(left) - 1:
            b += arrow(242, y + 94, 242, y + 108, ORANGE, 1.5)
        y += 110
    # 右：运行时
    b += rect(480, 58, 456, 600, "blue", BLUE, rx=14)
    b += text(496, 84, "运行时：engine.add_data(quotes) 与 on_quote 回调", 16, BLUE, "bold", "start", limit=430)
    b += box(500, 100, 416, 56, ["Python：engine.add_data([QuoteTick, …])", "参数是 Python 对象的列表"], "white", BLUE, size=14)
    b += box(500, 180, 416, 74, ["PyO3 包装：PyBacktestEngine.py_add_data", "逐个 extract：QuoteTick? TradeTick? Bar? …", "→ Vec<Data>（每个元素复制一份）"], "white", BLUE, size=14)
    b += box(500, 278, 416, 56, ["Rust：BacktestEngine::add_data", "数据进入内核，之后全在 Rust 里流动"], "white", BLUE, size=14)
    b += arrow(708, 158, 708, 178, BLUE, 1.5)
    b += arrow(708, 256, 708, 276, BLUE, 1.5)
    b += rect(500, 356, 416, 2, "#94a3b8", "#94a3b8", rx=0, width=0)
    b += box(500, 374, 416, 56, ["Rust：engine.run() 主循环", "DataEngine 发布报价 → 策略的 handler"], "white", BLUE, size=14)
    b += box(500, 454, 416, 74, ["PyStrategyInner.dispatch_on_quote", "Python::attach（拿 GIL）", "quote.into_py_any → 新的 Python 对象"], "white", TEAL, size=14)
    b += box(500, 552, 416, 56, ["Python：MyStrategy.on_quote(quote)", "经 weakref 找到实例，按名字调用"], "white", TEAL, size=14)
    b += arrow(708, 432, 708, 452, TEAL, 1.5)
    b += arrow(708, 530, 708, 550, TEAL, 1.5)
    b += text(708, 636, "上半：Python → Rust 提取参数；下半：Rust → Python 回调", 14, GRAY, limit=430)
    svg("pyo3-binding.svg", "PyO3 绑定的构建与调用",
        "左边是构建时：各 crate 的 src/python 用 pyclass、pymethods、pyfunction 标注，再在 pymodule 函数里登记，crates/pyo3 的 _libnautilus 把这些子模块挂上去并写入 sys.modules，"
        "maturin 编成一个 .so，python/nautilus_trader 下的各模块再星号导入并修正模块名。右边是运行时：engine.add_data 把 Python 对象逐个提取成 Rust 的 Data，"
        "进入内核后全在 Rust 里流动；回测主循环里报价到达策略时，PyStrategyInner 拿 GIL、把报价转成新的 Python 对象，经弱引用调用 Python 子类的 on_quote。",
        680, b)


# ---------------------------------------------------------------------------
# 第 4 章 · 回调流程：一条报价到 on_quote，一笔成交到 on_order_filled / on_position_opened
# ---------------------------------------------------------------------------
def callback_flow():
    b = text(480, 36, "回调是怎样被调用的：都从总线发布开始，经订阅时登记的闭包，回到组件", 19, INK, "bold", limit=920)

    def column(x0, title, color, fill, steps, h=64, gap=18):
        out = rect(x0, 58, 448, 40 + len(steps) * (h + gap), fill, color, rx=14)
        out += text(x0 + 16, 84, title, 16, color, "bold", "start", limit=420)
        y = 100
        for i, (head, detail, hl) in enumerate(steps):
            stroke = ORANGE if hl else color
            out += rect(x0 + 14, y, 420, h, "#fde68a" if hl else "white", stroke, rx=9, width=1.4)
            out += text(x0 + 30, y + 26, head, 15, INK, "bold", "start", mono=head.isascii(), limit=396)
            out += text(x0 + 30, y + 50, detail, 14, GRAY, anchor="start", limit=396)
            if i < len(steps) - 1:
                out += arrow(x0 + 224, y + h + 2, x0 + 224, y + h + gap - 2, color, 1.5)
            y += h + gap
        return out

    left = [
        ("DataEngine.handle_quote", "先写缓存，再发布到 data.quotes.{venue}.{symbol}", False),
        ("MessageBus：TopicRouter<QuoteTick>", "按优先级派发：Portfolio（10）先于策略（0）", False),
        ("订阅时登记的闭包", "按 actor_id 从注册表取出组件", False),
        ("handle_quote（框架代码）", "先更新已注册的指标；组件不在 RUNNING 就丢弃", False),
        ("on_quote（你的代码）", "Rust 直接调用；Python 拿 GIL、转成新对象、按名字调用", True),
        ("出错时", "返回错误或抛异常只记日志，派发继续，节点不停", False),
    ]
    right = [
        ("ExecEngine.process(OrderFilled)", "执行客户端经 channel 送来的成交事件", False),
        ("更新缓存里的订单", "订单 apply 这笔成交，状态、已成交量、均价随之变化", False),
        ("handle_order_fill", "通知 Portfolio；开仓或更新仓位写进缓存", False),
        ("发布 events.order.{strategy_id}", "Portfolio（10）先收到；再到 Trader 注册时订阅的策略", False),
        ("on_order_filled → on_order_event", "先具体回调，再通用回调；此时缓存里的仓位已更新", True),
        ("发布 events.position.{strategy_id}", "on_position_opened 等 → on_position_event", True),
    ]
    b += column(24, "一条报价 → on_quote", BLUE, "blue", left)
    b += column(488, "一笔成交 → on_order_filled、on_position_opened", TEAL, "teal", right)
    b += text(480, 620, "橙色框是你写的回调；其余都是框架代码。两条路都在核心线程上同步执行，回调返回后派发才继续。", 14, GRAY, limit=920)
    svg("callback-flow.svg", "回调的调用流程",
        "左边是报价：DataEngine 先写缓存再发布到行情主题，MessageBus 按优先级派发，Portfolio 先于策略；订阅时登记的闭包从注册表取出组件，"
        "handle_quote 先更新指标、检查组件是否在运行，再调用 on_quote；Python 策略在这里拿 GIL 并按名字调用；出错只记日志。"
        "右边是成交：执行引擎更新缓存里的订单，处理仓位，然后发布订单事件，策略先收到 on_order_filled 再收到 on_order_event，"
        "最后发布仓位事件，触发 on_position_opened 等回调。",
        640, b)


# ---------------------------------------------------------------------------
# 第 4 章 · Rust 策略的组成：你写的、宏生成的、框架提供的
# ---------------------------------------------------------------------------
def rust_strategy():
    b = text(480, 36, "一个 Rust 策略由三部分拼成：你写的结构体和回调、宏生成的样板、框架的默认实现", 19, INK, "bold", limit=920)
    cols = [
        (24, "你写的", ORANGE, "orange", [
            ("struct EmaCross", "core: StrategyCore", "+ 指标、参数、自己的状态"),
            ("impl DataActor for EmaCross", "on_start / on_quote / on_stop …", "只覆盖需要的回调"),
            ("（可选）宏的花括号里", "覆盖 Strategy 的方法", "如 on_order_filled"),
        ]),
        (334, "nautilus_strategy! 宏生成", BLUE, "blue", [
            ("impl DataActorNative", "core() / core_mut()", "启动时先跑框架的 on_start"),
            ("impl StrategyNative", "strategy_core() / _mut()", "由此拿到下单工厂、组合"),
            ("impl Strategy {}", "空实现，全用默认方法", "外加 config() 访问器"),
        ]),
        (644, "框架提供（默认方法与通用实现）", TEAL, "teal", [
            ("impl<T> Component for T", "任何 DataActor 自动获得", "生命周期状态机"),
            ("DataActor 的默认方法", "subscribe_* / request_*", "以及派发前检查 handle_*"),
            ("Strategy 的默认方法", "submit_order / cancel_order …", "handle_order_event 等"),
        ]),
    ]
    for x, title, color, fill, items in cols:
        b += rect(x, 58, 292, 352, fill, color, rx=14)
        b += text(x + 146, 86, title, 16, color, "bold", limit=270)
        y = 104
        for h, l1, l2 in items:
            b += rect(x + 14, y, 264, 92, "white", color, rx=9, width=1.3)
            b += text(x + 146, y + 28, h, 15, INK, "bold", mono=h.isascii(), limit=252)
            b += text(x + 146, y + 52, l1, 14, GRAY, mono=l1.isascii(), limit=252)
            b += text(x + 146, y + 74, l2, 14, GRAY, mono=l2.isascii(), limit=252)
            y += 100
    # StrategyCore 组成
    b += rect(24, 430, 912, 150, "gray", INK, rx=14)
    b += text(44, 458, "StrategyCore（crates/trading/src/strategy/core.rs）注册之后才完整", 16, INK, "bold", "start", limit=880)
    parts = [("DataActorCore", "状态、时钟、订阅表"), ("OrderFactory", "生成订单和订单号"),
             ("OrderManager", "关联订单 OCO / OTO"), ("Portfolio", "净头寸、盈亏查询"), ("计时器", "GTD 过期、市场退出")]
    x = 40
    for name, desc in parts:
        b += rect(x, 476, 168, 84, "white", INK, rx=9, width=1.2)
        b += text(x + 84, 508, name, 15, INK, "bold", mono=name.isascii(), limit=156)
        b += text(x + 84, 534, desc, 14, GRAY, limit=156)
        x += 178
    svg("rust-strategy.svg", "Rust 策略的组成",
        "左边是你写的部分：持有 StrategyCore 的结构体、覆盖回调的 impl DataActor，以及可选地在宏里覆盖 Strategy 的方法。"
        "中间是 nautilus_strategy! 宏生成的 DataActorNative、StrategyNative 和空的 impl Strategy。右边是框架提供的通用实现和默认方法："
        "任何 DataActor 自动实现 Component，DataActor 和 Strategy 的订阅、下单、派发方法都有默认实现。下方是 StrategyCore 的组成，"
        "DataActorCore、OrderFactory、OrderManager、Portfolio 和计时器在注册到 Trader 时才接上。",
        600, b)



# ---------------------------------------------------------------------------
# 第 6 章 · 图 1：一次 subscribe_bars 和一笔成交怎样变成 on_bar
# ---------------------------------------------------------------------------
def bar_aggregation_flow():
    b = text(480, 36, "K 线在 Rust 的 DataEngine 里合成：订阅时建聚合器，运行时逐笔喂进去", 19, INK, "bold", limit=920)
    # 上半：订阅时
    b += rect(24, 58, 912, 150, "gray", GRAY, rx=14)
    b += text(44, 84, "订阅时：一次 subscribe_bars(…-1-MINUTE-LAST-INTERNAL)", 16, INK, "bold", "start", limit=880)
    sub = [
        ("策略 subscribe_bars", "Rust 或 Python 都一样", "发 SubscribeBars 命令"),
        ("DataEngine", "来源是 INTERNAL", "不转给数据客户端"),
        ("建聚合器", "按标准 BarType 只建一份", "多个订阅者共享"),
        ("向客户端订阅源数据", "LAST 订成交", "BID/ASK/MID 订报价"),
    ]
    x = 40
    for i, (h, l1, l2) in enumerate(sub):
        b += box(x, 100, 204, 92, [h, l1, l2], "white", GRAY, 15, mono_from=9)
        if i < 3:
            b += arrow(x + 206, 146, x + 226, 146, GRAY)
        x += 224
    # 下半：运行时
    b += rect(24, 226, 912, 376, "blue", BLUE, rx=14)
    b += text(44, 252, "运行时：一笔成交怎样变成 on_bar（全程在核心线程上同步执行）", 16, BLUE, "bold", "start", limit=880)
    row1 = [
        ("DataEngine 收到成交", "来自客户端或回测数据流", "先写 Cache，再发布"),
        ("总线 data.trades.*", "按优先级从高到低派发", "聚合器 5 先于策略 0"),
        ("BarTradeHandler", "订阅时登记的处理器", "弱引用找到聚合器"),
        ("BarAggregator", "BarBuilder 累计 OHLCV", "满足关闭条件就 build"),
    ]
    x = 40
    for i, (h, l1, l2) in enumerate(row1):
        hl = i == 3
        b += box(x, 300, 204, 92, [h, l1, l2], "#dbeafe" if hl else "white", BLUE, 15, mono_from=9)
        if i < 3:
            b += arrow(x + 206, 346, x + 226, 346, BLUE)
        x += 224
    # 时间 K 线的定时器
    b += box(712, 410, 204, 56, ["时钟定时器 TIME_BAR_…", "到点调用 build_bar"], "white", TEAL, 14, mono_from=9, dash=True)
    b += arrow(814, 410, 814, 394, TEAL, dash=True)
    row2 = [
        ("on_bar（你的代码）", "Rust 直接调用", "Python 拿 GIL 按名字调用"),
        ("handle_bar（框架）", "先更新注册的指标", "组件不在 RUNNING 就丢弃"),
        ("总线 data.bars.{类型}", "主题用标准 BarType", "组合 K 线也去掉 @ 部分"),
        ("process_engine_bar", "可选的时间戳顺序检查", "写 Cache，再发布"),
    ]
    x = 40
    for i, (h, l1, l2) in enumerate(row2):
        hl = i == 0
        b += box(x, 486, 204, 92, [h, l1, l2], "#fde68a" if hl else "white", ORANGE if hl else BLUE, 15, mono_from=9)
        if i < 3:
            b += arrow(x + 226, 532, x + 206, 532, BLUE)
        x += 224
    b += poly_arrow([(712 + 102 + 120, 346), (926, 346), (926, 532), (918, 532)], BLUE)
    b += text(480, 628, "聚合器的优先级（5）高于策略（0）：凑满一根 K 线的那笔成交，策略先收到 on_bar，再收到这笔成交的 on_trade_tick。", 14, GRAY, limit=920)
    svg("bar-aggregation-flow.svg", "K 线聚合的订阅与数据流",
        "上半部分是订阅时：策略调用 subscribe_bars 订阅一个 INTERNAL 的 K 线类型，DataEngine 不把它转给数据客户端，而是按标准 BarType 建一个共享的聚合器，"
        "再向客户端订阅源数据：LAST 订阅成交，BID、ASK、MID 订阅报价，组合 K 线订阅 @ 后面的源 K 线。"
        "下半部分是运行时：成交发布到 data.trades 主题，按优先级先到 Portfolio、再到聚合器的处理器、最后到策略；聚合器用 BarBuilder 累计开高低收和成交量，"
        "满足关闭条件或时间 K 线的定时器到点时生成 K 线，process_engine_bar 写入缓存并发布到 data.bars 主题，策略的 handle_bar 先更新指标，再调用 on_bar。",
        650, b)


# ---------------------------------------------------------------------------
# 第 6 章 · 图 2：一个 BarBuilder，七种关闭规则
# ---------------------------------------------------------------------------
def bar_aggregators():
    b = text(480, 36, "所有聚合器共用一个 BarBuilder，区别只在“什么时候关闭这根 K 线”", 19, INK, "bold", limit=920)
    b += rect(300, 58, 360, 92, "gray", INK, rx=12)
    b += text(480, 86, "BarBuilder（每根 K 线的累加器）", 16, INK, "bold", limit=340)
    b += text(480, 112, "open/high/low/close · volume · count", 14, GRAY, mono=True, limit=340)
    b += text(480, 136, "ts_init 比上一笔早就忽略；空 K 线用上一收盘价补", 14, GRAY, limit=340)
    b += text(480, 174, "下面每个聚合器的 BarAggregatorCore 里都有一个 BarBuilder，加上各自的关闭规则", 14, GRAY, limit=920)
    cards = [
        ("TickBarAggregator", "成交笔数 count ≥ step", "250-TICK → 279 根", BLUE),
        ("VolumeBarAggregator", "成交量凑满 step，大单拆进两根", "100-VOLUME → 1912 根", BLUE),
        ("ValueBarAggregator", "成交额 价×量 累计到 step", "50000-VALUE → 1627 根", BLUE),
        ("…ImbalanceBarAggregator", "买 +1、卖 −1，|和| ≥ step", "100-TICK_IMBALANCE → 65 根", TEAL),
        ("…RunsBarAggregator", "同方向连续 step 笔，换向重来", "20-TICK_RUNS → 247 根", TEAL),
        ("RenkoBarAggregator", "价格离上一块收盘 ≥ 砖块大小", "50-RENKO → 158 根", ORANGE),
        ("TimeBarAggregator", "时钟定时器到点，不看数据", "1-MINUTE → 299 根", ORANGE),
        ("组合：…@1-MINUTE-INTERNAL", "源是更小的 K 线", "5-MINUTE → 59 根", ORANGE),
    ]
    for i, (name, rule, run, color) in enumerate(cards):
        col, row = i % 4, i // 4
        x = 24 + col * 230
        y = 186 + row * 150
        b += rect(x, y, 220, 132, "white", color, rx=10, width=1.4)
        b += text(x + 110, y + 30, name, 14, color, "bold", mono=name.isascii(), limit=208)
        b += text(x + 110, y + 62, rule, 14, INK, limit=208)
        b += text(x + 110, y + 100, run, 14, GRAY, limit=208)
    b += text(480, 506, "蓝：阈值类　青：信息驱动类（需要成交的主动方向）　橙：按价格或按时间", 14, GRAY, limit=920)
    b += text(480, 530, "根数是本章实验：ETHUSDT.BINANCE 69,806 笔成交，2020-08-14 10:00–15:00 UTC", 14, GRAY, limit=920)
    svg("bar-aggregators.svg", "BarBuilder 与七种聚合器",
        "上面是所有聚合器共用的 BarBuilder，记录开高低收、成交量和笔数。下面八张卡片是不同的关闭规则："
        "按笔数、按成交量（大单会被拆进两根）、按成交额、按主动买卖的净失衡、按同方向连续成交、按价格移动的 Renko 砖块、按时钟的时间 K 线，"
        "以及用更小的 K 线合成大 K 线的组合方式。每张卡片下面写着本章实验得到的根数。",
        560, b)



# ---------------------------------------------------------------------------
# 第 7 章 · 指标：注册表与一根 K 线的更新路径
# ---------------------------------------------------------------------------
def indicator_flow():
    b = text(480, 36, "指标挂在组件的 Indicators 表上，每根 K 线先更新指标、再调用 on_bar", 19, INK, "bold", limit=920)
    # 注册表
    b += rect(24, 58, 912, 168, "gray", GRAY, rx=14)
    b += text(44, 84, "注册：DataActorCore 里的 Indicators（crates/common/src/actor/indicators.rs）", 16, INK, "bold", "start", limit=880)
    tables = [
        ("indicators", "全部已注册的指标", "按对象地址去重"),
        ("indicators_for_quotes", "键：InstrumentId", "register_…_quote_ticks"),
        ("indicators_for_trades", "键：InstrumentId", "register_…_trade_ticks"),
        ("indicators_for_bars", "键：(品种, K 线规格)", "不含来源 INTERNAL/EXTERNAL"),
    ]
    x = 40
    for h, l1, l2 in tables:
        b += box(x, 100, 208, 108, [h, l1, l2], "white", GRAY, 15, mono_from=9)
        x += 224
    # 更新路径
    b += rect(24, 244, 912, 372, "blue", BLUE, rx=14)
    b += text(44, 270, "一根 K 线到达组件：handle_bar（框架代码）", 16, BLUE, "bold", "start", limit=880)
    b += box(40, 290, 300, 64, ["Indicators::handle_bar", "按 (品种, 规格) 找出这一组指标"], "white", BLUE, 15, mono_from=9)
    b += arrow(342, 322, 380, 322, BLUE)
    # Rust 路
    b += rect(384, 286, 536, 108, "white", TEAL, rx=10, width=1.4)
    b += text(400, 310, "Rust 指标：Rc<RefCell<T>>，T 实现 Indicator", 15, TEAL, "bold", "start", limit=510)
    b += text(400, 338, "borrow_mut().handle_bar(&bar) → 直接改结构体里的 f64", 14, INK, anchor="start", limit=510)
    b += text(400, 364, "要打开 nautilus-common 的 indicators 特性", 14, GRAY, anchor="start", limit=510)
    # Python 路
    b += rect(384, 404, 536, 132, "white", ORANGE, rx=10, width=1.4)
    b += text(400, 428, "Python 注册的指标：包成 PyActorIndicator", 15, ORANGE, "bold", "start", limit=510)
    b += text(400, 456, "拿 GIL → Bar 转成新的 Python 对象", 14, INK, anchor="start", limit=510)
    b += text(400, 482, "→ call_method1(\"handle_bar\") 按名字调用", 14, INK, anchor="start", limit=510)
    b += text(400, 508, "内置指标再经 PyO3 回到 Rust；纯 Python 类就在 Python 里算", 14, GRAY, anchor="start", limit=510)
    b += poly_arrow([(360, 322), (360, 470), (382, 470)], BLUE)
    # 之后
    b += box(40, 380, 300, 64, ["任一指标出错", "记日志，这根 K 线不再调用 on_bar"], "#fee2e2", RED, 14, mono_from=9)
    b += box(40, 460, 300, 64, ["组件不在 RUNNING", "指标照样更新，on_bar 不调用"], "white", BLUE, 14, mono_from=9)
    b += box(40, 540, 300, 60, ["on_bar（你的代码）", "读 indicator.value"], "#fde68a", ORANGE, 15, mono_from=9)
    for y1, y2 in [(354, 378), (444, 458), (524, 538)]:
        b += arrow(190, y1, 190, y2, BLUE)
    b += box(384, 552, 536, 48, ["历史响应 on_historical_bars 之前也先更新指标"], "white", BLUE, 14, mono_from=9)
    b += text(480, 642, "注册不会订阅数据，也不会在 reset 时清空指标：订阅要另外调用 subscribe_*，清空要在 on_reset 里自己做。", 14, GRAY, limit=920)
    svg("indicator-flow.svg", "指标的注册表与更新路径",
        "上半部分是组件里的 Indicators：一个保存全部指标的列表，以及按品种分的报价、成交两张表和按品种加 K 线规格分的 K 线表，K 线表的键不含聚合来源。"
        "下半部分是一根 K 线到达时：框架先按品种和规格找出指标逐个更新。Rust 指标以 Rc<RefCell<T>> 注册，直接调用 handle_bar；"
        "Python 注册的指标被包成 PyActorIndicator，每次都要拿 GIL、把 K 线转成 Python 对象、按名字调用 handle_bar。"
        "任一指标出错就记日志并跳过 on_bar；组件不在运行状态时指标照样更新但不调用 on_bar；最后才调用你的 on_bar。",
        670, b)



# ---------------------------------------------------------------------------
# 第 2 章 · 一行成交拆成六个值
# ---------------------------------------------------------------------------
def value_types_trade():
    b = text(480, 36, "一行成交记录在内存里是什么：定点整数、驻留字符串、栈上字符串和 u64 纳秒", 19, INK, "bold", limit=920)
    b += rect(24, 58, 912, 70, "gray", GRAY, rx=12)
    b += text(44, 84, "CSV 原文（test_data/binance/ethusdt-trades.csv 第 1 行）", 15, INK, "bold", "start", limit=880)
    b += text(44, 112, "2020-08-14 10:00:00.223000+00:00,148568980,423.76,2.67900,True", 15, GRAY, anchor="start", mono=True, limit=880)
    b += arrow(480, 130, 480, 156, BLUE)
    b += text(492, 150, "TradeTick", 15, BLUE, "bold", "start", mono=True)
    cells = [
        ("InstrumentId", "ETHUSDT.BINANCE", "Symbol + Venue", "两个 Ustr 句柄", BLUE),
        ("Price", "423.76（precision 2）", "HP raw 4237600000000000000", "std raw 423760000000", ORANGE),
        ("Quantity", "2.67900（precision 5）", "HP raw 26790000000000000", "std raw 2679000000", ORANGE),
        ("AggressorSide", "SELL", "buyer_maker = True", "主动方是卖方", BLUE),
        ("TradeId", "148568980", "StackStr，最多 36 字符", "不进全局字符串表", TEAL),
        ("UnixNanos", "1597399200223000000", "2020-08-14T10:00:00.223Z", "ts_event = ts_init", TEAL),
    ]
    for i, (t, v, l1, l2, c) in enumerate(cells):
        col, row = i % 3, i // 3
        x = 24 + col * 308
        y = 166 + row * 150
        b += rect(x, y, 296, 132, "white", c, rx=10, width=1.4)
        b += text(x + 148, y + 30, t, 16, c, "bold", mono=True, limit=280)
        b += text(x + 148, y + 60, v, 15, INK, mono=v.isascii(), limit=280)
        b += text(x + 148, y + 88, l1, 14, GRAY, mono=l1.isascii(), limit=280)
        b += text(x + 148, y + 114, l2, 14, GRAY, mono=l2.isascii(), limit=280)
    b += rect(24, 470, 912, 74, "orange", ORANGE, rx=12)
    b += text(480, 498, "名义金额 Money：423.76 × 2.679 = 1135.25304000 USDT", 16, INK, "bold", limit=880)
    b += text(480, 526, "Money 没有自己的精度字段，跟着币种 USDT 的精度 8 显示", 14, GRAY, limit=880)
    b += text(480, 574, "HP = 高精度模式，raw = 数值 × 10^16；std = 标准模式，raw = 数值 × 10^9。放大倍数是全局的，和这个值自己的精度无关。", 14, GRAY, limit=920)
    svg("value-types-trade.svg", "一行成交拆成六个值",
        "上面是测试数据 CSV 的第一行，下面是它变成的 TradeTick 的六个字段：品种 ID 由两个驻留字符串组成；价格 423.76 和数量 2.679 都存成全局倍数放大的整数，"
        "高精度模式下分别是 4237600000000000000 和 26790000000000000，标准模式下是 423760000000 和 2679000000；主动方是卖方；成交 ID 是栈上定长字符串；"
        "时间是 u64 纳秒。最下面是这笔成交的名义金额 1135.25304000 USDT，精度来自币种。",
        600, b)



# ---------------------------------------------------------------------------
# 第 3 章 · 一个价格从策略走到交易所
# ---------------------------------------------------------------------------
def instrument_price_path():
    b = text(480, 36, "一个价格从策略走到交易所：每一站检查什么、不检查什么", 19, INK, "bold", limit=920)
    stations = [
        ("策略算出 f64", ["1.03", "（增量 0.05 的期权）"], ORANGE, "orange"),
        ("make_price", ["转十进制，银行家舍入", "只舍到 2 位小数 → 1.03"], BLUE, "blue"),
        ("RiskEngine", ["精度 ≤ 2 ✓", "min/max 价格 ✓"], BLUE, "blue"),
        ("交易所", ["1.03 不是 0.05 的倍数", "拒单"], RED, "#fee2e2"),
    ]
    x = 24
    for i, (h, lines, c, fill) in enumerate(stations):
        b += rect(x, 70, 210, 120, fill, c, rx=12, width=1.5)
        b += text(x + 105, 102, h, 16, c, "bold", mono=h.isascii(), limit=196)
        b += text(x + 105, 134, lines[0], 14, INK, mono=lines[0].isascii(), limit=196)
        b += text(x + 105, 162, lines[1], 14, GRAY, mono=lines[1].isascii(), limit=196)
        if i < 3:
            b += arrow(x + 212, 130, x + 232, 130, BLUE)
        x += 234
    b += rect(258, 206, 444, 64, "#fee2e2", RED, rx=10, width=1.3, dash=True)
    b += text(480, 232, "缝隙：风控不检查增量的整数倍，也不检查 lot_size", 15, RED, "bold", limit=430)
    b += text(480, 256, "make_price 的结果可以过风控、却被交易所拒绝", 14, INK, limit=430)
    b += rect(24, 290, 912, 150, "teal", TEAL, rx=14)
    b += text(44, 318, "要严格对齐，用这两个方法", 16, TEAL, "bold", "start", limit=880)
    b += box(44, 336, 420, 88, ["next_bid_price(1.03, 0) → 1.00", "next_ask_price(1.03, 0) → 1.05", "有价位表按价位表，没有就按增量对齐"], "white", TEAL, 15, mono_from=1)
    b += box(496, 336, 420, 88, ["try_normalize_price(1.03)", "→ 错误：not aligned to price increment", "适合在适配器边界做最后检查"], "white", TEAL, 15, mono_from=1)
    b += text(480, 470, "make_qty 同理：只舍到 size_increment 的小数位；正数舍成 0 时报错；round_down=true 时向零截断。", 14, GRAY, limit=920)
    svg("instrument-price-path.svg", "一个价格从策略走到交易所",
        "上面一行是一个期权价格 1.03 的路径：策略算出浮点数，make_price 按两位小数舍入后仍是 1.03，RiskEngine 只检查精度和价格上下限所以放行，"
        "交易所因为 1.03 不是最小变动价位 0.05 的倍数而拒单。中间的红框标出风控不检查增量整数倍和整手的缝隙。"
        "下面是两种严格对齐的办法：next_bid_price 和 next_ask_price 分别得到 1.00 和 1.05，try_normalize_price 对未对齐的价格直接报错。",
        500, b)



# ---------------------------------------------------------------------------
# 第 4 章 · 二档订单簿的四个状态
# ---------------------------------------------------------------------------
def book_deltas():
    b = text(480, 36, "一本 L2_MBP 簿依次应用四组增量：每一步之后的盘口", 19, INK, "bold", limit=920)
    states = [
        ("① 快照", "CLEAR + 4×ADD",
         [("423.90", "4.0", ""), ("423.80", "2.0", "")],
         [("423.70", "5.0", ""), ("423.60", "3.0", "")],
         "价差 0.10　中间价 423.75"),
        ("② UPDATE", "BUY 423.70 × 1.5",
         [("423.90", "4.0", ""), ("423.80", "2.0", "")],
         [("423.70", "1.5", "hl"), ("423.60", "3.0", "")],
         "价差 0.10　买一量 1.5"),
        ("③ DELETE", "SELL 423.80",
         [("423.90", "4.0", ""), ("423.80", "—", "del")],
         [("423.70", "1.5", ""), ("423.60", "3.0", "")],
         "价差 0.20　中间价 423.80"),
        ("④ UPDATE", "BUY 423.65 × 2.0",
         [("423.90", "4.0", "")],
         [("423.70", "1.5", ""), ("423.65", "2.0", "hl"), ("423.60", "3.0", "")],
         "不存在的价位：等于新增"),
    ]
    for i, (title, sub, asks, bids, note) in enumerate(states):
        x = 24 + i * 230
        b += rect(x, 58, 218, 420, "white", GRAY, rx=12)
        b += text(x + 109, 86, title, 16, INK, "bold", limit=200)
        b += text(x + 109, 110, sub, 14, BLUE, mono=True, limit=204)
        b += text(x + 20, 140, "卖盘", 14, RED, "bold", "start")
        y = 152
        for px, qty, st in asks:
            fill = "#fde68a" if st == "hl" else ("#f1f5f9" if st == "del" else "#fef2f2")
            stroke = ORANGE if st else RED
            b += rect(x + 16, y, 186, 34, fill, stroke, rx=6, width=1.2, dash=(st == "del"))
            b += text(x + 30, y + 23, px, 15, GRAY if st == "del" else INK, anchor="start", mono=True)
            b += text(x + 188, y + 23, qty if st != "del" else "删除", 15, GRAY if st == "del" else INK, anchor="end", mono=(st != "del"))
            y += 40
        y = max(y, 232) + 8
        b += text(x + 20, y + 4, "买盘", 14, TEAL, "bold", "start")
        y += 16
        for px, qty, st in bids:
            fill = "#fde68a" if st == "hl" else "#f0fdfa"
            stroke = ORANGE if st else TEAL
            b += rect(x + 16, y, 186, 34, fill, stroke, rx=6, width=1.2)
            b += text(x + 30, y + 23, px, 15, INK, anchor="start", mono=True)
            b += text(x + 188, y + 23, qty, 15, INK, anchor="end", mono=True)
            y += 40
        b += text(x + 109, 456, note, 14, GRAY, limit=204)
        if i < 3:
            b += arrow(x + 219, 270, x + 229, 270, BLUE)
    b += text(480, 510, "橙色是这一步动过的档位。L2_MBP 簿按价格改写订单号，所以“更新一个不存在的订单”会落到新增分支；数量为 0 的更新等于删除。", 14, GRAY, limit=920)
    svg("book-deltas.svg", "二档订单簿的四个状态",
        "四列分别是一本 ETHUSDT 二档簿在快照、更新买一数量、删除卖一、更新一个不存在的买价之后的状态。快照后最优买卖价是 423.70 和 423.80，价差 0.10；"
        "更新后买一数量变成 1.5；删除 423.80 后最优卖价变成 423.90，价差扩大到 0.20；最后一条更新在簿里新增了 423.65 这一档。",
        540, b)



# ---------------------------------------------------------------------------
# 第 5 章 · 订单状态机
# ---------------------------------------------------------------------------
def order_state_machine():
    b = text(480, 36, "订单状态机：15 个状态，颜色说明订单在哪里", 19, INK, "bold", limit=920)
    W, H = 168, 50
    xs = [24, 210, 396, 582, 768]
    def st(x, y, name, kind):
        color, fill = {"local": (BLUE, "blue"), "open": (TEAL, "teal"), "closed": (GRAY, "gray")}[kind]
        out = rect(x, y, W, H, fill, color, rx=10, width=1.6)
        out += text(x + W / 2, y + 31, name, 14, color, "bold", mono=True, limit=W - 8)
        return out
    y1, y2, y3 = 80, 210, 360
    row1 = [("INITIALIZED", "local"), ("SUBMITTED", "local"), ("ACCEPTED", "open"), ("PARTIALLY_FILLED", "open"), ("FILLED", "closed")]
    for x, (n, k) in zip(xs, row1):
        b += st(x, y1, n, k)
    for i in range(4):
        b += arrow(xs[i] + W + 2, y1 + 25, xs[i + 1] - 2, y1 + 25, BLUE, 2)
    labels = ["Submitted", "Accepted", "Filled（部分）", "Filled（满）"]
    for i, l in enumerate(labels):
        b += text((xs[i] + W + xs[i + 1]) / 2, y1 - 8, l, 14, BLUE, limit=120)
    row2 = [("EMULATED", "local"), ("RELEASED", "local"), ("TRIGGERED", "open"), ("PENDING_UPDATE", "open"), ("PENDING_CANCEL", "open")]
    for x, (n, k) in zip(xs, row2):
        b += st(x, y2, n, k)
    b += arrow(xs[0] + W / 2, y1 + H + 2, xs[0] + W / 2, y2 - 2, BLUE)
    b += text(xs[0] + W / 2 + 8, (y1 + H + y2) / 2 + 5, "Emulated", 14, BLUE, anchor="start")
    b += arrow(xs[0] + W + 2, y2 + 25, xs[1] - 2, y2 + 25, BLUE)
    b += arrow(xs[1] + W / 2, y2 - 2, xs[1] + W / 2, y1 + H + 2, BLUE)
    b += text(xs[1] + W / 2 + 8, (y1 + H + y2) / 2 + 5, "Submitted", 14, BLUE, anchor="start")
    b += arrow(xs[2] + W / 2, y1 + H + 2, xs[2] + W / 2, y2 - 2, TEAL)
    b += text(xs[2] + W / 2 + 8, (y1 + H + y2) / 2 + 5, "Triggered", 14, TEAL, anchor="start")
    b += arrow(xs[3] + W / 2, y1 + H + 2, xs[3] + W / 2, y2 - 2, TEAL, both=True)
    b += text(xs[3] + W / 2 - 8, (y1 + H + y2) / 2 + 5, "改单", 14, TEAL, anchor="end")
    b += arrow(xs[3] + W - 16, y1 + H + 2, xs[4] + 24, y2 - 2, TEAL, both=True)
    b += text(xs[4] + 40, (y1 + H + y2) / 2 + 5, "撤单", 14, TEAL, anchor="start")
    b += rect(24, 290, 912, 46, "white", GRAY, rx=8, width=1, dash=True)
    b += text(480, 319, "下面五个终态（加上 FILLED 共六个）可以从多个非终态到达；箭头太多，这里只列主要来源", 14, GRAY, limit=880)
    row3 = [("DENIED", "INITIALIZED、RELEASED", "风控拒绝"), ("REJECTED", "SUBMITTED、ACCEPTED…", "交易所拒绝"),
            ("CANCELED", "多数在途和挂单状态", "IOC/FOK 也走这里"), ("EXPIRED", "ACCEPTED、TRIGGERED…", "GTD 到期等"),
            ("VOIDED", "FILLED", "成交被撤销")]
    for x, (n, src, why) in zip(xs, row3):
        b += st(x, y3, n, "closed")
        b += text(x + W / 2, y3 + H + 24, src, 14, INK, limit=W + 10)
        b += text(x + W / 2, y3 + H + 46, why, 14, GRAY, limit=W + 10)
    b += rect(24, 488, 912, 56, "orange", ORANGE, rx=10)
    b += text(480, 512, "照着真实交易所写的几条：外部订单可从 INITIALIZED 直接到 ACCEPTED；CANCELED、EXPIRED 之后仍可 FILLED；", 14, INK, limit=890)
    b += text(480, 534, "改撤单被拒时回到 previous_status；ModifyDenied、CancelDenied 在任何状态下都不改变状态。", 14, INK, limit=890)
    b += text(480, 572, "蓝：在本地或在路上（既不 open 也不 closed）　青：挂在交易所（is_open）　灰：已结束（is_closed）", 14, GRAY, limit=920)
    svg("order-state-machine.svg", "订单状态机",
        "最上面一行是主路径：INITIALIZED、SUBMITTED、ACCEPTED、PARTIALLY_FILLED、FILLED。第二行是分支：本地仿真单从 INITIALIZED 进入 EMULATED、"
        "再经 RELEASED 回到 SUBMITTED；触发类订单从 ACCEPTED 进入 TRIGGERED；改单和撤单请求进入 PENDING_UPDATE、PENDING_CANCEL 并可能回到原状态。"
        "第三行是终态 DENIED、REJECTED、CANCELED、EXPIRED、VOIDED 及其主要来源。底部注明几条照着真实交易所行为设计的转移。",
        600, b)



# ---------------------------------------------------------------------------
# 第 6 章 · 同一串成交在 NETTING 和 HEDGING 下的去向
# ---------------------------------------------------------------------------
def positions_oms():
    b = text(480, 36, "三笔成交在两种订单管理模式下的去向", 19, INK, "bold", limit=920)
    fills = ["F1  BUY 1 @ 420", "F2  BUY 1 @ 430", "F3  SELL 3 @ 440"]
    for i, f in enumerate(fills):
        b += box(24 + i * 304, 58, 288, 44, [f], "white", GRAY, 15, mono_from=9)
    # NETTING lane
    b += rect(24, 120, 912, 210, "blue", BLUE, rx=14)
    b += text(44, 146, "NETTING：一个仓位，ID = ETHUSDT.BINANCE-EMACross-001", 16, BLUE, "bold", "start", limit=880)
    b += box(44, 164, 260, 70, ["多 1　均价 420", "已实现 -0.42"], "white", BLUE, 15, mono_from=9)
    b += arrow(306, 199, 334, 199, BLUE)
    b += box(336, 164, 260, 70, ["多 2　均价 425", "已实现 -0.85"], "white", BLUE, 15, mono_from=9)
    b += arrow(598, 199, 626, 199, BLUE)
    b += rect(628, 160, 292, 158, "white", ORANGE, rx=10, width=1.5)
    b += text(774, 184, "F3 被拆成两笔", 15, ORANGE, "bold", limit=280)
    b += text(774, 210, "平 2 @ 440，手续费 0.88", 14, INK, limit=280)
    b += text(774, 232, "→ FLAT，已实现 28.27，存快照", 14, INK, limit=280)
    b += text(774, 262, "开 1 @ 440，手续费 0.44", 14, INK, limit=280)
    b += text(774, 284, "→ 同一 ID 新一轮：空 1", 14, INK, limit=280)
    b += text(774, 306, "已实现重置为 -0.44", 14, GRAY, limit=280)
    b += text(44, 268, "加仓：成本相加、加权平均", 14, GRAY, anchor="start", limit=560)
    b += text(44, 292, "减仓：按比例分摊成本，440 × 2 - 850 = 30，再减手续费", 14, GRAY, anchor="start", limit=560)
    # HEDGING lane
    b += rect(24, 348, 912, 160, "teal", TEAL, rx=14)
    b += text(44, 374, "HEDGING（三张单都不指定仓位）：三个仓位，互不轧差", 16, TEAL, "bold", "start", limit=880)
    hs = [("P-…-1", "多 1　均价 420"), ("P-…-2", "多 1　均价 430"), ("P-…-3", "空 3　均价 440")]
    for i, (pid, l) in enumerate(hs):
        b += box(44 + i * 296, 392, 276, 70, [pid, l], "white", TEAL, 15, mono_from=9)
    b += text(480, 490, "净敞口同样是空 1，但没有任何仓位被平掉，也没有已实现的价差盈亏", 14, INK, limit=880)
    b += text(480, 540, "手续费 0.1%，以 USDT 收取，直接计入已实现盈亏；数字单位 USDT。", 14, GRAY, limit=920)
    svg("positions-oms.svg", "同一串成交在 NETTING 和 HEDGING 下的去向",
        "上面是三笔成交：买 1 @ 420、买 1 @ 430、卖 3 @ 440。NETTING 泳道里只有一个固定 ID 的仓位，前两笔成交后是多 2、均价 425、已实现 -0.85；"
        "第三笔被拆成平 2 和开 1，平仓后已实现 28.27 并存入快照，同一 ID 开始新一轮空 1，已实现重置为 -0.44。HEDGING 泳道里三笔成交各自成为一个仓位，"
        "两个多 1、一个空 3，净敞口相同但互不轧差。",
        570, b)



# ---------------------------------------------------------------------------
# 第 7 章 · 现金账户的四个时刻
# ---------------------------------------------------------------------------
def account_balances():
    b = text(480, 36, "现金账户（多币种）在四个时刻的余额：总额 / 冻结 / 可用", 19, INK, "bold", limit=920)
    cols = [
        ("① 初始", "", [("1,000,000", "0", "1,000,000", ""), ("10", "0", "10", "")]),
        ("② 挂买单", "BUY 1 @ 423.50", [("1,000,000", "423.50", "999,576.50", "hl"), ("10", "0", "10", "")]),
        ("③ 买单成交", "手续费 0.4235", [("999,576.0765", "0", "999,576.0765", "hl"), ("11", "0", "11", "hl")]),
        ("④ 挂卖单", "SELL 5 @ 430.00", [("999,576.0765", "0", "999,576.0765", ""), ("11", "5", "6", "hl")]),
    ]
    b += text(60, 150, "USDT", 16, BLUE, "bold", "start", mono=True)
    b += text(60, 300, "ETH", 16, TEAL, "bold", "start", mono=True)
    for i, (title, sub, rows) in enumerate(cols):
        x = 130 + i * 205
        b += text(x + 95, 72, title, 16, INK, "bold", limit=190)
        b += text(x + 95, 96, sub, 14, ORANGE, mono=sub.isascii(), limit=190)
        for r, (tot, lck, fre, st) in enumerate(rows):
            y = 112 + r * 150
            color = BLUE if r == 0 else TEAL
            fill = "#fde68a" if st else ("blue" if r == 0 else "teal")
            b += rect(x, y, 190, 126, fill, ORANGE if st else color, rx=10, width=1.4)
            b += text(x + 14, y + 32, "总额", 14, GRAY, anchor="start")
            b += text(x + 178, y + 32, tot, 14, INK, anchor="end", mono=True)
            b += text(x + 14, y + 70, "冻结", 14, GRAY, anchor="start")
            b += text(x + 178, y + 70, lck, 14, INK, anchor="end", mono=True)
            b += text(x + 14, y + 108, "可用", 14, GRAY, anchor="start")
            b += text(x + 178, y + 108, fre, 14, INK, anchor="end", mono=True)
        if i < 3:
            b += arrow(x + 192, 250, x + 203, 250, BLUE)
    b += text(480, 420, "买单冻结报价币的名义金额（剩余数量 × 价格），卖单冻结要交付的基础币；冻结不含手续费。", 14, INK, limit=920)
    b += text(480, 446, "成交时：USDT 减少名义金额 423.50 和手续费 0.4235，ETH 增加 1；订单结束后冻结重算为 0。", 14, INK, limit=920)
    b += text(480, 480, "橙色格是这一步变化的余额。每一格都满足 冻结 + 可用 = 总额。", 14, GRAY, limit=920)
    svg("account-balances.svg", "现金账户的四个时刻",
        "四列是同一个多币种现金账户在初始、挂出买单、买单成交、挂出卖单之后的余额，上一行 USDT、下一行 ETH，每格是总额、冻结、可用。"
        "挂买单后 USDT 冻结 423.50；成交后 USDT 总额变成 999,576.0765、ETH 变成 11，冻结归零；挂卖单后 ETH 冻结 5、可用 6。",
        510, b)



# ---------------------------------------------------------------------------
# 第 8 章 · 事件链与事件存储
# ---------------------------------------------------------------------------
def event_chain():
    b = text(480, 36, "一笔成交的事件链，以及事件存储怎样把它记下来", 19, INK, "bold", limit=920)
    b += rect(24, 58, 912, 196, "blue", BLUE, rx=14)
    b += text(44, 84, "产生与传播（执行引擎 handle_order_fill）", 16, BLUE, "bold", "start", limit=880)
    steps = [
        ("适配器", ["OrderFilled", "交易所成交回报"]),
        ("更新订单", ["apply(event)", "写回缓存"]),
        ("更新仓位", ["定 position_id", "Position.apply"]),
        ("发布订单事件", ["events.order.{S}", "组合先、策略后"]),
        ("发布仓位事件", ["events.position.{S}", "Changed / Closed"]),
    ]
    x = 40
    for i, (h, lines) in enumerate(steps):
        b += box(x, 100, 166, 84, [h] + lines, "white", BLUE, 15, mono_from=1)
        if i < 4:
            b += arrow(x + 168, 142, x + 180, 142, BLUE)
        x += 180
    b += box(580, 196, 340, 46, ["随后：AccountState → events.account.{A}"], "white", TEAL, 14, mono_from=9)
    b += text(44, 224, "S = 策略 ID，A = 账户 ID", 14, GRAY, anchor="start", limit=500)
    # bus line
    b += rect(24, 272, 912, 40, "gray", GRAY, rx=10)
    b += text(480, 298, "消息总线派发：下游处理器和抓取点看到同一个消息", 15, INK, "bold", limit=880)
    b += arrow(480, 256, 480, 270, BLUE)
    # capture lane
    b += rect(24, 330, 912, 220, "orange", ORANGE, rx=14)
    b += text(44, 356, "记录（可选：内核构建时传入 EventStoreFactory 才打开）", 16, ORANGE, "bold", "start", limit=880)
    b += arrow(480, 314, 480, 368, ORANGE)
    cap = [
        ("BusCaptureAdapter", ["按事件 ID、命令 ID", "去重：同一消息只记一次"]),
        ("EventStoreWriter", ["有界通道 10,000", "分配 seq，每批 100 条或 5 ms"]),
        ("redb 运行文件", ["<base>/<instance>/<run>.redb", "记录 + 索引 + 清单 + 锚点"]),
    ]
    x = 44
    for i, (h, lines) in enumerate(cap):
        b += box(x, 380, 280, 84, [h] + lines, "white", ORANGE, 15, mono_from=1)
        if i < 2:
            b += arrow(x + 282, 422, x + 300, 422, ORANGE)
        x += 300
    b += text(480, 494, "阻塞超过 250 ms 或提交失败：停止记录，交易照常继续", 14, RED, "bold", limit=880)
    b += text(480, 522, "下次启动封存：Ended / CrashedRecovered / Quarantined；回放按 seq 恢复缓存", 14, INK, limit=880)
    svg("event-chain.svg", "事件链与事件存储",
        "上半是一笔成交的处理：适配器发来 OrderFilled，执行引擎先更新订单、再确定仓位 ID 并更新仓位，然后发布订单事件和仓位事件，账户状态随后更新。"
        "中间是消息总线，下游处理器和抓取点看到同一个消息。下半是可选的事件存储：抓取适配器按事件和命令 ID 去重，写入线程分配序号并按批提交，"
        "写进按运行划分的 redb 文件；写入失败只停止记录、不打断交易，下次启动时封存这个运行。",
        580, b)



# ---------------------------------------------------------------------------
# 第 13 章 · Actor、策略与 TWAP 的三件套
# ---------------------------------------------------------------------------
def actor_twap_flow():
    b = text(480, 36, "三件套：Actor 发信号，策略下单，TWAP 拆单", 19, INK, "bold", limit=920)
    b += box(24, 66, 260, 96, ["SpreadMonitor（Actor）", "on_quote 算价差", "publish_signal(\"spread\")"], "teal", TEAL, 15, mono_from=2)
    b += arrow(286, 114, 336, 114, TEAL)
    b += text(311, 104, "信号", 14, TEAL)
    b += box(338, 66, 280, 96, ["策略 EMACross-001", "on_signal → 决定买 6 ETH", "exec_algorithm_id = TWAP"], "orange", ORANGE, 15, mono_from=9)
    b += arrow(620, 114, 670, 114, BLUE)
    b += text(645, 104, "下单", 14, BLUE)
    b += box(672, 66, 264, 96, ["TWAP.execute 端点", "on_order：只收市价主单", "60 s ÷ 10 s = 6 份"], "blue", BLUE, 15, mono_from=9)
    b += text(480, 186, "Strategy::submit_order 看到 exec_algorithm_id，就把命令发往 {id}.execute，而不是风控", 14, GRAY, limit=900)
    # slices
    b += rect(24, 204, 912, 176, "white", BLUE, rx=14)
    b += text(44, 230, "TWAP 每 10 秒提交一份（计时器名 = 主单号）", 16, BLUE, "bold", "start", limit=880)
    names = ["…-1-E1", "…-1-E2", "…-1-E3", "…-1-E4", "…-1-E5", "主单 …-1"]
    for i, n in enumerate(names):
        x = 44 + i * 148
        last = i == 5
        b += box(x, 248, 136, 70, [n, "1 ETH" if not last else "剩余 1 ETH"], "#fde68a" if last else "blue", ORANGE if last else BLUE, 14, mono_from=9)
        b += text(x + 68, 340, f"t = {i * 10} s", 14, GRAY, mono=True)
    b += text(480, 366, "前五份由 spawn_market 派生（主单数量随之减少），最后一份提交主单本身", 14, INK, limit=880)
    b += arrow(480, 382, 480, 404, BLUE)
    b += box(250, 406, 460, 52, ["RiskEngine → ExecutionEngine → 交易所"], "white", BLUE, 15, mono_from=9)
    b += text(480, 484, "成交事件带着策略 ID EMACross-001 回到策略，仓位记在策略名下，不属于 TWAP", 14, ORANGE, limit=880)
    svg("actor-twap-flow.svg", "Actor、策略与 TWAP 的三件套",
        "左上的价差监控 Actor 在 on_quote 里计算价差并发布名为 spread 的信号；策略在 on_signal 里决定买入 6 ETH，下一张带 exec_algorithm_id=TWAP 的市价单，"
        "命令被发往 TWAP.execute 端点；TWAP 按 60 秒、每 10 秒一份拆成 6 份，前五份是派生的子单 E1 到 E5，最后一份是主单本身，"
        "都经风控和执行引擎提交到交易所；成交事件带着策略的 ID 回到策略。",
        500, b)



# ---------------------------------------------------------------------------
# 第 14 章 · 内核的构造顺序和一生
# ---------------------------------------------------------------------------
def kernel_lifecycle():
    b = text(480, 36, "NautilusKernel：九步构造，两步启动，分步关闭", 19, INK, "bold", limit=920)
    b += rect(24, 58, 912, 196, "gray", GRAY, rx=14)
    b += text(44, 84, "构造（new_with_dependencies）", 16, INK, "bold", "start", limit=880)
    steps = ["① 日志", "② 时钟", "③ 事件存储（可选）", "④ Cache", "⑤ MessageBus → 线程局部",
             "⑥ Portfolio、三大引擎、仿真器", "⑦ 注册总线处理器", "⑧ 关停处理器", "⑨ Trader"]
    pos = [(44, 100, 120), (176, 100, 120), (308, 100, 190), (510, 100, 120), (642, 100, 274),
           (44, 168, 300), (356, 168, 200), (568, 168, 160), (740, 168, 176)]
    for (x, y, w), t in zip(pos, steps):
        b += box(x, y, w, 50, [t], "white", GRAY, 14, mono_from=9)
    for (x1, y1, w1), (x2, y2, w2) in zip(pos[:4], pos[1:5]):
        b += arrow(x1 + w1 + 1, y1 + 25, x2 - 1, y2 + 25, GRAY)
    b += poly_arrow([(779, 152), (779, 160), (194, 160), (194, 166)], GRAY)
    for (x1, y1, w1), (x2, y2, w2) in zip(pos[5:8], pos[6:9]):
        b += arrow(x1 + w1 + 1, y1 + 25, x2 - 1, y2 + 25, GRAY)
    # lifecycle
    b += rect(24, 272, 912, 250, "white", BLUE, rx=14)
    b += text(44, 298, "一次实盘运行（LiveNode::start / run / stop）", 16, BLUE, "bold", "start", limit=880)
    tl = [
        ("start()", "启动引擎和客户端", "Trader → READY", BLUE),
        ("连接数据客户端", "品种冲进缓存", "flush_pending_data", TEAL),
        ("连接执行客户端", "启动对账", "timeout_connection", TEAL),
        ("start_trader()", "on_load（load_state）", "仿真器、组件 on_start", BLUE),
        ("运行", "select! 循环", "ShutdownSystem → 停", ORANGE),
    ]
    x = 40
    for i, (h, l1, l2, c) in enumerate(tl):
        b += box(x, 316, 168, 86, [h, l1, l2], "white", c, 14, mono_from=9)
        if i < 4:
            b += arrow(x + 170, 359, x + 182, 359, BLUE)
        x += 182
    stop = [("stop_trader()", "组件 on_stop"), ("断开客户端", ""), ("finalize_stop()", "存状态、停引擎、封存"), ("dispose()", "释放引擎、缓存、总线")]
    x = 40
    for i, (h, l1) in enumerate(stop):
        lines = [h] + ([l1] if l1 else [])
        b += box(x, 424, 210, 70, lines, "white", RED if i == 0 else GRAY, 14, mono_from=9)
        if i < 3:
            b += arrow(x + 212, 459, x + 226, 459, GRAY)
        x += 228
    b += text(480, 552, "蓝：内核方法　青：实盘节点在 start 与 start_trader 之间插入的步骤　回测由 BacktestEngine 直接依次调用两步", 14, GRAY, limit=920)
    svg("kernel-lifecycle.svg", "内核的构造顺序和一生",
        "上半是九步构造：日志、时钟、可选的事件存储、缓存、放进线程局部存储的消息总线、组合和三大引擎及订单仿真器、注册总线处理器、关停处理器、Trader。"
        "下半是一次实盘运行：start 启动引擎和客户端，实盘节点接着连接数据客户端并把品种冲进缓存、连接执行客户端并对账，然后 start_trader 恢复状态并启动组件，"
        "运行到收到关停命令后依次 stop_trader、断开客户端、finalize_stop 保存状态停止引擎封存事件存储、dispose 释放一切。",
        580, b)



# ---------------------------------------------------------------------------
# 第 15 章 · 一条报价在总线里的路径
# ---------------------------------------------------------------------------
def msgbus_publish():
    b = text(480, 36, "publish_quote(\"data.quotes.BINANCE.ETHUSDT\", &quote) 在总线里的路径", 19, INK, "bold", limit=920)
    left = [
        ("① 抓取点", "dispatch_tap_publish", "事件存储（第 8 章）", ORANGE, "white"),
        ("② 取缓冲区", "std::mem::take(TLS)", "嵌套发布拿到新缓冲区", BLUE, "white"),
        ("③ 短暂借用总线", "topic_cache 命中？", "否：匹配全部订阅并排序", GRAY, "gray"),
        ("④ 放开借用", "依次调用处理器", "⑤ 归还缓冲区", BLUE, "white"),
    ]
    y = 64
    for i, (h, l1, l2, c, fill) in enumerate(left):
        b += box(24, y, 300, 86, [h, l1, l2], fill, c, 15, mono_from=1)
        if i < 3:
            b += arrow(174, y + 88, 174, y + 104, BLUE)
        y += 106
    b += rect(352, 64, 584, 400, "white", BLUE, rx=14)
    b += text(372, 92, "匹配结果（已缓存，按优先级从高到低）", 16, BLUE, "bold", "start", limit=560)
    subs = [
        ("Portfolio", "data.quotes.*", "10", "更新未实现盈亏"),
        ("BarQuoteHandler", "data.quotes.BINANCE.ETHUSDT", "5", "聚合器：可能 publish_bar"),
        ("策略 handle_quote", "data.quotes.BINANCE.ETHUSDT", "0", "on_quote：可能下单"),
    ]
    y = 112
    for name, pat, pri, note in subs:
        b += rect(372, y, 544, 96, "blue", BLUE, rx=10, width=1.3)
        b += text(392, y + 30, name, 15, INK, "bold", "start", mono=name.isascii(), limit=300)
        b += text(896, y + 30, "优先级 " + pri, 14, BLUE, anchor="end")
        b += text(392, y + 56, pat, 14, GRAY, anchor="start", mono=True, limit=500)
        b += text(392, y + 82, note, 14, ORANGE, anchor="start", limit=500)
        y += 110
    b += arrow(326, 386, 350, 386, BLUE)
    b += text(480, 500, "③ 是唯一借用总线的一段；处理器运行时总线已放开，所以它们内部可以再发布、再发送命令。", 14, INK, limit=920)
    b += text(480, 526, "订阅或退订会清空 topic_cache；派发中新增的订阅从下一次发布开始生效。", 14, GRAY, limit=920)
    svg("msgbus-publish.svg", "一条报价在总线里的路径",
        "左边是 publish_typed 的五步：经过事件存储的抓取点；从线程局部存储取出处理器缓冲区；短暂借用总线，从匹配缓存取出处理器，未命中就匹配全部订阅并排序；"
        "放开借用后依次调用处理器；最后归还缓冲区。右边是这个主题的匹配结果：组合（优先级 10）、K 线聚合器（5）、策略（0），聚合器和策略在处理时还可能再发布或下单。",
        550, b)



# ---------------------------------------------------------------------------
# 第 16 章 · 一张限价单在缓存索引里的足迹
# ---------------------------------------------------------------------------
def cache_order_footprint():
    b = text(480, 36, "一张限价单在缓存索引里的足迹：每一步属于哪些集合", 19, INK, "bold", limit=920)
    cols = ["add_order\nINITIALIZED", "提交后\nSUBMITTED", "交易所接受\nACCEPTED", "全部成交\nFILLED"]
    rows = [
        ("orders", [1, 1, 1, 1]),
        ("orders_active_local", [1, 0, 0, 0]),
        ("orders_inflight", [0, 1, 0, 0]),
        ("orders_open", [0, 0, 1, 0]),
        ("orders_closed", [0, 0, 0, 1]),
        ("venue_order_ids", [0, 0, 1, 1]),
        ("account_orders", [0, 1, 1, 1]),
        ("order_position 等", [0, 0, 0, 1]),
    ]
    x0, w = 270, 160
    for j, c in enumerate(cols):
        a, bb = c.split("\n")
        b += text(x0 + j * (w + 8) + w / 2, 70, a, 15, INK, "bold", limit=w)
        b += text(x0 + j * (w + 8) + w / 2, 92, bb, 14, BLUE, mono=True, limit=w)
    y = 106
    for name, flags in rows:
        b += text(254, y + 26, name, 14, INK, anchor="end", mono=name.isascii(), limit=230)
        for j, f in enumerate(flags):
            x = x0 + j * (w + 8)
            b += rect(x, y + 4, w, 34, "#fde68a" if f else "white", ORANGE if f else "#cbd5e1", rx=6, width=1.2)
        y += 42
    b += text(480, y + 24, "归属索引（strategy_orders、instrument_orders、venue_orders）在 add_order 时一次写入，之后不变。", 14, GRAY, limit=920)
    b += text(480, y + 50, "每个订单事件经 update_order：先在副本上 apply，成功后替换缓存里的订单，再由 refresh_order 按新状态维护这些集合。", 14, INK, limit=920)
    svg("cache-order-footprint.svg", "一张限价单在缓存索引里的足迹",
        "表格的行是缓存的索引集合，列是订单的四个时刻：创建时属于总表和本地集合，提交后属于在途集合并登记账户，交易所接受后属于挂单集合并登记交易所订单号，"
        "全部成交后属于已结束集合并建立仓位索引。总表那一行始终有它。",
        y + 80, b)



# ---------------------------------------------------------------------------
# 第 17 章 · 回测时间线：数据与计时器的执行顺序
# ---------------------------------------------------------------------------
def clock_timeline():
    b = text(480, 36, "回测时间线：先执行更早的计时器，再处理这一时刻的数据，最后执行同一时刻的计时器", 18, INK, "bold", limit=930)
    x0, x1 = 150, 880
    t0, t1 = 0.0, 70.0
    def X(t):
        return x0 + (x1 - x0) * (t - t0) / (t1 - t0)
    ay = 230
    b += f'<line x1="{x0-20}" y1="{ay}" x2="{x1+20}" y2="{ay}" stroke="{INK}" stroke-width="2" marker-end="url(#arrow)"/>'
    for t, lab in [(0, "10:00:00"), (30, "10:00:30"), (45, "10:00:45"), (60, "10:01:00")]:
        b += f'<line x1="{X(t):.1f}" y1="{ay-6}" x2="{X(t):.1f}" y2="{ay+6}" stroke="{INK}" stroke-width="1.5"/>'
        b += text(X(t), ay + 26, lab, 14, GRAY, mono=True)
    b += text(30, 146, "数据", 15, BLUE, "bold", "start")
    b += text(30, 326, "计时器", 15, ORANGE, "bold", "start")
    data = [(0.223, "①", "成交 10:00:00.223", 0), (45, "③", "成交 10:00:45", 0), (60, "④", "成交 10:01:00.000", -1), (66, "⑥", "成交 10:01:06", 0)]
    for t, n, lab, side in data:
        x = X(t)
        b += f'<line x1="{x:.1f}" y1="{ay}" x2="{x:.1f}" y2="150" stroke="{BLUE}" stroke-width="1.5"/>'
        b += f'<circle cx="{x:.1f}" cy="140" r="13" fill="#eff6ff" stroke="{BLUE}" stroke-width="1.5"/>'
        b += text(x, 146, n, 14, BLUE, "bold")
        ly = {"①": 108, "③": 108, "④": 82, "⑥": 108}[n]
        lx = {"①": 0, "③": -30, "④": -10, "⑥": 30}[n]
        b += text(x + lx, ly, lab, 14, INK, limit=200)
    timers = [(30, "②", "heartbeat 10:00:30", 0), (60, "⑤", "heartbeat、TIME_BAR 10:01:00", 0)]
    for t, n, lab, side in timers:
        x = X(t)
        b += f'<line x1="{x:.1f}" y1="{ay}" x2="{x:.1f}" y2="310" stroke="{ORANGE}" stroke-width="1.5" stroke-dasharray="5 4"/>'
        b += f'<circle cx="{x:.1f}" cy="320" r="13" fill="#fff7ed" stroke="{ORANGE}" stroke-width="1.5"/>'
        b += text(x, 326, n, 14, ORANGE, "bold")
        b += text(x - (40 if t == 60 else 0), 362, lab, 14, INK, limit=260)
    b += rect(24, 392, 912, 112, "gray", GRAY, rx=12)
    b += text(44, 418, "规则（crates/backtest/src/engine.rs）", 15, INK, "bold", "start", limit=880)
    b += text(44, 444, "对每个数据时间戳 T：advance_time_impl(T) 执行所有 ≤ T−1 的计时器 → replay_data_row 处理 T 的全部数据", 14, INK, anchor="start", limit=880)
    b += text(44, 468, "→ flush_accumulator_events(T) 执行恰好在 T 到点的计时器。执行每个计时器前，所有组件时钟被设到它的时刻。", 14, INK, anchor="start", limit=880)
    b += text(44, 492, "所以 10:01:00.000 的成交先进入 K 线聚合器，再由 10:01:00 的 TIME_BAR 计时器生成 K 线（左开右闭）。", 14, ORANGE, anchor="start", limit=880)
    svg("clock-timeline.svg", "回测时间线：数据与计时器的执行顺序",
        "横轴是回测时间。上方蓝色圆圈是数据，下方橙色圆圈是计时器，数字是执行顺序：10:00:00.223 的成交、10:00:30 的心跳计时器、10:00:45 的成交、"
        "10:01:00.000 的成交、10:01:00 到点的心跳和 K 线计时器、10:01:06 的成交。同一时刻的数据先于计时器执行。",
        530, b)


def main():
    system_overview()
    rust_crates()
    python_projection()
    cache_layout()
    order_book_layout()
    crate_dependencies()
    build_pipeline()
    futu_in_crates()
    futu_runtime()
    futu_python_binding()
    pyo3_binding()
    callback_flow()
    rust_strategy()
    bar_aggregation_flow()
    bar_aggregators()
    indicator_flow()
    value_types_trade()
    instrument_price_path()
    book_deltas()
    order_state_machine()
    positions_oms()
    account_balances()
    event_chain()
    actor_twap_flow()
    kernel_lifecycle()
    msgbus_publish()
    cache_order_footprint()
    clock_timeline()
    for w in WARNINGS:
        print("WARNING:", w, file=sys.stderr)


if __name__ == "__main__":
    main()
