"""Controlled topical navigation, independent of the four editorial rubrics.

A story can have 0–3 editor-approved topics. The controlled vocabulary is extensible,
but never accept arbitrary scanner labels as a URL.
The editorial handoff may provide validated keys; otherwise a conservative
rule-based classifier works on headline and summary. Unknown is preferable
to a plausible but wrong subject label.
"""
from html import escape
import re
from pathlib import Path
from itertools import groupby
from scripts.site_rubrics import RUBRICS, publication_sort_key, publication_label, navigation
from scripts.site_topic_registry import load_extensions

BASE = "https://iipike.ru"
TOPICS = {
    "agents": ("ИИ-агенты", "Автономные помощники, выполнение задач и действия ИИ-агентов."),
    "safety": ("Безопасность и контроль", "Контроль поведения ИИ, риски, отключение и выравнивание моделей."),
    "cybersecurity": ("Кибербезопасность", "Взломы, уязвимости, защита систем и инструменты кибербезопасности."),
    "development": ("Разработка и код", "Программирование, инструменты разработчиков и генерация кода."),
    "infrastructure": ("Инфраструктура ИИ", "Вычисления, дата-центры, чипы, облака, серверы и энергоснабжение."),
    "engineering": ("Инженерия и устройства", "Роботы, оборудование, проектирование и физические устройства."),
    "models": ("Модели и исследования", "Новые языковые модели, архитектуры, бенчмарки и исследования."),
    "video": ("Генерация видео", "Создание видео, анимации и работа с движением."),
    "images": ("Генерация изображений", "Создание и редактирование графики, фотографий и дизайна."),
    "audio": ("Голос и звук", "Синтез речи, озвучка, музыка и голосовые модели."),
    "business": ("ИИ в бизнесе", "Автоматизация рабочих процессов, экономика и внедрение в компаниях."),
    "society": ("Законы и общество", "Регулирование ИИ, суды, авторское право и общественные последствия."),
    "search": ("ИИ-поиск и веб", "Поисковые системы, ответы ИИ, браузеры и доступность информации в интернете."),
    "health": ("Медицина и биотехнологии", "Медицинские применения, диагностика, препараты и биологические исследования."),
    "science": ("Наука и экология", "Фундаментальная наука, космос, экология и наблюдение за природой."),
    "finance": ("Деньги и инвестиции", "Финансирование ИИ, рынки, капитал, IPO и экономика технологических компаний."),
    "apps": ("Приложения и сервисы", "Пользовательские функции ChatGPT, Gemini, Claude и других приложений и сервисов."),
} 
# Built-in 17 topic keys remain stable. Emerging categories are appended by
# the editor as reviewed DATA; no Python code change is needed for each topic.
# An invalid manifest fails closed before an article is released.
BUILTIN_TOPICS = dict(TOPICS)
TOPICS.update(load_extensions(
    Path(__file__).resolve().parents[1] / "data" / "topic_extensions.json",
    BUILTIN_TOPICS,
    Path(__file__).resolve().parents[1] / "news.json",
))

