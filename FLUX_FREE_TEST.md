# Бесплатные обложки ХПИИ: тест Cloudflare FLUX

Этот эксперимент расположен в отдельном `AfterDark1000/iipike-site`. Он **не публикует** изображения на сайте, в Дзен или соцсетях. Он запускается только вручную, сохраняет 3 варианта в приватном артефакте GitHub Actions на 7 дней.

## Cloudflare: что нужно

1. Войди в https://dash.cloudflare.com/ (или создай бесплатную учётную запись).
2. Убедись, что аккаунт использует именно **Workers Free**, без подключения Workers Paid и платёжных данных ради этого эксперимента. Бесплатная квота Workers AI — 10 000 Neurons в день; при исчерпании бесплатного лимита на Free операции перестают выполняться.
3. Открой https://dash.cloudflare.com/?to=/:account/ai/workers-ai → **Use REST API**.
4. Выбери **Create a Workers AI API Token**. Если настраиваешь права вручную, для Workers AI нужны `Read` и `Edit`. Не используй Global API Key.
5. На этой же странице скопируй **Account ID** (это идентификатор аккаунта, не ключ).

## GitHub: сохранить реквизиты только в Secrets

Открой https://github.com/AfterDark1000/iipike-site/settings/secrets/actions → **New repository secret** и создай два секрета:

- `CLOUDFLARE_API_TOKEN` — ключ Cloudflare Workers AI.
- `CLOUDFLARE_ACCOUNT_ID` — Account ID из Cloudflare.

В чат, README, исходники, публичные скриншоты или файлы ключи не отправляй.

## Ровно один тест: 3 иллюстрации

1. Открой https://github.com/AfterDark1000/iipike-site/actions/workflows/flux-free-test.yml
2. **Run workflow** → **Run workflow**.
3. Внутри выполняются 7 офлайн-проверок, затем три REST-запроса к фиксированной модели `@cf/black-forest-labs/flux-2-klein-4b`, каждый 1024x576 (16:9), без повторных попыток и платных резервных моделей.
4. GitHub самостоятельно накладывает кириллический заголовок «ССЫЛКИ НА ВИДУ» и подзаголовок «Google меняет ИИ-поиск» (DejaVu font в GitHub runner).
5. После Success внизу запуска скачай Artifacts → `hpi-flux-three-covers`. Внутри 3 PNG, `comparison.jpg` и `manifest.json`.

Каждый вариант посвящён **одной уже известной тестовой новости**, но в разных стилях: европейский плакат, киноиллюстрация и сюрреализм. Сравниваем рисунок, композицию, разнообразие и читаемость заголовка.

## Ограничения

- Никаких новых статей скрипт не пишет; публичные файлы репозитория не меняет.
- Никаких автоматических повторов. Если Cloudflare вернёт 401/403/429, тест завершится ошибкой и не переключится на платную модель.
- Код не способен проверить текущий тариф аккаунта Cloudflare по двум предоставленным секретам. **Перед запуском проверь Workers Free**; на Workers Paid расход сверх дневной квоты платный.
- Если изображения плохие, их никуда не публикуем; это сравнение, а не приёмка качества.

Официальная документация: https://developers.cloudflare.com/workers-ai/get-started/rest-api/ ; https://developers.cloudflare.com/workers-ai/platform/pricing/ ; https://developers.cloudflare.com/changelog/post/2026-01-15-flux-2-klein-4b-workers-ai/
