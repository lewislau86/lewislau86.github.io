"""R17 ownership and replay figures from verified independent-process experiments."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence=json.loads((root/"scripts/data/learn-agent-rust/r17-results.json").read_text())
    source=root/"docs/public/learn-agent-rust/code/autonomous-workers"
    for name,digest in evidence["files_sha256"].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:
            raise ValueError("R17 evidence stale; run verify-agent-workers.py")
    rows={row["name"]:row for row in evidence["scenarios"]}
    m=rows["race-four"]["metrics"]
    body=panel(40,92,880,110,"{} 个独立进程 · 同一项 report".format(m["live_processes"]),["全部到达管道门闩 → 放行，开始竞争写事务"])
    body+=arrow("M480 202 V244")
    body+=panel(40,252,880,125,"一个 BEGIN IMMEDIATE 写事务",["挑选候选 → 更新 owner / token / lease_until → COMMIT","提交成功后才开始业务动作"],"#0f766e")
    body+=arrow("M480 377 V417")
    body+=panel(40,425,400,115,"成功领取 {} 个".format(m["first_round_claimed"]),["持久化 token = {}".format(m["persisted_token"])],"#0f766e")
    body+=panel(520,425,400,115,"其余 {} 个".format(m["first_round_other_empty_or_busy"]),["empty 或 store_busy；由实际调度决定"],"#b45309")
    body+=text(480,590,"随后 {} 次新进程领取均为 empty，有效租约没有被重复领取。".format(m["retry_empty"]),18,"#475569")
    save("r17-atomic-claim.svg","选取与更新在一个事务中完成","四个真实进程竞争同一任务，只有一个成功领取；其他进程返回空或忙，持久化代次仍为一。",630,body)

    m=rows["restart-takeover"]["metrics"]
    steps=rows["restart-takeover"]["steps"]
    claims=[s for s in steps if s["status"]=="claimed"]
    first,last=claims[0]["task"],claims[-1]["task"]
    empty=next(s for s in steps if s["status"]=="empty")
    body=panel(40,92,400,125,"worker-a · 首次领取",["now = {} · token = {}".format(claims[0]["now"],first["token"]),"lease_until = {}".format(first["lease_until"])])
    body+=panel(520,92,400,125,"worker-b · 尝试领取",["now = {}".format(empty["now"]),"尚未到期 → empty"],"#b45309")
    body+=arrow("M720 217 V263")
    body+=panel(520,271,400,125,"worker-b · 到期接管",["now = {} · token = {}".format(m["takeover_now"],last["token"]),"lease_until = {}".format(last["lease_until"])],"#0f766e")
    body+=arrow("M240 217 V333 H505")
    body+=panel(40,442,880,100,"业务任务身份始终相同",["id = report；接管更换 owner、增加代次并设置新截止时间"],"#0f766e")
    body+=text(480,588,"租约到期允许接管；它不会自动终止旧进程。",19,"#475569")
    save("r17-lease-takeover.svg","到期边界与领取代次共同定义接管","实验时间一百秒领取到一百一十秒，一百零九秒无法接管，一百一十秒接管得到代次二。",630,body)

    same=rows["same-name"]["steps"]
    claims=[s for s in same if s["status"]=="claimed"]
    old,new=claims[0]["task"],claims[1]["task"]
    rejected=sum(s.get("error")=="lease_rejected" for s in same)
    body=panel(40,92,400,130,"旧请求 · owner 相同",["owner = {}".format(old["owner"]),"token = {}".format(old["token"])],"#b45309")
    body+=panel(520,92,400,130,"数据库 · 当前领取",["owner = {}".format(new["owner"]),"token = {}".format(new["token"])],"#0f766e")
    body+=arrow("M240 222 V262 H480 V283")+arrow("M720 222 V262 H480")
    body+=panel(40,291,880,130,"完成与续租：条件必须全部成立",["state = running · owner 相同 · token 相同","now < lease_until；续租还须严格延长截止时间"])
    body+=arrow("M480 421 V461")
    body+=panel(40,469,880,100,"同名仍无法绕过代次检查",["旧代次完成 + 旧代次续租：{} 次 lease_rejected".format(rejected)],"#b91c1c")
    body+=text(480,615,"代次保护实际核验凭证的存储端；此处保护的是任务表。",18,"#475569")
    save("r17-fenced-writes.svg","名字可以复用，领取代次不能混用","相同执行者名字的新旧领取依代次区分，旧代次完成与续租均被任务表拒绝。",655,body)

    a,b=rows["effect-replay"]["metrics"],rows["effect-dedupe"]["metrics"]
    body=panel(40,86,880,110,"相同退出窗口与接管顺序",["A 提交业务动作 → 退出；到期后 B 接管 → 再次调用"])
    for x,m,title,color in [(40,a,"业务服务关闭去重","#b45309"),(520,b,"业务服务开启稳定身份去重","#0f766e")]:
        body+=panel(x,255,400,140,title,["calls = {} · reports = {}".format(m["calls"],m["reports"]),"最终任务 token = {}".format(m["queue_token"])],color)
        body+=arrow("M{} 196 V247".format(x+200))
    body+=panel(40,445,880,105,"去重身份跨领取代次保持不变",[b["operation"]+"；去重键与报告在业务库同一事务提交"],"#0f766e")
    body+=text(480,598,"队列完成只有一次，业务调用仍有两次；两个边界分别核对。",18,"#475569")
    save("r17-effect-replay.svg","只有当前 owner，业务仍可能重复产生结果","两个场景都发生两次业务调用，关闭去重产生两份报告，开启业务端稳定身份去重仅产生一份。",640,body)
