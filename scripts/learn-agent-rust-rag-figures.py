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

    body = panel(40, 85, 420, 155, '索引阶段：真实 Markdown', ['段落切块 + 标题 + 来源行号', '范围、完整快照与显示指纹'], '#2563eb')
    body += panel(500, 85, 420, 155, '查询阶段：宿主给定范围', ['先过滤，再统计词频并排序', 'BM25 → top-k'], '#0f766e')
    body += arrow('M460 165 H495')
    body += arrow('M710 240 V285 H480 V320')
    body += panel(160, 330, 640, 155, '证据组装与检查', ['逐条核对来源仍然存在且内容未变', '按序装入字符预算；过期或无证据则停止'], '#b45309')
    body += arrow('M480 485 V530')
    body += panel(40, 540, 420, 145, '生成边界：固定摘录夹具', ['原文 + citation', '真实模型请求在这里替换'], '#475569')
    body += arrow('M460 610 H495')
    body += panel(500, 540, 420, 145, '宿主独立校验', ['引用属于本次证据集合', '摘录确实出现在原文中'], '#0f766e')
    body += text(480, 740, '更新或删除来源后重建索引；本例索引只在当前进程保存。', 19)
    save_figure('k01-rag-pipeline.svg', '从资料到有来源的回答', '检索、范围过滤、版本核对与引用检查真实执行；生成器采用固定摘录夹具。', 785, body)

    data = json.loads((root / 'scripts/data/learn-agent-rust/k01-results.json').read_text())
    body = panel(40, 90, 420, 180, '公开教学检索题', [f"题目数：{data['labeled_queries']}", f"Recall@2：{data['recall_at_2']:.2f}", f"MRR@2：{data['mrr_at_2']:.2f}"], '#2563eb')
    body += panel(500, 90, 420, 180, '有意保留的失败', ['revert disaster', '词面未命中 rollback', '返回无证据，保留失败记录'], '#b45309')
    body += text(480, 325, '固定英文小语料、公开标签、无真实模型；这些数值只评价本次检索。', 18)
    save_figure('k01-retrieval-results.svg', '检索命中与回答质量分别验收', '公开教学查询上的真实检索指标为 0.75；保留同义表达未召回案例，不代表泛化或真实模型正确率。', 370, body)
