"""Check chapter teaching structure and produce a deliberately non-runtime coverage report."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/learn-agent-rust'
REPORT = DOCS / 'course-review.md'
DATA = ROOT / 'scripts/data/learn-agent-rust/review-coverage.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    lessons = json.loads((ROOT / 'scripts/learn-agent-rust-lessons.json').read_text())['lessons']
    written = [r for r in lessons if r['status'] == 'written']
    planned = [r for r in lessons if r['status'] == 'planned']
    prompts = json.loads((ROOT / 'scripts/data/learn-agent-rust/review-prompts.json').read_text())
    assert set(prompts) == {r['id'] for r in written}, 'Each written lesson needs an authored review focus'
    rows, errors = [], []
    table = ['| 章节 | 图片 / 片段 / 折叠 | 迁移思考焦点 | 证据边界 |', '| --- | --- | --- | --- |']
    for index, lesson in enumerate(written):
        p = DOCS / (lesson['slug'] + '.md')
        s = p.read_text()
        requirements = {
            'frontmatter': s.startswith('---\n') and 'description:' in s.split('---', 2)[1],
            'objectives': '::: tip 本章学习目标' in s,
            'map': f'<LearnAgentRustMap active="{lesson["slug"]}" />' in s,
            'pitfalls': '::: warning 常见误区' in s,
            'conclusion': bool(re.search(r'^## 本章结论', s, re.M)),
            'questions': '## 检查理解' in s,
            'references': '## 参考资料' in s,
            'transfer': '## 迁移思考：' in s,
        }
        counts = dict(images=len(re.findall(r'!\[[^\]]*\]\(', s)),
                      snippets=len(re.findall(r'^<<< ', s, re.M)),
                      details=len(re.findall(r'<details>', s)))
        if counts['images'] == 0 or counts['snippets'] == 0 or counts['details'] < 5:
            errors.append(lesson['id'] + ': missing media, runnable references or questions')
        for key, passed in requirements.items():
            if not passed:
                errors.append(lesson['id'] + ': ' + key)
        if 'chapter' in lesson:
            frontmatter = s.split('---', 2)[1]
            title = f'第 {lesson["chapter"]} 章：{lesson["title"]}'
            if f'title: "{title}"' not in frontmatter or f'\n# {title}\n' not in s:
                errors.append(lesson['id'] + ': title must match continuous chapter numbering')
            for direction, offset in [('prev', -1), ('next', 1)]:
                if not 0 <= index + offset < len(written):
                    continue
                neighbor = written[index + offset]
                prefix = f'第 {neighbor["chapter"]} 章' if 'chapter' in neighbor else f'专题 {int(neighbor["id"][1:])}'
                expected = f'{direction}:\n  text: {prefix} · {neighbor["title"]}\n  link: /learn-agent-rust/{neighbor["slug"]}'
                if expected not in frontmatter:
                    errors.append(lesson['id'] + ': stale ' + direction + ' navigation')
            if '知识专题' in s:
                errors.append(lesson['id'] + ': mainline chapter still labeled as a knowledge topic')
        for details in re.findall(r'<details>.*?</details>', s, re.S):
            if not re.search(r'</summary>\s*\n\s*\n', details) or not re.search(r'\n\s*\n\s*</details>', details):
                errors.append(lesson['id'] + ': folded Markdown must have blank lines')
        if lesson['id'] != 'P06':
            for key in ('theme', 'question', 'reasoning', 'transfer'):
                if prompts[lesson['id']][key] not in s:
                    errors.append(lesson['id'] + ': stale transfer prompt ' + key)
        for forbidden in ('目前仍为提纲', '下一章提纲', '课程学习包仍待实现'):
            if forbidden in s:
                errors.append(lesson['id'] + ': stale status ' + forbidden)
        focus = prompts[lesson['id']]
        label = f'第 {lesson["chapter"]} 章' if 'chapter' in lesson else f'专题 {int(lesson["id"][1:])}'
        table.append('| [{} · {}](./{}.md) | {} / {} / {} | {} | {} |'.format(
            label, lesson['title'], lesson['slug'], counts['images'], counts['snippets'], counts['details'], focus['theme'], focus['boundary']))
        rows.append(dict(id=lesson['id'], slug=lesson['slug'], status=lesson['status'],
                         checks=requirements, **counts, teaching_focus=focus['theme'],
                         evidence_boundary=focus['boundary'],
                         document_path=str(p.relative_to(ROOT))))
    planning_rows = []
    if planned:
        table.extend(['', '以下章节为教学设计，正文与实验待完成；不纳入上表的已成文覆盖率。', '',
                      '| 规划章节 | 状态 |', '| --- | --- |'])
    for lesson in planned:
        p = DOCS / (lesson['slug'] + '.md')
        s = p.read_text()
        frontmatter = s.split('---', 2)[1] if s.startswith('---\n') else ''
        title = f'第 {lesson["chapter"]} 章：{lesson["title"]}'
        required = [f'title: "{title}"', 'description:', 'status: planned', 'search: false', 'prev: false', 'next: false']
        if any(item not in frontmatter for item in required) or f'\n# {title}\n' not in s:
            errors.append(lesson['id'] + ': invalid planned title/status/navigation')
        planning_sections = ['::: info 本章状态：规划中', '## 本章问题', '## 计划验收',
                             f'<LearnAgentRustMap active="{lesson["slug"]}" />']
        if lesson['part'] == 'patterns':
            planning_sections.extend(['## 适用与不适用', '## 场景与流程', '## 状态与控制契约',
                                      '## graph-flow 实现方向', '## 已有基础与待补证据'])
        for item in planning_sections:
            if item not in s:
                errors.append(lesson['id'] + ': missing planning section ' + item)
        table.append(f'| [第 {lesson["chapter"]} 章 · {lesson["title"]}](./{lesson["slug"]}.md) | 教学设计；正文与实验待完成 |')
        planning_rows.append(dict(id=lesson['id'], slug=lesson['slug'], status='planned', document_path=str(p.relative_to(ROOT))))
    if errors:
        raise SystemExit('\n'.join(errors))
    a, b = '<!-- review-coverage:start -->', '<!-- review-coverage:end -->'
    report = REPORT.read_text()
    assert report.count(a) == report.count(b) == 1
    before, rest = report.split(a); _, after = rest.split(b)
    updated = before + a + '\n\n' + '\n'.join(table) + '\n\n' + b + after
    coverage = dict(schema_version=2, scope='documentation structure only; not runtime verification',
                    lessons=len(lessons), written_lessons=len(rows), planned_lessons=len(planning_rows),
                    all_structure_checks_passed=True, rows=rows, planning_rows=planning_rows)
    targets = {REPORT: updated, DATA: json.dumps(coverage, ensure_ascii=False, indent=2) + '\n'}
    for path, expected in targets.items():
        if args.check:
            if not path.exists() or path.read_text() != expected:
                raise SystemExit('Stale coverage: ' + str(path.relative_to(ROOT)))
        else:
            path.write_text(expected)
    print(f'Review coverage: {len(rows)} written, {len(planning_rows)} planned; documentation checks only (no runtime claim)')


if __name__ == '__main__':
    main()
