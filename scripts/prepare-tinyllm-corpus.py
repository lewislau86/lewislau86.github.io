"""Build the TinyLLM poem corpus: docs/public/tinyllm/data/tang-poems.jsonl

读者不需要运行这个脚本：处理好的语料已经放在仓库和网站上（见 /tinyllm/setup）。
它只用来说明语料从哪里来、怎样处理，并在需要时重新生成，结果逐字节可复现。

来源：chinese-poetry（MIT 许可证）固定版本 b8594f81 的《全唐诗》与《唐诗三百首》。
处理：
  1. 只保留五言绝句和五言律诗：2 或 4 段，每段都是“五字，五字。”；
  2. 繁体转简体（OpenCC t2s），按正文去重；
  3. 第 1 章用的 39 首排在最前，用通行的教材版本（源数据里有不少异文和异体字）；
     接着是《唐诗三百首》里的五言绝句、律诗，其余按固定随机种子打乱，“前 N 首”就是一个稳定的子集；
     同一首诗的异文版本（首句、末句都相同，或与前 39 首有两句以上相同）只保留一份；
  4. 按正文的 SHA-256 固定划分：约 5% 验证集、5% 测试集，其余训练集。划分只看正文，
     和顺序无关，任取前 N 首，划分都一致。第 1 章的 39 首全部放在训练集。

依赖：pip install opencc-python-reimplemented（需要联网下载源数据，约 24 MB）。
用法：python scripts/prepare-tinyllm-corpus.py
"""

from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
import hashlib
import json
import random
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/tinyllm/data/tang-poems.jsonl"
CACHE = ROOT / ".cache/chinese-poetry"
COMMIT = "b8594f81a89752241442f2ce267d6f66f96704ee"
RAW = f"https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/{COMMIT}/"
LINE = re.compile(r"^[一-鿿]{5}，[一-鿿]{5}。$")

# 第 1 章的 39 首：用通行的教材版本（源数据里不少是异文、异体字，例如“床前看月光”“万迳人踪灭”）
CLASSICS = """
床前明月光，疑是地上霜。举头望明月，低头思故乡。
春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。
白日依山尽，黄河入海流。欲穷千里目，更上一层楼。
红豆生南国，春来发几枝。愿君多采撷，此物最相思。
空山不见人，但闻人语响。返景入深林，复照青苔上。
千山鸟飞绝，万径人踪灭。孤舟蓑笠翁，独钓寒江雪。
锄禾日当午，汗滴禾下土。谁知盘中餐，粒粒皆辛苦。
春种一粒粟，秋收万颗子。四海无闲田，农夫犹饿死。
松下问童子，言师采药去。只在此山中，云深不知处。
向晚意不适，驱车登古原。夕阳无限好，只是近黄昏。
移舟泊烟渚，日暮客愁新。野旷天低树，江清月近人。
独坐幽篁里，弹琴复长啸。深林人不知，明月来相照。
君自故乡来，应知故乡事。来日绮窗前，寒梅著花未。
山中相送罢，日暮掩柴扉。春草明年绿，王孙归不归。
众鸟高飞尽，孤云独去闲。相看两不厌，只有敬亭山。
功盖三分国，名成八阵图。江流石不转，遗恨失吞吴。
绿蚁新醅酒，红泥小火炉。晚来天欲雪，能饮一杯无。
日暮苍山远，天寒白屋贫。柴门闻犬吠，风雪夜归人。
人闲桂花落，夜静春山空。月出惊山鸟，时鸣春涧中。
危楼高百尺，手可摘星辰。不敢高声语，恐惊天上人。
离离原上草，一岁一枯荣。野火烧不尽，春风吹又生。远芳侵古道，晴翠接荒城。又送王孙去，萋萋满别情。
国破山河在，城春草木深。感时花溅泪，恨别鸟惊心。烽火连三月，家书抵万金。白头搔更短，浑欲不胜簪。
空山新雨后，天气晚来秋。明月松间照，清泉石上流。竹喧归浣女，莲动下渔舟。随意春芳歇，王孙自可留。
好雨知时节，当春乃发生。随风潜入夜，润物细无声。野径云俱黑，江船火独明。晓看红湿处，花重锦官城。
青山横北郭，白水绕东城。此地一为别，孤蓬万里征。浮云游子意，落日故人情。挥手自兹去，萧萧班马鸣。
海上生明月，天涯共此时。情人怨遥夜，竟夕起相思。灭烛怜光满，披衣觉露滋。不堪盈手赠，还寝梦佳期。
城阙辅三秦，风烟望五津。与君离别意，同是宦游人。海内存知己，天涯若比邻。无为在歧路，儿女共沾巾。
客路青山外，行舟绿水前。潮平两岸阔，风正一帆悬。海日生残夜，江春入旧年。乡书何处达，归雁洛阳边。
故人具鸡黍，邀我至田家。绿树村边合，青山郭外斜。开轩面场圃，把酒话桑麻。待到重阳日，还来就菊花。
单车欲问边，属国过居延。征蓬出汉塞，归雁入胡天。大漠孤烟直，长河落日圆。萧关逢候骑，都护在燕然。
渡远荆门外，来从楚国游。山随平野尽，江入大荒流。月下飞天镜，云生结海楼。仍怜故乡水，万里送行舟。
戍鼓断人行，边秋一雁声。露从今夜白，月是故乡明。有弟皆分散，无家问死生。寄书长不达，况乃未休兵。
细草微风岸，危樯独夜舟。星垂平野阔，月涌大江流。名岂文章著，官应老病休。飘飘何所似，天地一沙鸥。
昔闻洞庭水，今上岳阳楼。吴楚东南坼，乾坤日夜浮。亲朋无一字，老病有孤舟。戎马关山北，凭轩涕泗流。
清晨入古寺，初日照高林。曲径通幽处，禅房花木深。山光悦鸟性，潭影空人心。万籁此都寂，但余钟磬音。
岱宗夫如何，齐鲁青未了。造化钟神秀，阴阳割昏晓。荡胸生曾云，决眦入归鸟。会当凌绝顶，一览众山小。
楚塞三湘接，荆门九派通。江流天地外，山色有无中。郡邑浮前浦，波澜动远空。襄阳好风日，留醉与山翁。
北阙休上书，南山归敝庐。不才明主弃，多病故人疏。白发催年老，青阳逼岁除。永怀愁不寐，松月夜窗虚。
八月湖水平，涵虚混太清。气蒸云梦泽，波撼岳阳城。欲济无舟楫，端居耻圣明。坐观垂钓者，徒有羡鱼情。
""".split()


