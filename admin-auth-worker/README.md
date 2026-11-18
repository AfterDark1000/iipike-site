# ХПИИ — единый вход через GitHub (подготовка; НЕ ВКЛЮЧЕНО)

Цель: один вход в `iipike.ru/admin/` через GitHub, затем безопасное подтверждение решений без перехода в GitHub Issues. Публичный сайт и DNS SpaceWeb остаются без изменений. Рабочие файлы выпуска не затрагиваются.

## Что подготовлено

- `src/index.mjs`: отдельный Cloudflare Worker с OAuth 2.0 Authorization Code + PKCE, защитой `state`, проверкой **GitHub user ID 284211090 / AfterDark1000**, 8-часовой подписанной сессией, ограниченным CORS и endpoint `POST /api/review`.
- `admin/auth/hpii-auth-client.js`: клиент всплывающего входа с `postMessage` по точному origin и `sessionStorage` (одна сессия внутри текущей вкладки; не хранит GitHub OAuth токен).
- GitHub-права для решения: отдельный fine-grained PAT **только для репозитория `AfterDark1000/iipike-site`**, с `Contents: Read and write`; хранится **только** в Cloudflare Worker secret. Клиенту не выдаётся.
- Строгая проверка `article_id/revision/updated_at/status`, запрет второго решения для одной версии, commit в `editorial-intake/editorial_inbox/auto_decisions/`. Нет endpoint публикации, перехода материала в `editor_approved` или изменения очередей.
- `.github/workflows/hpii-admin-auth-tests.yml`: офлайн-тесты в PR, **без развёртывания**.

## Что отсутствует до включения

**Это код-кандидат, а не действующая авторизация.** Нет созданного/подключённого OAuth App, адреса работающего Worker, сохранённых серверных секретов и подключения клиента ко всем трём HTML-страницам. Публичная админка сейчас **без изменений**. Не объявлять её защищённой.

## Однократные действия владельца (делаются только после просмотра PR)

1. В Cloudflare создать аккаунт (если его нет), Workers & Pages → Worker на отдельном `*.workers.dev`. **Не переносить DNS и не менять nameservers** в SpaceWeb.
2. Записать фактический адрес Worker, например `https://hpii-admin-gateway.<ваш-subdomain>.workers.dev`.
3. В GitHub → Settings → Developer settings → OAuth Apps создать GitHub OAuth App с Homepage `https://iipike.ru/admin/` и **Authorization callback URL** `https://<адрес-worker>/auth/callback`. У приложения должен быть фиксированный callback URL; не использовать примерные адреса.
4. Развернуть `admin-auth-worker/` (Wrangler либо Cloudflare Git integration) **только после проверки кода**. В secrets Worker задать:
   - `GITHUB_CLIENT_ID` — OAuth App Client ID (не секрет, но хранить с настройками Worker);
   - `GITHUB_CLIENT_SECRET` — OAuth App Client Secret (никогда не присылать в чат или commit);
   - `SESSION_SIGNING_KEY` — случайная строка минимум 32 символа, хранится только в Worker;
   - `GITHUB_REPO_TOKEN` — fine-grained GitHub token на один репозиторий, `Contents: Read and write`, с минимальным сроком действия; не использовать личный широкий PAT;
   - `BACKEND_ORIGIN` — точный HTTPS origin Worker без / и path.
   - `ADMIN_ORIGIN=https://iipike.ru`, `ALLOWED_GITHUB_USER_ID=284211090` задаются в `wrangler.toml`.
5. На отдельном тестовом интерфейсе проверить popup login, запрет чужого аккаунта, устаревшее решение, дубликат, чтение нового JSON и невозможность публикации.
6. После успешных тестов подключить `HpiiAdminAuth` к `/admin/`, `/admin/auto-editor/` и `/admin/commenting/` одной управляемой интеграцией с откатом. Форму входа показывать при входе в админку; действия после авторизации вызывать через API. Сначала оставить fallback GitHub Issue, затем убрать.
7. Если необходимо **скрывать статьи/черновики/логи от посторонних**, перенести эти данные из публичного GitHub. Вход в JavaScript на публичном GitHub Pages не закрывает прямой URL файлов.

## Почему выбран отдельный Worker

GitHub Pages — статический хостинг. Нельзя хранить `GITHUB_CLIENT_SECRET`, signing key и GitHub write token в его HTML/JavaScript. GitHub OAuth-код обменивается на сервере Worker, который проверяет стабильный числовой ID владельца и выдаёт собственный короткоживущий session ticket. API не принимает неподписанные запросы.

При адресе `workers.dev` аутентификация остаётся **функциональной**, а не сетевым запретом на доступ к публичным HTML. Если потребуется полностью скрыть `/admin/*` и исходники (включая альтернативный GitHub Pages домен), понадобится менять архитектуру размещения административных данных и отдачи страниц; нельзя обещать это только клиентским входом.

## Проверка

Локально: `node --check admin-auth-worker/src/index.mjs` и `node --test admin-auth-worker/tests/*.test.mjs` (Node 22). Тесты подменяют внешние GitHub-запросы и не публикуют новости.

Связанные задачи: [GitHub #163](https://github.com/AfterDark1000/iipike-site/issues/163), [настройка решений](../docs/AUTO_EDITOR_REVIEW_PANEL.md).

**Не внедрять без реального backend deployment и позитивного теста. Не вставлять фиктивную ссылку Worker.**

## Обложки v2 после редакторского возврата
При обновлении исходного `admin-auth-worker/src/index.mjs` redeploy действующего Worker обязателен: GitHub PR не разворачивает его автоматически. Текущая версия API принимает `cover_version=2..5` **только при подтверждённом `cover_revision_requested` предыдущей версии**. Каждый кандидат имеет собственный WebP SHA, метаданные и решение. Проверить на тестовом/боевом окружении до заявления, что админка принимает v2. Никогда не вводить секреты в GitHub и не открывать публикацию этим обновлением.
