"""Controlled topical navigation, independent of the four editorial rubrics.

A story can have 0–2 topics. The controlled vocabulary is extensible,
but never accept arbitrary scanner labels as a URL.
The editorial handoff may provide validated keys; otherwise a conservative
rule-based classifier works on headline and summary. Unknown is preferable
to a plausible but wrong subject label.
"""
from html import escape
import re
from pathlib import Path
from scripts.site_rubrics import RUBRICS, publication_date

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
MAX_TOPICS = 2


def validate_topics(values):
    if not isinstance(values, list) or len(values) > MAX_TOPICS:
        raise ValueError("Topics must be a list of at most two approved keys")
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
    # At most two independent subjects; weak summary-only signals cannot
    # crowd out the central story.
    selected = [item[-1] for item in scores if item[0] >= 2][:MAX_TOPICS]
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


def render_topics_index(records):
    count = {key: sum(key in topics_for_record(row) for row in records) for key in TOPICS}
    links = "".join(
        '<a class="topic-index-link" href="' + key + '/"><strong>' + escape(TOPICS[key][0])
        + '</strong><span>' + str(count[key]) + ' материалов</span></a>'
        for key in TOPICS if count[key]
    )
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Темы новостей об искусственном интеллекте: ИИ-агенты, безопасность, модели, разработка, видео и другие направления.">
<link rel="canonical" href="{BASE}/topics/"><title>Темы — ХПИИ</title>
<link rel="stylesheet" href="../assets/site.css"></head>
<body><header class="header"><div class="wrap bar">
<a class="logo" href="../"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../articles/">Все статьи</a><a href="../">Главная</a></nav></div></header>
<main class="wrap"><div class="overline">ХПИИ / Темы</div><h1>Темы новостей</h1>
<p class="summary">Одна тема может встречаться в разных рубриках. Выбирайте, что интересно.</p>
<nav class="topic-index-grid" aria-label="Все темы">{links}</nav></main>
<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ</div></footer>
<script defer src="../assets/social-footer.js"></script></body></html>
'''


def render_topic_page(key, records):
    if key not in TOPICS:
        raise ValueError("Unknown topic")
    name, description = TOPICS[key]
    articles = sorted(
        (r for r in records if key in topics_for_record(r)),
        key=lambda r: (r["published"], r["id"]), reverse=True
    )
    cards = "\n".join(
        '<a class="archive-card" href="../../' + escape(r["url"], quote=True) + '">'
        '<img loading="lazy" src="../../' + escape(r["cover"], quote=True) + '" alt="Обложка статьи">'
        '<span><small class="date">' + escape(publication_date(r["published"]))
        + ' · ' + escape(RUBRICS[r.get("rubric", "news")]["name"]) + '</small>'
        '<h3>' + escape(r["title"]) + '</h3>'
        '<p>' + escape(r["summary"]) + '</p></span>'
        '<span aria-hidden="true">↗</span></a>'
        for r in articles
    ) or '<p class="summary">Публикаций на эту тему пока нет.</p>'
    robots = "" if articles else '<meta name="robots" content="noindex, follow">'
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(description, quote=True)}">
<link rel="canonical" href="{BASE}/topics/{key}/">{robots}
<title>{escape(name)} — Темы ХПИИ</title><link rel="stylesheet" href="../../assets/site.css"></head>
<body><header class="header"><div class="wrap bar">
<a class="logo" href="../../"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../">Все темы</a><a href="../../articles/">Все статьи</a></nav></div></header>
<main class="wrap"><div class="overline">ХПИИ / Тема</div><h1>{escape(name)}</h1>
<p class="summary">{escape(description)}</p><p class="date">{len(articles)} материалов</p>
<a href="../">← Все темы</a>
<section class="archive"><h2>Публикации</h2>{cards}</section></main>
<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ</div></footer>
<script defer src="../../assets/social-footer.js"></script></body></html>
'''


def render_all_topics(records, root):
    root = Path(root)
    outputs = {root / "topics" / "index.html": render_topics_index(records)}
    outputs.update({
        root / "topics" / key / "index.html": render_topic_page(key, records)
        for key in TOPICS
    })
    return outputs
