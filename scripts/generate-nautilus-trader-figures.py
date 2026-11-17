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
<marker id="arrow-orange" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ORANGE}"/></marker></defs>
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
        mono = i >= mono_from
        out += text(x + w / 2, top + i * gap, line, size if i == 0 else size - 1,
                    color if i == 0 else GRAY, "bold" if i == 0 else "normal", mono=mono, limit=w - 12)
    return out


def arrow(x1, y1, x2, y2, color=GRAY, width=1.6, dash=False, both=False):
    marker = {GRAY: "arrow", BLUE: "arrow-blue", ORANGE: "arrow-orange"}[color]
    extra = ' stroke-dasharray="6 5"' if dash else ""
    start = f' marker-start="url(#{marker})"' if both else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
            f'stroke-width="{width}"{extra} marker-end="url(#{marker})"{start}/>')


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
    b += box(676, 448, 208, 50, ["日志 · 写库 · 写数据目录", "后台写入任务"], "white", TEAL, size=14, mono_from=9)
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
        "适配器客户端、网络、日志和持久化写入跑在 Tokio 后台线程，只通过 channel 把事件送回核心线程。",
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


def main():
    system_overview()
    rust_crates()
    python_projection()
    cache_layout()
    order_book_layout()
    for w in WARNINGS:
        print("WARNING:", w, file=sys.stderr)


if __name__ == "__main__":
    main()