def fetch(path: str) -> list:
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / path.replace("/", "_")
    if not local.exists():
        with urlopen(RAW + quote(path), timeout=120) as r:
            local.write_bytes(r.read())
    return json.loads(local.read_text(encoding="utf-8"))


def main() -> None:
    from opencc import OpenCC
    t2s = OpenCC("t2s").convert

    def wuyan(item, source):
        paras = item.get("paragraphs", [])
        if len(paras) in (2, 4) and all(LINE.match(p) for p in paras):
            return {"text": t2s("".join(paras)), "title": t2s(item.get("title", "")),
                    "author": t2s(item.get("author", "")), "source": source}
        return None

    pool = []
    for i in range(0, 58000, 1000):
        for item in fetch(f"全唐诗/poet.tang.{i}.json"):
            p = wuyan(item, "全唐诗")
            if p:
                pool.append(p)
    famous = [p for item in fetch("全唐诗/唐诗三百首.json") if (p := wuyan(item, "唐诗三百首"))]

    classics = [{"text": t, "title": "", "author": "", "source": "第 1 章（通行版本）"} for t in CLASSICS]
    lines5 = lambda t: set(re.findall(r"[一-鿿]{5}", t))

    # 去重：正文相同，或首句、末句都相同（同一首诗的异文版本）只保留一份；与第 1 章的 39 首有两句以上相同的也去掉
    kept, keys = [], set()
    classic_lines = [lines5(c["text"]) for c in classics]
    for p in famous + pool:                       # “唐诗三百首”排在前面，重复时保留它的来源标记
        key = (p["text"][:5], p["text"][-6:-1])
        if p["text"] in keys or key in keys or any(len(lines5(p["text"]) & cl) >= 2 for cl in classic_lines):
            continue
        keys.update([p["text"], key])
        kept.append(p)
    head = [p for p in kept if p["source"] == "唐诗三百首"]
    rest = [p for p in kept if p["source"] != "唐诗三百首"]
    random.Random(0).shuffle(rest)
    ordered = classics + head + rest

    def split(p, k):
        if k < len(classics):
            return "train"
        h = int(hashlib.sha256(p["text"].encode("utf-8")).hexdigest(), 16) % 20
        return "val" if h == 0 else "test" if h == 1 else "train"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for k, p in enumerate(ordered):
            f.write(json.dumps({"id": k, "split": split(p, k), **p}, ensure_ascii=False) + "\n")
    data = OUT.read_bytes()
    rows = [json.loads(l) for l in data.decode("utf-8").splitlines()]
    manifest = {
        "file": OUT.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "poems": len(rows),
        "chars": sum(len(r["text"]) for r in rows),
        "splits": {s: sum(r["split"] == s for r in rows) for s in ("train", "val", "test")},
        "order": {"classics": len(classics), "tangshi300": len(head), "quantangshi": len(rest)},
        "source": {"repo": "https://github.com/chinese-poetry/chinese-poetry", "commit": COMMIT, "license": "MIT"},
    }
    (OUT.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False))

if __name__ == "__main__":
    main()
