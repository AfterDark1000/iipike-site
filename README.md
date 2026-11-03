# Хроники Пикирующего ИИ — сайт

Основной адрес: https://iipike.ru/ (GitHub Pages, репозиторий `AfterDark1000/iipike-site`).

Это статический сайт ХПИИ: главная страница со ссылками на опубликованные новости в Дзене, редакционный реестр, лаборатория помеченных **НЕ ОПУБЛИКОВАНО** черновиков и пилотная авторская статья в `articles/google-search-ai-links/`.

**Поисковая индексация:** `sitemap.xml` содержит только реально опубликованные HTML-материалы сайта из `news.json` и главную страницу. Черновики и служебный реестр имеют `noindex, nofollow` и в карту сайта не включаются. RSS `feed.xml` ведёт на `iipike.ru`; GUID существующего пилотного материала оставлен неизменным, чтобы не создавать дубль у подписчиков RSS.

После добавления **редактором проверенной и опубликованной** новой HTML-статьи: добавьте её в `news.json`, укажите `<link rel="canonical" href="https://iipike.ru/articles/<slug>/">` в HTML, затем выполните:

```sh
python3 scripts/build_sitemap.py
python3 -m unittest discover -s tests -p 'test_search_indexing.py' -v
```

Автоматические черновики нельзя записывать в `news.json` или индексировать без редакционной проверки. График Дзен → соцсети не изменён; полноценного автоматического выпуска утверждённых новостей на сайт пока нет.

Для подключения Яндекс Вебмастера добавьте `https://iipike.ru/`, выберите подтверждение HTML-файлом или метатегом и добавьте выданный сервисом **конкретный** файл/код в этот репозиторий. После подтверждения отправьте `https://iipike.ru/sitemap.xml`. Никаких кодов подтверждения заранее не придумываем.

Первоисточник пилотной статьи: https://blog.google/products-and-platforms/products/search/updates-ai-mode-overviews-explore-web/

## Публикация утверждённой статьи

1. Редактор проверяет факты, первоисточники, текст и обложку, затем кладёт JSON по образцу `content/approved/README.md` в `content/approved/<slug>.json`. Сырые автоподборки из `drafts/` публиковать запрещено.
2. Проверка **без изменения файлов**: `python3 scripts/publish_approved_article.py <slug>`.
3. Явная генерация после утверждения: `python3 scripts/publish_approved_article.py <slug> --publish`.
4. Просмотреть diff: HTML в `articles/<slug>/index.html`, `articles/index.html`, `news.json`, `feed.xml`, `sitemap.xml` и отправить отдельный PR на проверку. Сайт изменится только после слияния в `main` и успешного GitHub Pages деплоя.
5. Проверить: `python3 scripts/build_sitemap.py --check`, `python3 -m unittest discover -s tests -p 'test_search_indexing.py' -v` и `python3 -m unittest discover -s tests -p 'test_approved_publisher.py' -v`.

Команда не трогает кросспостинг, не вызывает внешних API, не публикует в Дзен и отказывает в повторной записи поверх уже опубликованного материала. Авторизация утверждения обеспечивается редакционными правами на GitHub, а не полем JSON как криптографической подписью.
