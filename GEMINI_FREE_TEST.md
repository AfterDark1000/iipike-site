# Бесплатный тест Gemini API для ХПИИ

Это отдельный эксперимент в репозитории `iipike-site`. Он **не запускается по расписанию** и **не публикует** ничего на сайте, в Дзене или соцсетях. Обычный кросспостинг не изменён.

## Один раз настроить ключ

1. Открой https://aistudio.google.com/apikey — Google AI Studio → API keys.
2. Выбери или создай проект **Free tier**, без подключения Billing / Set up billing. Проверь колонку Billing Tier.
3. Создай API key. Не вставляй его в переписку, GitHub issue или файлы репозитория.
4. Открой https://github.com/AfterDark1000/iipike-site/settings/secrets/actions → New repository secret.
5. Name: `GEMINI_API_KEY`; Secret: созданный ключ; Save.
6. Открой https://github.com/AfterDark1000/iipike-site/actions/workflows/gemini-free-test.yml → Run workflow → Run workflow.

## Что произойдёт

- GitHub выполнит 6 офлайн-тестов и **один** запрос к модели `gemini-2.5-flash-lite`.
- Использует публичную тестовую новость из `news.json`; ищет не новую новость, а проверяет редакционный формат.
- Возвращает текст и предупреждения о непроверенных фактах в `gemini_probe.json` (Actions → Run → Artifacts).
- Не передаёт ключ в URL, не пишет его в лог, не вызывает платную модель и не переключается на другой тариф при исчерпании лимита.
- Если аккаунт Google привязан к платному проекту, код не умеет проверить это изнутри: убедись, что проект Free tier до запуска.
- Если регион, ключ или квота недоступны, задание завершится ошибкой с кодом HTTP; никаких резервных платных вызовов.

## Следующий этап

После успешного теста подключения Gemini: пробное получение новостей из нескольких независимых RSS с датами/первоисточниками, затем Cloudflare Workers AI для тестовых обложек. Публикация остаётся выключенной до редакционной проверки.

Документация: https://ai.google.dev/gemini-api/docs/pricing ; https://ai.google.dev/gemini-api/docs/api-key