# Matches should describe actual subject matter, not merely mention AI or
# a company name. Title matches dominate; summaries only break close ties.
_PATTERNS = {
    "agents": r"\b(?:агент\w*|agentic|agents?\b|автономн\w+\s+помощник\w*)",
    "safety": r"(?:выключ\w*|отключ\w*|стоп.кра\w*|контрол\w*\s+(?:над\s+)?ии|безопасност\w+\s+ии|угроз\w+\s+контрол\w*|самосовершенств\w*|потер\w+\s+контрол\w*|обман\w+\s+контрол\w*|safety\b|alignment\b)",
    "cybersecurity": r"(?:взлом\w*|хакер\w*|кибер\w*|уязвимост\w*|утечк\w*|парол\w*|фишинг\w*|malware\b|ransomware\b|bug.bounty\b)",
    "development": r"(?:codex\b|claude code\b|программир\w*|разработк\w+\s+код\w*|напис\w+\s+код\w*|генерац\w+\s+код\w*|git\b|репозитор\w*|mcp\b|github\b|компилятор\w*)",
    "infrastructure": r"(?:дата.центр\w*|сервер\w*|облачн\w+\s+(?:инфраструктур\w*|вычислен\w*)|видеокарт\w*|gpu\b|nvidia\s+(?:blackwell|rubin)|ускорител\w*|электричеств\w*|энергосистем\w*|чип\w*|процессор\w*|вычислительн\w+\s+мощност\w*)",
    "engineering": r"(?:гаджет\w*|устройств\w*|робот\w*|завод\w*|инженер\w*|производств\w*|электроник\w*|3d.печать|печатн\w+\s+плат\w*|физическ\w+\s+объект\w*)",
    "models": r"(?:нейросет\w*|модел\w*|llm\b|бенчмарк\w*|параметр\w*|обучени\w+\s+ии|исследовани\w+\s+ии|benchmark\b|open.weight|open.source)",
    "video": r"(?:видеомодел\w*|генерац\w+\s+видео|генерир\w+\s+видео|созда\w+\s+(?:видео|ролик\w*)|видеоролик\w*|кинематограф\w*|анимаци\w*|seedance\b|kling\b|pika\b|sora\b|omnihuman\b)",
    "images": r"(?:генерац\w+\s+(?:картин\w*|изображен\w*|фотограф\w*)|рису\w+\s+(?:картин\w*|изображен\w*)|изображен\w*|фоторедактор\w*|фотографи\w*|flux\b|midjourney\b|дизайн\w*)",
    "audio": r"(?:голос\w*|озвуч\w*|звук\w*|аудио\w*|музык\w*|реч\w*|elevenlabs\b|suno\b|tts\b|speech\b)",
    "business": r"(?:компан\w+\s+внедр\w*|внедр\w+\s+ии|офисн\w+\s+работ\w*|сотрудник\w*|клиент\w*|подписк\w*|экономи\w+\s+час\w*|корпоративн\w*|бизнес\w*|автоматизаци\w+\s+работ\w*)",
    "society": r"(?:закон\w*|суд\w*|регулировани\w*|запрет\w*|правительств\w*|депутат\w*|авторск\w+\s+прав\w*|выбор\w*|парламент\w*|реклам\w+\s+chatgpt|обществ\w*)",
    "search": r"(?:поиск\w*|поисков\w*|выдач\w*|источник\w*\s+(?:в\s+)?ответ\w*|ссылк\w*\s+в\s+ответ\w*|браузер\w*|webai\b|ai\s*overviews?\b|ai\s*mode\b)",
    "health": r"(?:медицин\w*|биолог\w*|биотех\w*|врач\w*|диагностик\w*|заболеван\w*|лекарств\w*|препарат\w*|антител\w*|пациент\w*)",
    "science": r"(?:научн\w+\s+(?:загадк\w*|исследован\w*|открыти\w*)|учён\w*|физик\w*|частиц\w*|cern\b|спутник\w*|космос\w*|орбит\w*|эколог\w*|климат\w*|лес\w*|растени\w*)",
    "finance": r"(?:ipo\b|бирж\w*|акци\w*|рынок\w+\s+капитал\w*|инвестиц\w*|инвестор\w*|финансирован\w*|миллиард\w*\s+доллар\w*|ии.пузыр\w*|триллион\w*|котировк\w*)",
    "apps": r"(?:приложен\w*|сервис\w*|пользовател\w*|переписк\w*|pdf\b|таблиц\w*|pin.код\w*|домашн\w+\s+(?:помощник\w*|центр\w*)|голосов\w+\s+помощник\w*|siri\b|чат.бот\w*)",
}
_REGEX = {key: re.compile(value, re.IGNORECASE) for key, value in _PATTERNS.items()}
MAX_TOPICS = 3


def validate_topics(values):
    if not isinstance(values, list) or len(values) > MAX_TOPICS:
        raise ValueError("Topics must be a list of at most three approved keys")
    if any(not isinstance(key, str) or key not in TOPICS for key in values):
        raise ValueError("Unknown topic key: only the controlled HPII vocabulary is accepted")
    if len(set(values)) != len(values):
        raise ValueError("Repeated topic key")
    return list(values)


