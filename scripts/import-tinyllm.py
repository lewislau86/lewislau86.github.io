"""Import the GitBook publishing files without modifying the TinyLLM checkout."""
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1]).expanduser().resolve()
repo = Path(__file__).resolve().parents[1]
target = repo / 'docs/tinyllm'
summary = (source / 'SUMMARY.md').read_text()
entries = re.findall(r'^\* \[(.+?)\]\(([^)]+\.md)\)', summary, re.M)
assert len(entries) > 1 and entries[0][1] == 'README.md', 'Expected overview followed by chapters in SUMMARY.md'
chapter_count = len(entries) - 1
assert [int(re.search(r'chapter(\d+)_', name)[1]) for _, name in entries[1:]] == list(range(chapter_count)), 'Chapter numbers must be consecutive from 0'
target.mkdir(parents=True, exist_ok=True)
manifest = {'source': 'https://github.com/lewislau86/tinyllm',
            'commit': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
            'files': {'SUMMARY.md': hashlib.sha256((source / 'SUMMARY.md').read_bytes()).hexdigest()}}
notebooks = set()
for title, filename in entries:
    raw = (source / filename).read_bytes()
    manifest['files'][filename] = hashlib.sha256(raw).hexdigest()
    text = raw.decode()
    # The optimizer lesson is complete before the source overview is updated.
    # Keep the published overview consistent without changing the source checkout.
    if filename == 'README.md' and '尚在规划中' not in (source / 'chapter12_optimizers.md').read_text():
        completed, heading, remainder = text.partition('## 课程路线（规划）')
        if '](chapter12_optimizers.md)' not in completed:
            completed = completed.replace('| [Chapter 15',
                '| [Chapter 12：优化器](chapter12_optimizers.md) | SGD、Momentum、AdaGrad、RMSProp、Adam/AdamW、Adafactor；参数组与优化器状态 | 教案与 [ch12.ipynb](chapter12_Optimizers/ch12.ipynb) 已完成 |\n| [Chapter 15')
        text = (completed + heading + remainder).replace(
            '现有 Chapter 0、Chapter 1、Chapter 15 保留原编号。',
            '现有 Chapter 0、Chapter 1、Chapter 12、Chapter 15 保留原编号。')
    notebooks.update(re.findall(r'\]\(([^)]+\.ipynb)\)', text))
    # GitBook-exported inline math has Markdown escapes; remove only those
    # escapes inside inline equations, keeping fenced code and display math intact.
    parts = re.split(r'(```[^\n]*\n.*?```|\$\$.*?\$\$|`[^`\n]+`)', text, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'(?<!\\)\$([^$\n]+)\$',
            lambda m: '$' + m[1].replace(r'\_', '_').replace(r'\[', '[')
                .replace(r'\mathrm{next\}', r'\mathrm{next}') + '$', parts[i])
        parts[i] = parts[i].replace(r'\*\*', '**')
        parts[i] = re.sub(r'\*\*([^*\n]+)\*\*', r'<strong>\1</strong>', parts[i])
        parts[i] = parts[i].replace('](README.md', '](index.md')
    text = ''.join(parts)
    text = re.sub(r'\[([^\[\]]+)\]\(([^)]+\.ipynb)\)',
        lambda m: '<a href="/tinyllm/' + html.escape(m[2], quote=True) + '" download>'
            + html.escape(m[1].replace('`', '')) + '</a>', text)
    text = re.sub(r'(\]\([^)]*\.md#)([0-9])', r'\1_\2', text)
    text = text.replace('#_10-bf16fp16-', '#_10-bf16-fp16-')
    # Keep the GitBook anchor used by the existing chapter backlinks.
    text = text.replace('## 课程路线（规划）', '## 课程路线（规划） {#课程路线规划}')
    # Keep published cross-references accurate until the source checkout catches up.
    if filename == 'README.md':
        text = text.replace('Chapter 0 中的“小词典”', 'Chapter 0 的“统一符号与总览”')
    if filename == 'chapter12_optimizers.md':
        text = text.replace('上一章我们已经知道：', '第 1、5 章已经讲过：')
    destination = 'index.md' if filename == 'README.md' else filename
    (target / destination).write_text(text)
for filename in sorted(notebooks):
    src = source / filename
    dest = repo / 'docs/public/tinyllm' / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    manifest['files'][filename] = hashlib.sha256(src.read_bytes()).hexdigest()

stages = [
    ('基础工具与稳定训练', 0, 4),
    ('构造语言模型', 4, 10),
    ('数据与训练', 10, 19),
    ('生成与扩展', 19, chapter_count),
]
sidebar = [{'text': 'TinyLLM 教程', 'items': [
    {'text': '返回知识库', 'link': '/'},
    {'text': '课程总览', 'link': '/tinyllm/'}]}]
for title, start, end in stages:
    items = []
    for label, filename in entries[start + 1:end + 1]:
        status = '（规划）' if '尚在规划中' in (source / filename).read_text() else ''
        items.append({'text': label + status, 'link': '/tinyllm/' + filename.removesuffix('.md')})
    sidebar.append({'text': title, 'collapsed': False, 'items': items})
(repo / 'docs/.vitepress/tinyllm-sidebar.json').write_text(json.dumps(sidebar, ensure_ascii=False, indent=2) + '\n')
(repo / 'scripts/tinyllm-source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(f'Imported {len(entries)} pages and {len(notebooks)} notebooks from {manifest["commit"][:7]}.')
