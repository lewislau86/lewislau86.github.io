"""Generate adk-graph orchestration teaching diagrams (G01–G03, ADK-Rust 3.0) from the fixed lab design."""


def generate(root,text,panel,arrow,save_figure):
    body=panel(40,85,420,150,'Agent 层 · LlmAgent',['模型 ↔ 工具的循环','决定本轮提出什么内容与动作'],'#2563eb')
    body+=panel(500,85,420,150,'图编排层 · adk-graph',['节点、状态通道、边与检查点','决定下一步运行哪个节点'],'#0f766e')
    body+=arrow('M250 235 V285 H480 V320')+arrow('M710 235 V285 H480')
    body+=panel(140,330,680,160,'宿主应用：决定图的形状与规则',['G01：状态与路由 → G02：暂停与恢复 → G03：并行与子图','节点可以是一个 Agent（AgentNode），也可以只是校验、审批或归并','权限、预算、终态与业务效果由明确契约约束'],'#475569')
    body+=text(480,545,'三章实验真实运行 adk-graph；固定业务规则，无模型服务。',19)
    save_figure('graph-orchestration-layers.svg','两条教学主线：Agent 循环与图编排','LlmAgent 运行模型与工具的循环，adk-graph 管理节点的执行顺序、状态与检查点；宿主应用决定图的形状与规则。',590,body)

    body=panel(40,85,240,110,'prepare',['draft = 1'])+arrow('M280 140 H355')
    body+=panel(365,85,240,110,'check',['条件边：达到 required？'],'#0f766e')
    body+=arrow('M605 140 H675')+panel(685,85,235,110,'accept',['outcome = accepted'],'#0f766e')
    body+=arrow('M530 195 V265')+text(588,236,'未达要求',15,'#475569')
    body+=arrow('M430 275 V205')+text(372,236,'再检查',15,'#475569')
    body+=panel(355,275,260,145,'repair',['额度未满：repairs +1，draft +1','with_goto(check)'],'#b45309')
    body+=arrow('M615 345 H675')+panel(685,275,235,145,'handoff',['额度用完：with_goto','outcome = needs_human'],'#b91c1c')
    body+=panel(75,485,810,120,'状态是带归并规则的通道',['draft / required / outcome：覆盖；repairs：计数；trace：列表追加','一次 stream 按超步跑到结束；with_recursion_limit 兜住无限循环'],'#475569')
    save_figure('g01-state-routing.svg','一次审查如何经过分支与修复回路','准备后进行检查，达到要求则接受，否则在有限额度内修复并跳回检查，额度用完则转人工；状态通道按各自的归并规则更新。',650,body)

    body=panel(40,85,260,140,'进程 A：init',['draft → approve','approve 暂停','返回暂停 ID'],'#2563eb')
    body+=arrow('M300 155 H345')+panel(355,85,250,140,'SQLite 检查点',['状态 + 步号 + 待运行节点','暂停 ID 与答案格式','版本号只增不减'],'#0f766e')
    body+=arrow('M605 155 H650')+panel(660,85,260,140,'进程 B：answer',['严格恢复：只认暂停 ID','答案先按格式校验','宿主先核对图版本'],'#b45309')
    body+=arrow('M790 225 V290 H480 V325')
    body+=panel(160,335,640,150,'恢复：重新运行 approve',['这次带着回答，with_goto 到 render / reject / draft','已保存的步骤不再运行；已完成的线程直接返回最终状态','两个写入者同时保存：后者 CheckpointConflict'],'#475569')
    body+=text(480,545,'默认每个超步结束保存；崩溃时未保存的一步整步重跑，节点可能运行不止一次。',18)
    save_figure('g02-resume-boundary.svg','暂停的是执行，保存的是检查点','不同进程通过 SQLite 检查点保存和读取图的状态；恢复时暂停的节点重新运行，并按暂停 ID 拿到回答。',590,body)

    body=panel(45,85,240,130,'plan',['两条出边','下一个超步并行'],'#2563eb')
    body+=arrow('M285 150 H330 V110 H385')+arrow('M330 150 V290 H385')
    body+=panel(395,65,230,125,'security',['只写 security 通道','失败：完成的兄弟保留'],'#0f766e')
    body+=panel(395,245,230,125,'license',['只写 license 通道','超时：失败或跳过'],'#0f766e')
    body+=arrow('M625 125 H665 V215 H700')+arrow('M625 305 H665 V215')
    body+=panel(710,150,210,160,'merge',['自动等两项到齐','只运行一次','ready / blocked / incomplete'],'#b45309')
    body+=panel(80,440,800,135,'并行边界与子图边界分别设计',['同一步的更新按节点名顺序应用；覆盖通道上的“读后写回”会丢更新','SubgraphNode 隔离通道：只交换声明的输入输出，映射错误在父图编译时发现','超时跳过让缺失流进下游，归并规则要识别 incomplete'],'#475569')
    save_figure('g03-parallel-join.svg','并行执行需要显式归并契约','plan 之后两项检查在同一个超步并行，merge 自动等待两项到齐后按业务规则归并；子图通过隔离的通道映射交换数据。',620,body)
