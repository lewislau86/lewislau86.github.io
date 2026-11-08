"""Generate graph-flow orchestration teaching diagrams from the fixed lab design."""


def generate(root,text,panel,arrow,save_figure):
    body=panel(40,85,420,150,'模型与工具层 · langchain-rust',['消息、模型请求、工具调用结果','决定本轮提出什么内容与动作'],'#2563eb')
    body+=panel(500,85,420,150,'图编排层 · graph-flow',['节点、状态、边与会话游标','决定下一步执行哪段程序'],'#0f766e')
    body+=arrow('M250 235 V285 H480 V320')+arrow('M710 235 V285 H480')
    body+=panel(140,330,680,160,'宿主应用：把两层接起来',['G01：状态与路由 → G02：等待与恢复 → G03：并行与子图','节点可以调用模型，也可以只是校验、审批或归并','权限、预算、终态与业务效果由明确契约约束'],'#475569')
    body+=text(480,545,'三章实验真实调用 graph-flow；固定业务规则，无模型服务。',19)
    save_figure('graph-orchestration-layers.svg','两条教学主线：模型交互与图编排','模型工具层产生请求与结果，图编排层管理执行顺序和状态；宿主应用连接两者。',590,body)

    body=panel(40,85,240,110,'prepare',['draft = 1'])+arrow('M280 140 H355')
    body+=panel(365,85,240,110,'check',['等级达到 required？'],'#0f766e')
    body+=arrow('M605 140 H675')+panel(685,85,235,110,'accept',['记录 accepted → End'],'#0f766e')
    body+=arrow('M480 195 V265')+panel(355,275,260,145,'repair',['未超额度：draft + 1','GoTo(check)'],'#b45309')
    body+=arrow('M355 345 H315 V140 H355')
    body+=arrow('M615 345 H675')+panel(685,275,235,145,'handoff',['额度耗尽','needs_human → End'],'#b91c1c')
    body+=panel(75,485,810,120,'状态在 Context，游标在 Session',['review：draft / required / repairs / outcome / trace','Continue 返回宿主；ContinueAndExecute 可在同一次调用继续'],'#475569')
    save_figure('g01-state-routing.svg','一次审查如何经过分支与修复回路','准备后进行检查，达到要求则接受，否则在有界预算内修复并跳回检查，耗尽则交接。',650,body)

    body=panel(40,85,260,140,'进程 A：推进到审批',['draft → approve','WaitForInput','游标仍为 approve'],'#2563eb')
    body+=arrow('M300 155 H345')+panel(355,85,250,140,'SQLite SessionStorage',['Session JSON + version','事务核对旧 version','成功后 version + 1'],'#0f766e')
    body+=arrow('M605 155 H650')+panel(660,85,260,140,'进程 B：保存决定',['revision + yes/no','校验当前方案修订','CAS 保存'],'#b45309')
    body+=arrow('M790 225 V290 H480 V325')
    body+=panel(160,335,640,150,'进程 C：重新进入 approve',['节点从头运行，读取已保存的决定','GoTo(render/reject) → 下次 step 执行终态节点','应用保存 terminal，重复 step 直接返回'],'#475569')
    body+=text(480,545,'FlowRunner：load → execute_session → save；外部效果不在此事务内。',18)
    save_figure('g02-resume-boundary.svg','暂停的是执行，保存的是整个会话','不同进程通过真实 SQLite SessionStorage 保存和读取会话；等待节点恢复时重新执行。',590,body)

    body=panel(45,85,240,130,'图中的一个节点',['FanOutTask(checks)','共享状态，等待全部孩子'],'#2563eb')
    body+=arrow('M285 150 H330 V110 H385')+arrow('M330 150 V290 H385')
    body+=panel(395,65,230,125,'compatibility',['独立 response','子 NextAction = End'],'#0f766e')
    body+=panel(395,245,230,125,'tests',['独立 response','子 NextAction = End'],'#0f766e')
    body+=arrow('M625 125 H665 V215 H700')+arrow('M625 305 H665 V215')
    body+=panel(710,150,210,160,'merge',['检查全部结果','检查成员齐全','固定 ID 顺序归并'],'#b45309')
    body+=panel(80,440,800,135,'并行边界与子图边界分别设计',['FanOut 子任务共享 Context：前缀只隔开自动归档键','子图包装器创建新 Session：显式传入 request，取回 result','子任务失败可留下局部数据；后续 merge 不运行'],'#475569')
    save_figure('g03-parallel-join.svg','并行执行需要显式归并契约','FanOutTask 等待并行子任务，归并节点核对结果；子图通过新会话与显式输入输出隔离。',620,body)
