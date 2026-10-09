"""Publish local mini-redis reading notes, with a reproducible source bundle."""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

source = Path(sys.argv[1]).expanduser().resolve()
project = source.parent
repo = Path(__file__).resolve().parents[1]
target = repo / 'docs/mini-redis'
public = repo / 'docs/public/mini-redis'
commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
tracked = subprocess.check_output(['git', '-C', str(project), 'ls-files', '-z'], text=True).split('\0')
# Publish only source, examples, tests, manifests and license, not build outputs
# or local environment files. Include the requested notes and labs separately.
source_files = [project / p for p in tracked if p and
    (p.startswith(('src/', 'tests/', 'examples/')) or p in ('Cargo.toml', 'Cargo.lock', 'LICENSE', 'README.md'))]
source_files += [p for p in source.rglob('*') if p.is_file() and
    (p.suffix in ('.md', '.rs') or p.name in ('Cargo.toml', 'Cargo.lock')) and
    not set(p.relative_to(source).parts) & {'target', '.git'}]
source_files = sorted(set(source_files))
notes = sorted(p for p in source_files if p.suffix == '.md' and p.is_relative_to(source))
chapters = sorted(source.glob('[0-9][0-9]-*.md'))
assert chapters, 'No numbered chapters found'
assert len({p.name[:2] for p in chapters}) == len(chapters), 'Duplicate chapter numbers'
manifest = {'upstream': 'https://github.com/tokio-rs/mini-redis', 'source_commit': commit,
            'content': 'Local docs and working-tree source snapshot; file hashes identify the published content.',
            'files': {}}
public.mkdir(parents=True, exist_ok=True)
for path in source_files:
    relative = path.relative_to(project)
    data = path.read_bytes()
    manifest['files'][relative.as_posix()] = hashlib.sha256(data).hexdigest()
    dest = public / 'source' / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

blob_base = 'https://github.com/lewislau86/lewislau86.github.io/'
def published_path(path):
    relative = path.relative_to(source)
    return relative.with_name('index.md') if relative.name == 'README.md' else relative

def convert_link(match, current):
    url = match[1]
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return match[0]
    linked = (current.parent / parsed.path).resolve()
    assert linked.is_relative_to(project) and linked.exists(), (current, url)
    if linked in notes:
        dest = '/mini-redis/' + published_path(linked).as_posix()
    else:
        if linked.is_file(): assert linked in source_files, linked
        kind = 'tree' if linked.is_dir() else 'blob'
        dest = blob_base + kind + '/master/docs/public/mini-redis/source/' + quote(linked.relative_to(project).as_posix())
    if parsed.fragment: dest += '#' + parsed.fragment
    return '](' + dest + ')'

for path in notes:
    text = path.read_text()
    # Preserve fenced code exactly; only adapt navigation in prose.
    chunks = re.split(r'(```[^\n]*\n.*?```)', text, flags=re.S)
    for i in range(0, len(chunks), 2):
        chunks[i] = re.sub(r'\]\(([^)]+)\)', lambda m: convert_link(m, path), chunks[i])
    text = ''.join(chunks)
    if path == source / 'README.md':
        text = text.replace('## 阅读顺序', '''## 下载源码与实验

<a href="/mini-redis/mini-redis-study.zip" download>下载完整学习包（ZIP）</a>，解压后进入 `mini-redis-study/`，即可按正文的相对路径查阅源码和运行命令。学习包包含本教程、对应源码、Cargo 锁文件与配套实验。

网页中的源码链接指向本次发布的代码快照。实验需要在本地 Rust 环境运行，浏览器提供阅读和下载。

## 阅读顺序''')
        text = text.replace('文中的相对源码链接指向本仓库；', '文中的源码链接指向随教程发布的代码快照；')
    dest = target / published_path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('---\neditLink: false\n---\n\n' + text)

with zipfile.ZipFile(public / 'mini-redis-study.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in source_files:
        info = zipfile.ZipInfo('mini-redis-study/' + path.relative_to(project).as_posix(), (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes())
sidebar = [{'text': 'mini-redis 源码分析', 'items': [
    {'text': '返回知识库', 'link': '/'}, {'text': '教程总览与下载', 'link': '/mini-redis/'}]}]
for title, start, end in [('整体架构', 0, 0), ('入门与请求链路', 1, 4), ('并发、存储与生命周期', 5, 10), ('架构与实践', 11, 99)]:
    sidebar.append({'text': title, 'collapsed': False, 'items': [
        {'text': p.read_text().splitlines()[0].removeprefix('# '), 'link': '/mini-redis/' + p.stem}
        for p in chapters if start <= int(p.name[:2]) <= end]})
sidebar.append({'text': '配套资料', 'items': [
    {'text': '配套实验', 'link': '/mini-redis/labs/'},
    {'text': '原始验证记录', 'link': '/mini-redis/validation'}]})
(repo / 'docs/.vitepress/mini-redis-sidebar.json').write_text(json.dumps(sidebar, ensure_ascii=False, indent=2) + '\n')
(repo / 'scripts/mini-redis-source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(f'Imported {len(notes)} pages and bundled {len(source_files)} files from local mini-redis docs.')
