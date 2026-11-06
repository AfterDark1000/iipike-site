'use strict';

const OWNER = 'AfterDark1000';
const SITE = 'iipike-site';
const CROSS = 'dzen-telegram-crosspost';
const PREFIX = '[HPII WATCHDOG] ';
const HOUR = 60 * 60 * 1000;

function ageMinutes(iso, nowMs) {
  const time = Date.parse(iso || '');
  return Number.isFinite(time) ? (nowMs - time) / 60000 : Infinity;
}
function dueAgeMinutes({readyAt, notBefore, lastPublication}, nowMs) {
  const earliest = Math.max(
    Date.parse(readyAt),
    notBefore ? Date.parse(notBefore) : 0,
    lastPublication ? Date.parse(lastPublication) + HOUR : 0,
  );
  return Number.isFinite(earliest) ? (nowMs - earliest) / 60000 : -Infinity;
}
function latestNonCancelled(runs) {
  return runs.find(r => r.status === 'completed' && r.conclusion !== 'cancelled');
}
function evaluateRun(label, runs, maxAge, nowMs, url) {
  const recentInProgress = runs.some(r => r.status === 'in_progress' && ageMinutes(r.created_at, nowMs) < 30);
  const latest = latestNonCancelled(runs);
  if (recentInProgress) return null;
  if (!latest) return 'Не найден завершённый запуск ' + label + ': ' + url;
  const age = ageMinutes(latest.created_at, nowMs);
  if (age > maxAge) {
    return 'Последний запуск ' + label + ' был ' + Math.round(age) +
      ' мин назад (норма до ' + maxAge + ' мин): ' + latest.html_url;
  }
  if (latest.conclusion !== 'success') {
    return 'Последний запуск ' + label + ': ' + latest.conclusion + ' — ' + latest.html_url;
  }
  return null;
}
function decodeFile(data) {
  if (Array.isArray(data) || data.type !== 'file') throw Error('Expected GitHub file');
  return Buffer.from((data.content || '').replace(/\s/g, ''), 'base64').toString('utf8');
}
async function main({github, context, core}) {
  const now = Date.now();
  const findings = new Map();
  const notes = [];
  const put = (key, message) => findings.set(key, message);
  async function content(path, ref) {
    const r = await github.rest.repos.getContent({owner: OWNER, repo: SITE, path, ref});
    return r.data;
  }
  async function runs(repo, workflowId) {
    const r = await github.rest.actions.listWorkflowRuns({
      owner: OWNER, repo, workflow_id: workflowId, per_page: 20
    });
    return r.data.workflow_runs || [];
  }
  // A green workflow with "New articles: 0" is healthy, not a missing publication.
  try {
    const r = await runs(SITE, 'site-first-scheduled-release.yml');
    const problem = evaluateRun('очереди iipike.ru', r, 85, now,
      'https://github.com/' + OWNER + '/' + SITE + '/actions/workflows/site-first-scheduled-release.yml');
    if (problem) put('site-scheduler', problem);
  } catch (error) {
    put('site-scheduler', 'Не удалось проверить расписание сайта: ' + error.message);
  }
  try {
    const r = await runs(CROSS, 'crosspost.yml');
    const problem = evaluateRun('Дзен → Telegram', r, 155, now,
      'https://github.com/' + OWNER + '/' + CROSS + '/actions/workflows/crosspost.yml');
    if (problem) put('crosspost', problem);
  } catch (error) {
    put('crosspost', 'Не удалось проверить запуски кросспостинга: ' + error.message +
      '. Это не доказательство сбоя Telegram.');
  }
  // Only fully approved stories with covers count. Respect both future slots and 60-minute spacing.
  try {
    const [stories, covers, live, mainStories] = await Promise.all([
      content('editorial_inbox/stories', 'editorial-intake'),
      content('editorial_inbox/covers', 'editorial-intake'),
      content('news.json', 'main'),
      content('editorial_inbox/stories', 'main')
    ]);
    if (![stories, covers, mainStories].every(Array.isArray)) throw Error('Unexpected directory listing');
    const items = JSON.parse(decodeFile(live));
    if (!Array.isArray(items)) throw Error('Invalid news.json');
    const publishedIds = new Set(items.map(x => x.id));
    const mainIds = new Set(mainStories.map(x => x.name.replace(/\.json$/, '')));
    const timestamps = items.filter(x => mainIds.has(x.id) && x.published_at_utc)
      .map(x => Date.parse(x.published_at_utc)).filter(Number.isFinite);
    const last = timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null;
    const coversById = new Map();
    for (const f of covers) {
      const m = /^([a-z0-9-]+)\.(webp|png|jpe?g)$/.exec(f.name);
      if (m) coversById.set(m[1], f.name);
    }
    const overdue = [];
    for (const f of stories) {
      const m = /^([a-z0-9-]+)\.json$/.exec(f.name);
      if (!m || !coversById.has(m[1]) || publishedIds.has(m[1])) continue;
      const id = m[1];
      const raw = JSON.parse(decodeFile(await content('editorial_inbox/stories/' + f.name, 'editorial-intake')));
      if (raw.id !== id || raw.status !== 'editor_approved' || raw.approved_by !== 'human_editor') continue;
      const coverPath = 'editorial_inbox/covers/' + coversById.get(id);
      const [storyCommits, coverCommits] = await Promise.all([
        github.rest.repos.listCommits({owner:OWNER, repo:SITE,
          path:'editorial_inbox/stories/' + f.name, sha:'editorial-intake', per_page:1}),
        github.rest.repos.listCommits({owner:OWNER, repo:SITE,
          path:coverPath, sha:'editorial-intake', per_page:1})
      ]);
      const a = storyCommits.data[0]?.commit?.committer?.date;
      const b = coverCommits.data[0]?.commit?.committer?.date;
      const readyAt = new Date(Math.max(Date.parse(a), Date.parse(b))).toISOString();
      const slot = raw.site_publish_at || null;
      if (slot && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:00$/.test(slot)) {
        overdue.push(id + ' (ошибка времени site_publish_at)');
        continue;
      }
      const age = dueAgeMinutes({readyAt, notBefore:slot, lastPublication:last}, now);
      if (age >= 100) overdue.push(id + ' (ожидание ' + Math.round(age) + ' мин сверх допустимого слота)');
    }
    if (overdue.length) {
      put('site-queue', 'Готовые статьи не опубликованы дольше 100 минут после допустимого времени: ' +
        overdue.slice(0,5).join('; ') +
        '. Очередь: https://github.com/' + OWNER + '/' + SITE +
        '/blob/editorial-intake/editorial_inbox/QUEUE_STATUS.md');
    }
    // Check the latest released story's actual public URL, not only Git commits.
    const newest = items.filter(x => mainIds.has(x.id) && x.published_at_utc)
      .sort((a,b) => Date.parse(b.published_at_utc) - Date.parse(a.published_at_utc))[0];
    if (newest && ageMinutes(newest.published_at_utc, now) > 45) {
      const url = 'https://iipike.ru/articles/' + encodeURIComponent(newest.id) + '/';
      try {
        const response = await fetch(url, {method:'GET', signal:AbortSignal.timeout(12000),
          headers:{'User-Agent':'HPII-Watchdog/1.0'}});
        if (response.status === 404 || response.status >= 500) {
          put('site-public', 'После публикации в main статья не открывается: HTTP ' + response.status + ', ' + url);
        }
      } catch (error) {
        notes.push('Публичная проверка сайта временно недоступна: ' + error.message);
      }
    }
  } catch (error) {
    put('site-queue', 'Не удалось выполнить проверку очереди iipike.ru: ' + error.message);
  }
  // MAX has no verified read-only history source. Never infer delivery from green Telegram runs.
  notes.push('MAX: доставки не проверены автоматически; нужен отдельный источник подтверждений репостера.');
  // One open issue per distinct component. New findings open issues once, recovery closes them.
  const existing = await github.paginate(github.rest.issues.listForRepo,
    {owner:OWNER, repo:SITE, state:'open', per_page:100});
  const ours = existing.filter(x => !x.pull_request && x.title.startsWith(PREFIX));
  for (const [key, description] of findings) {
    const title = PREFIX + key;
    if (ours.some(i => i.title === title)) continue;
    await github.rest.issues.create({owner:OWNER, repo:SITE, title,
      body:'Автоматический сторож ХПИИ обнаружил отклонение.\n\n' + description +
        '\n\n@AfterDark1000 — проверьте проблему вручную. Сторож не запускает публикации и не изменяет секреты.' +
        '\n\nОтчётный запуск: https://github.com/' + OWNER + '/' + SITE + '/actions/runs/' + context.runId});
    core.warning('OPEN INCIDENT: ' + key + ': ' + description);
  }
  for (const incident of ours) {
    const key = incident.title.slice(PREFIX.length);
    if (!findings.has(key)) {
      await github.rest.issues.createComment({owner:OWNER, repo:SITE, issue_number:incident.number,
        body:'Сторож больше не обнаруживает прежнее отклонение. Закрыто автоматически; это не подтверждает доставку в MAX.'});
      await github.rest.issues.update({owner:OWNER, repo:SITE,
        issue_number:incident.number, state:'closed'});
    }
  }
  const summary = ['## ХПИИ — сторож', 'Время UTC: ' + new Date(now).toISOString(),
    'Активные отклонения: ' + findings.size,
    ...[...findings].map(([key, detail]) => '- **' + key + ':** ' + detail),
    ...notes.map(x => '- ' + x)];
  await core.summary.addRaw(summary.join('\n') + '\n').write();
}
module.exports = {main, ageMinutes, dueAgeMinutes, latestNonCancelled, evaluateRun};
