#!/usr/bin/env python3
"""Publish labelled AI draft previews on GitHub Pages; never touch news.json or RSS."""
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_test_output" / "editorial"
SHELF = ROOT / "drafts"


def esc(value):
    return html.escape(str(value), quote=True)


def shell(page_title, body, prefix, description):
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="description" content="{esc(description)}">
<title>{esc(page_title)} — Хроники Пикирующего ИИ</title>
<link rel="stylesheet" href="{prefix}assets/site.css">
<style>
.draft-note{{border-left:4px solid #e54731;background:#ece4d8;padding:20px 25px;margin:27px 0 35px}}
.draft-note strong{{display:block;font-size:16px;margin-bottom:5px}}
.draft-note p{{margin:0;font-size:15px}}
.draft-item{{display:grid;grid-template-columns:250px minmax(0,1fr);gap:23px;padding:23px 0;border-top:1px solid #d9d5cd;text-decoration:none}}
.draft-item img{{aspect-ratio:16/9;object-fit:cover}}
.draft-item h2{{font-size:clamp(22px,3vw,30px);margin:6px 0 12px}}
.draft-item p{{margin:0;color:#626469}}
.draft-reading{{max-width:840px;margin:0 auto 75px;font-size:18px;line-height:1.85}}
.draft-reading p{{margin:0 0 23px}}
.draft-reading .draft-source{{font-size:14px;border-top:1px solid #d9d5cd;padding-top:22px;overflow-wrap:anywhere}}
.draft-cover{{margin:25px 0 30px}}
.draft-cover img{{aspect-ratio:16/9;object-fit:cover}}
@media(max-width:650px){{.draft-item{{grid-template-columns:1fr}}.draft-reading{{font-size:16px}}}}
</style></head><body>
<header class="header"><div class="wrap bar"><a class="logo" href="{prefix}index.html"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a><nav class="menu"><a href="{prefix}index.html">Главная</a><a href="{prefix}drafts/">Авточерновики</a></nav></div></header>
<main class="wrap">{body}</main>
<footer class="footer"><div class="wrap"><strong>Хроники Пикирующего ИИ</strong><p>Здесь размещаются автоматически созданные материалы для испытаний редакционной системы. Их содержание может содержать ошибки.</p></div></footer></body></html>'''


def parse_markdown(raw):
    match = re.fullmatch(
        r'# ([^\n]+)\n\n\*Черновик, НЕ ПУБЛИКОВАТЬ без проверки\.[^\n]*\*\n\n(.*?)\n\n\*\*Первоисточник:\*\*.*',
        raw.strip(), flags=re.DOTALL)
    if not match:
        raise ValueError('Unexpected draft.md layout; public preview not created')
    headline, article = match.groups()
    paras = [part.strip() for part in re.split(r'\n\s*\n', article) if part.strip()]
    if not paras or len(headline) > 180:
        raise ValueError('Empty or malformed draft')
    return headline, paras


def build(output=OUTPUT, shelf=SHELF):
    required = [output / x for x in ('draft.md', 'cover.png', 'report.json')]
    if not any(p.exists() for p in required):
        print('No new draft: website preview unchanged.')
        return False
    if not all(p.is_file() and p.stat().st_size for p in required):
        raise RuntimeError('Partial draft package; cannot update preview')
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    if report.get('status') != 'awaiting_human_quality_review':
        raise ValueError('Refusing to display unexpected editorial status')
    source = report['source_url']
    url = urlparse(source)
    if url.scheme != 'https' or url.hostname not in {'deepmind.google', 'openai.com', 'blog.google', 'www.blog.google', 'mistral.ai', 'www.mistral.ai'}:
        raise ValueError('Source must be first-party HTTPS URL')
    date = report['date']
    if not re.fullmatch(r'20\d\d-\d\d-\d\d', date):
        raise ValueError('Invalid draft date')
    headline, paragraphs = parse_markdown((output / 'draft.md').read_text(encoding='utf-8'))
    draft_id = hashlib.sha256(source.encode('utf-8')).hexdigest()[:20]
    shelf.mkdir(parents=True, exist_ok=True)
    index_path = shelf / 'index.json'
    rows = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
    if not isinstance(rows, list):
        raise ValueError('Invalid preview catalog')
    article_dir = shelf / draft_id
    article_dir.mkdir(exist_ok=True)
    shutil.copyfile(output / 'cover.png', article_dir / 'cover.png')
    source_name = report['source_name']
    body_text = '\n'.join('<p>' + esc(part) + '</p>' for part in paragraphs)
    page_body = f'''
<div class="overline"><span>ХПИИ / Испытание автономной редакции</span><b>{esc(date)}</b></div>
<h1 style="max-width:1000px">{esc(headline)}</h1>
<div class="draft-note"><strong>⚠ Автоматический черновик — не проверен редактором</strong><p>Этот текст и иллюстрация созданы автоматически. В статье могут быть неточности; это не опубликованная редакционная новость.</p></div>
<figure class="draft-cover"><img src="cover.png" width="1024" height="576" alt="Автоматически созданная иллюстрация"><figcaption class="caption">Тестовая иллюстрация ИИ · качество не подтверждено</figcaption></figure>
<div class="draft-reading">{body_text}
<div class="draft-source"><strong>Первоисточник:</strong> {esc(source_name)} — <a href="{esc(source)}" rel="nofollow noopener noreferrer">{esc(source)}</a><p>Дата первоисточника: {esc(report['source_date'][:10])}. Дата черновика: {esc(date)}.</p></div></div>
<p style="margin-bottom:60px"><a class="button" href="../">← Все авточерновики</a></p>'''
    (article_dir / 'index.html').write_text(shell(headline, page_body, '../../', headline), encoding='utf-8')
    current = {'id': draft_id, 'date': date, 'title': headline,
               'source_name': source_name, 'source_url': source}
    rows = [row for row in rows if row.get('id') != draft_id] + [current]
    rows.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    index_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cards = '\n'.join(
        f'<a class="draft-item" href="{esc(row["id"])}/"><img src="{esc(row["id"])}/cover.png" alt="">'
        f'<div><span class="kicker">{esc(row["date"])} · {esc(row["source_name"])}</span>'
        f'<h2>{esc(row["title"])}</h2><p>Открыть текст и иллюстрацию ↗</p></div></a>'
        for row in rows)
    listing = f'''
<div class="overline"><span>ХПИИ / Лаборатория</span><b>Тестовые выпуски ({len(rows)})</b></div>
<h1>Авточерновики</h1><p class="summary">Здесь можно смотреть, что самостоятельно создаёт наша новостная система: новости, статьи, обложки, первоисточники. Никаких архивов ZIP.</p>
<div class="draft-note"><strong>Это не обычная новостная лента</strong><p>Каждый материал сделан программой без окончательной редакторской проверки. Ошибки возможны. В соцсети эти тексты не отправляются.</p></div>
<section class="archive" style="margin-top:45px"><h2>Готовые тестовые выпуски</h2>{cards}</section>'''
    (shelf / 'index.html').write_text(shell('Авточерновики', listing, '../', 'Автоматические тестовые выпуски ХПИИ'), encoding='utf-8')
    print(f'Website preview saved: drafts/{draft_id}/ (total {len(rows)})')
    return True


if __name__ == '__main__':
    try:
        build()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print('Preview generation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
