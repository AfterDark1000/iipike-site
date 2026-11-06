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
  const checked = new Set();
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
    checked.add('site-scheduler');
    const problem = evaluateRun('очереди iipike.ru', r, 85, now,
      'https://github.com/' + OWNER + '/' + SITE + '/actions/workflows/site-first-scheduled-release.yml');
    if (problem) put('site-scheduler', problem);
  } catch (error) {
    notes.push('Проверка расписания сайта недоступна: ' + String(error.message).slice(0,160));
  }
  try {
    const r = await runs(CROSS, 'crosspost.yml');
    checked.add('crosspost');
    const problem = evaluateRun('Дзен → Telegram', r, 155, now,
      'https://github.com/' + OWNER + '/' + CROSS + '/actions/workflows/crosspost.yml');
    if (problem) put('crosspost', problem);
  } catch (error) {
    notes.push('Проверка запусков Дзен → Telegram недоступна: ' + String(error.message).slice(0,160) +
      '. Это не доказательство сбоя Telegram.');
  }
  // Read queue via local git, not repeated GitHub API calls. Inspection failures are NOT a publication outage.
  try {
    const fs = require('node:fs');
    const q = JSON.parse(fs.readFileSync('/tmp/hpii-queue-health.json', 'utf8'));
    if (q.check_error) {
      notes.push('Состояние очереди не подтверждено: ' + String(q.check_error).slice(0,180));
    } else {
      checked.add('site-queue');
      const problems = [];
      if (Array.isArray(q.overdue) && q.overdue.length) {
        problems.push('Просроченные публикации: ' + q.overdue.slice(0,5)
          .map(x => x.id + ' (+' + x.minutes + ' мин)').join('; '));
      }
      if (Array.isArray(q.blocked_unverified_dzen_ids) && q.blocked_unverified_dzen_ids.length) {
        problems.push('Записи заблокированы неверной ссылкой Дзена: ' +
          q.blocked_unverified_dzen_ids.slice(0,5).join(', '));
      }
      if (problems.length) {
        put('site-queue', problems.join('. ') + '. Очередь: https://github.com/' +
          OWNER + '/' + SITE + '/blob/editorial-intake/editorial_inbox/QUEUE_STATUS.md');
      }
      if (q.newest_id && ageMinutes(q.newest_published_at_utc, now) > 45) {
        const url = 'https://iipike.ru/articles/' + encodeURIComponent(q.newest_id) + '/';
        try {
          const response = await fetch(url, {method:'GET', signal:AbortSignal.timeout(12000),
            headers:{'User-Agent':'HPII-Watchdog/1.1'}});
          checked.add('site-public');
          if (response.status === 404 || response.status >= 500) {
            put('site-public', 'Страница из main не открывается: HTTP ' + response.status + ', ' + url);
          }
        } catch (error) {
          notes.push('Сайт извне проверить не удалось: ' + String(error.message).slice(0,160));
        }
      }
    }
  } catch (error) {
    notes.push('Диагностика очереди не завершена: ' + String(error.message).slice(0,160));
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
    if (!findings.has(key) && checked.has(key)) {
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