def infer_topics(title, summary):
    if not isinstance(title, str) or not isinstance(summary, str):
        return []
    # A strong subject signal from the headline outranks incidental body mentions.
    scores = []
    for order, (key, regex) in enumerate(_REGEX.items()):
        title_hits = len(regex.findall(title))
        summary_hits = len(regex.findall(summary[:350]))
        if not title_hits and not summary_hits:
            continue
        score = title_hits * 5 + min(summary_hits, 2)
        if title_hits or summary_hits >= 2:
            scores.append((score, -order, key))
    scores.sort(reverse=True)
    # Auto-inference stays at two strong subjects; weak summary-only signals cannot
    # crowd out the central story.
    selected = [item[-1] for item in scores if item[0] >= 2][:min(MAX_TOPICS, 2)]
    return selected


def topics_for_record(record):
    return validate_topics(record.get("topics", []))


def render_topic_links(values):
    values = validate_topics(values)
    if not values:
        return ""
    return ('<nav class="topic-links" aria-label="Темы статьи">'
            + "".join(
                '<a href="../../topics/' + key + '/">' + escape(TOPICS[key][0]) + "</a>"
                for key in values
            )
            + '</nav>')


def active_topics(records):
    return [key for key in TOPICS if any(key in topics_for_record(x) for x in records)]


