"""Concept diagrams and observed retrieval metrics for the knowledge supplement."""
import json


def generate(root, text, panel, arrow, save_figure):
    body = panel(40, 85, 420, 155, 'Skills：工作方法', ['按需读升级审查步骤', '指令、脚本与参考资源'], '#2563eb')
    body += panel(500, 85, 420, 155, 'Memory：历史事实', ['召回语言偏好与项目约定', '保留来源、范围与修订'], '#0f766e')
    body += arrow('M250 240 V290 H480 V322') + arrow('M710 240 V290 H480')
    body += panel(220, 330, 520, 135, 'Agent 宿主与模型循环', ['组装输入，检查权限与预算', '根据工具结果继续或交回控制'], '#475569')
    body += arrow('M320 465 V520') + arrow('M640 465 V520')
    body += panel(40, 530, 420, 165, 'RAG：查当前证据', ['按问题检索资料，保留引用', '资料与可信策略分开处理'], '#b45309')
    body += panel(500, 530, 420, 165, 'MCP：连接外部能力', ['Host → Client → Server', '工具、资源与提示模板'], '#2563eb')
    body += text(480, 747, '检索可在本地运行，也可经 MCP 工具暴露；图示为设计关系。', 19)
    save_figure('knowledge-capability-roles.svg', '同一个任务里的四类职责', '方法与历史进入上下文，检索提供证据，MCP 连接外部能力；宿主控制权限与预算。', 790, body)

    body = panel(40, 85, 420, 155, '索引阶段：scoped(范围).ingest', ['自写切块器：段落 + 标题 + 来源行号', '词袋 embedding → 内存向量库（按范围）'], '#2563eb')
    body += panel(500, 85, 420, 155, '查询阶段：scoped(范围).query', ['范围由宿主给定，只在范围内打分', '余弦相似度 → top-k → 相似度下限'], '#0f766e')
    body += arrow('M460 165 H495')
    body += arrow('M710 240 V285 H480 V320')
    body += panel(160, 330, 640, 155, '证据组装与检查（宿主）', ['逐条核对来源仍是建索引时的版本', '按序装入字符预算；过期或无证据则停止'], '#b45309')
    body += arrow('M480 485 V530')
    body += panel(40, 540, 420, 145, '生成：固定摘录夹具 / Agent', ['原文 + 引用；或 RagTool 交给 LlmAgent', '检索结果记为本轮来源'], '#475569')
    body += arrow('M460 610 H495')
    body += panel(500, 540, 420, 145, '校验', ['宿主：摘录属于本轮证据且出现在原文', 'CitationRequired：回答链接到检索来源'], '#0f766e')
    body += text(480, 740, '资料更新或删除后由宿主重新入库；框架替换或删除这份文档的旧块。', 19)
    save_figure('k01-rag-pipeline.svg', '从资料到有来源的回答', '切块、向量检索与范围隔离由 adk-rag 执行，来源时效、预算与摘录校验由宿主执行，Agent 场景由 CitationRequired 检查引用。', 785, body)

    data = json.loads((root / 'scripts/data/learn-agent-rust/k01-results.json').read_text())
    recall = data['recall_at_2']
    body = panel(40, 90, 420, 180, '词袋 embedding（主线）', [f"题目数：{data['labeled_queries']}", f"Recall@2：{recall['hashed-words']:.2f}", 'revert disaster 未命中 rollback'], '#2563eb')
    body += panel(500, 90, 420, 180, '只换 embedder：手写同义词表', [f"Recall@2：{recall['synonym-table']:.2f}", '语料、切块、范围、标签都不变', '同义词表是替身，不是语义模型'], '#b45309')
    body += text(480, 325, '固定英文小语料、公开标签、无真实模型；这些数值只评价本次检索。', 18)
    save_figure('k01-retrieval-results.svg', '检索命中与回答质量分别验收', '公开教学查询上，词袋 embedding 的 Recall@2 为 0.75，只换成手写同义词表后为 1.00；同义词表只是演示替换边界的替身，不代表泛化或真实模型质量。', 370, body)