def topic_shell(title, description, prefix, canonical, content, robots=""):
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f6f3eb">
<meta name="description" content="{escape(description, quote=True)}">
<link rel="canonical" href="{canonical}">{robots}
<title>{escape(title)}</title><link rel="icon" href="{prefix}assets/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="{prefix}assets/site.css"></head>
<body class="home-v1 rubric-r2 topic-r2"><header class="header"><div class="wrap bar">
<a class="logo" href="{prefix}" aria-label="Хроники Пикирующего ИИ — главная"><span class="badge" aria-hidden="true">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu home-menu" aria-label="Основное меню"><a href="{prefix}articles/">Все статьи</a><a href="{prefix}briefs/">Коротко</a><a href="{prefix}dossier/">Досье</a><a href="{prefix}entities/">Компании и продукты</a></nav></div></header>
<div class="home-v1-rubrics"><div class="wrap"><nav class="rubric-navigation" aria-label="Рубрики">{navigation(prefix)}</nav></div></div>
<main class="wrap rubric-main">{content}</main>
<footer class="footer"><div class="wrap home-v1-footer"><span>Хроники Пикирующего ИИ · Новости без истерики</span><nav><a href="{prefix}registry/">Архив Дзена</a><a href="{prefix}drafts/">Лаборатория редакции</a><a href="{prefix}feed.xml">RSS</a></nav></div></footer>
<script defer src="{prefix}assets/social-footer.js"></script></body></html>
'''


# Presentation only: topic taxonomy and editorial assignments stay independent.
_TOPIC_ATLAS_GROUPS = (
    ("Технологии и исследования", ("agents", "models", "development", "infrastructure", "engineering", "science")),
    ("Творчество и инструменты", ("video", "images", "audio", "apps", "search", "entertainment")),
    ("Люди, безопасность и экономика", ("safety", "cybersecurity", "society", "business", "finance", "crypto", "health", "education", "ai-in-russia")),
)
_TOPIC_ATLAS_ICONS = {
    "agents": ("--tone:#38675a;--tint:#dce9df", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"5\" r=\"2.5\"/><circle cx=\"5\" cy=\"19\" r=\"2.5\"/><circle cx=\"19\" cy=\"19\" r=\"2.5\"/><path d=\"M12 8v4M5 16v-4h14v4\"/></svg>"),
    "models": ("--tone:#536c49;--tint:#e4ead6", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5\"/></svg>"),
    "development": ("--tone:#465f74;--tint:#dce9ee", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18\"/></svg>"),
    "infrastructure": ("--tone:#7b6140;--tint:#eee3ce", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"3\" width=\"18\" height=\"7\" rx=\"2\"/><rect x=\"3\" y=\"14\" width=\"18\" height=\"7\" rx=\"2\"/><path d=\"M7 6.5h.1M7 17.5h.1M12 6.5h5M12 17.5h5\"/></svg>"),
    "engineering": ("--tone:#635b7b;--tint:#e9e1ee", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M9 2h6l1 4 4 1 2 5-3 3 1 4-5 3-3-3-3 3-5-3 1-4-3-3 2-5 4-1z\"/></svg>"),
    "science": ("--tone:#527342;--tint:#e1ecd9", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><ellipse cx=\"12\" cy=\"12\" rx=\"10\" ry=\"4\" transform=\"rotate(60 12 12)\"/><ellipse cx=\"12\" cy=\"12\" rx=\"10\" ry=\"4\" transform=\"rotate(-60 12 12)\"/><ellipse cx=\"12\" cy=\"12\" rx=\"10\" ry=\"4\"/><circle cx=\"12\" cy=\"12\" r=\"1\"/></svg>"),
    "video": ("--tone:#93544e;--tint:#f3dfdb", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"4\" width=\"18\" height=\"16\" rx=\"3\"/><path d=\"m10 9 5 3-5 3z\"/></svg>"),
    "images": ("--tone:#886431;--tint:#f1e7cf", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\"/><circle cx=\"8\" cy=\"8\" r=\"1.5\"/><path d=\"m3 18 6-6 4 4 3-3 5 5\"/></svg>"),
    "audio": ("--tone:#66517c;--tint:#e9e1f0", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 10v4M7 6v12M12 3v18M17 7v10M21 10v4\"/></svg>"),
    "apps": ("--tone:#53617e;--tint:#e1e6f0", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"3\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"14\" y=\"3\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"3\" y=\"14\" width=\"7\" height=\"7\" rx=\"1.5\"/><rect x=\"14\" y=\"14\" width=\"7\" height=\"7\" rx=\"1.5\"/></svg>"),
    "search": ("--tone:#456e81;--tint:#dce9ee", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"10\" cy=\"10\" r=\"6\"/><path d=\"m15 15 6 6\"/></svg>"),
    "entertainment": ("--tone:#925b66;--tint:#f0dfe4", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 6h18v15H3zM3 6l3-4 5 4 3-4 5 4M3 10h18\"/><path d=\"m10 13 5 3-5 3z\"/></svg>"),
    "safety": ("--tone:#91513b;--tint:#f1ded0", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 3 21 7v5c0 5-5 8-9 10-4-2-9-5-9-10V7z\"/><path d=\"m8 12 3 3 5-6\"/></svg>"),
    "cybersecurity": ("--tone:#4b5d78;--tint:#e0e6ed", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"4\" y=\"10\" width=\"16\" height=\"11\" rx=\"2\"/><path d=\"M8 10V7a4 4 0 0 1 8 0v3M12 14v3\"/></svg>"),
    "society": ("--tone:#8a5e43;--tint:#ede2d5", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 3v18M5 21h14M3 7h18M6 7l-4 8h8zM18 7l-4 8h8z\"/></svg>"),
    "business": ("--tone:#3b7164;--tint:#dcece5", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"7\" width=\"18\" height=\"14\" rx=\"2\"/><path d=\"M8 7V3h8v4M3 12h18M10 12v3h4v-3\"/></svg>"),
    "finance": ("--tone:#80622e;--tint:#eee7d2", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 20V4M3 20h18M7 16l5-6 4 3 5-8M16 5h5v5\"/></svg>"),
    "crypto": ("--tone:#8c683a;--tint:#f0e3ce", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10\"/></svg>"),
    "health": ("--tone:#4c776b;--tint:#dcebe2", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M9 3h6v6h6v6h-6v6H9v-6H3V9h6z\"/></svg>"),
    "education": ("--tone:#6b597e;--tint:#e9e1ee", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"m2 8 10-5 10 5-10 5zM6 10v7c3 3 9 3 12 0v-7M22 8v9\"/></svg>"),
    "ai-in-russia": ("--tone:#9b482a;--tint:#f0dfd1", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M5 22V3m0 1h15l-3 5 3 5H5\"/><path d=\"M5 8h12M5 11h13\"/></svg>"),
}
_TOPIC_ATLAS_DEFAULT = ("--tone:#53617e;--tint:#e1e6f0", "<svg aria-hidden=\"true\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"4\" y=\"4\" width=\"16\" height=\"16\" rx=\"3\"/><path d=\"M8 9h8M8 15h8\"/></svg>")


def render_topics_index(records):
    count = {key: sum(key in topics_for_record(row) for row in records) for key in TOPICS}
    active = sum(bool(n) for n in count.values())
    grouped = {key for _, keys in _TOPIC_ATLAS_GROUPS for key in keys}
    groups = list(_TOPIC_ATLAS_GROUPS) + [
        ("Другие темы", tuple(key for key in TOPICS if key not in grouped))
    ]

    def row(key):
        name, description = TOPICS[key]
        style, icon = _TOPIC_ATLAS_ICONS.get(key, _TOPIC_ATLAS_DEFAULT)
        return (
            f'<a class="directory-row" href="{escape(key, quote=True)}/" style="{style}">'
            '<span class="symbol">' + icon + '</span><span class="row-copy"><strong>' +
            escape(name) + '</strong><span>' + escape(description) + '</span></span>' +
            f'<span class="row-count">{count[key]}<small>материалов</small></span>' +
            '<span class="row-arrow" aria-hidden="true">↗</span></a>'
        )

    sections = []
    for name, keys in groups:
        links = "\n".join(row(key) for key in keys if count.get(key))
        if links:
            sections.append(
                f'<section class="directory-section"><div class="section-label"><span>{len(sections)+1:02d}</span>'
                '<h2>' + escape(name) + '</h2></div><div class="directory-list">' +
                links + '</div></section>'
            )
    content = (
        f'<div class="rubric-head"><div><span class="rubric-kicker">ХПИИ / Темы</span><h1>Темы новостей</h1><p class="rubric-deck">Одна тема может встречаться в разных рубриках. Выбирайте, что интересно.</p></div><span class="rubric-count">Тем: {active}</span></div>'
        '<nav class="topic-atlas" aria-label="Все темы">' + "\n".join(sections) + '</nav>'
    )
    return topic_shell("Темы — ХПИИ", "Темы новостей об искусственном интеллекте: ИИ-агенты, безопасность, модели, разработка, видео и другие направления.",
                       "../", BASE + "/topics/", content)


def render_topic_page(key, records):
    if key not in TOPICS:
        raise ValueError("Unknown topic")
    name, description = TOPICS[key]
    articles = sorted((r for r in records if key in topics_for_record(r)),
                      key=publication_sort_key, reverse=True)

    def card(row):
        label = publication_label(row)
        _, _, time = label.partition(" · ")
        rubric = row.get("rubric", "news")
        return (
            f'<a class="archive-card" href="../../{escape(row["url"], quote=True)}">'
            f'<span class="rubric-time" aria-label="{escape(label, quote=True)}">{escape(time)}</span>'
            f'<img loading="lazy" src="../../{escape(row["cover"], quote=True)}" alt="Обложка статьи">'
            f'<div class="rubric-copy"><h3>{escape(row["title"])}</h3>'
            f'<small class="date"><span class="archive-rubric" data-rubric="{escape(rubric)}">{escape(RUBRICS[rubric]["name"])}</span></small>'
            f'<p>{escape(row["summary"])}</p></div>'
            '<span class="rubric-arrow" aria-hidden="true">↗</span></a>'
        )

    days = []
    for day, group in groupby(articles, key=lambda r: publication_label(r).partition(" · ")[0]):
        days.append('<section class="rubric-day"><h2 class="rubric-day-title">' +
                    escape(day) + '</h2><div class="rubric-day-list">' +
                    "\n".join(card(row) for row in group) + '</div></section>')
    cards = "\n".join(days) or '<p class="rubric-empty">Публикаций на эту тему пока нет.</p>'
    robots = "" if articles else '<meta name="robots" content="noindex, follow">'
    content = (
        '<div class="rubric-head topic-detail-head"><div><a class="topic-back" href="../">← Все темы</a>'
        '<span class="rubric-kicker">ХПИИ / Тема</span><h1>' + escape(name) +
        '</h1><p class="rubric-deck">' + escape(description) + '</p></div>'
        '<span class="rubric-count">Материалов: ' + str(len(articles)) + '</span></div>' + cards
    )
    return topic_shell(name + " — Темы ХПИИ", description, "../../",
                       BASE + "/topics/" + key + "/", content, robots)


def render_all_topics(records, root):
    root = Path(root)
    outputs = {root / "topics" / "index.html": render_topics_index(records)}
    from scripts.site_rubrics import paginate_listing
    for key in TOPICS:
        outputs.update(paginate_listing(root / "topics" / key / "index.html",
                                        render_topic_page(key, records)))
    return outputs
