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
// A later green workflow check is not proof the failed release actually
// reached the site. Compare failed run timestamps to LAST public publication.
// Returning one stable component incident prevents issue spam during retries.
function unrecoveredPublisherFailures(runs, newestPublication, nowMs) {
  const publishedMs = Date.parse(newestPublication || '');
  return runs.filter(r => r.status === 'completed' && r.conclusion === 'failure' &&
    ageMinutes(r.created_at, nowMs) >= 0 && ageMinutes(r.created_at, nowMs) <= 180 &&
    (!Number.isFinite(publishedMs) || publishedMs < Date.parse(r.created_at)));
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

// Pages publishes what readers see; a green scheduler is not a deploy proof.
const PAGES_WORKFLOW = 'pages build and deployment';
function evaluatePagesBuilds(runs, nowMs) {
  const pages = runs.filter(r => r.name === PAGES_WORKFLOW);
  if (!pages.length) return null; // No evidence; don't invent a failure.
  // A new deploy normally cancels an older one. Never alert while the
  // replacement is actively being built or deployed.
  if (pages.some(r => r.status !== 'completed' && ageMinutes(r.created_at, nowMs) < 35))
    return null;
  const latest = latestNonCancelled(pages);
  if (!latest || latest.conclusion === 'success') return null;
  if (ageMinutes(latest.created_at, nowMs) < 10) return null;
  return 'Последняя доставка сайта GitHub Pages не удалась (' + latest.conclusion +
    '): ' + latest.html_url + '. Наличие HTML в main не подтверждает доступность страницы.';
}

const RELEASE_PREFIX = 'site-release:';
const RELEASE_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// A job's regression tests may print fake SCHEDULED_RELEASE lines.
// Only the actual scheduled-publication step identifies the failed article.
function selectedReleaseFromLogs(logs) {
  if (typeof logs !== 'string') return null;
  // Since the pipefail/tee change, Actions prints "Run set -o pipefail"
  // instead of the former "Run python3 scripts/site_publication_queue.py".
  // Choose the actual step AFTER regression tests; never attribute simulated
  // SCHEDULED_RELEASE lines printed by unit tests to a live publication.
  const markers = [
    '##[group]Run python3 scripts/site_publication_queue.py',
    '##[group]Run set -o pipefail'
  ];
  const offset = Math.max(...markers.map(marker => logs.lastIndexOf(marker)));
  if (offset < 0) return null;
  const section = logs.slice(offset);
  if (!section.includes('scripts/site_publication_queue.py')) return null;
  const matches = [...section.matchAll(/SCHEDULED_RELEASE:\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s+urgent=(?:True|False)\b/g)];
  return matches.length === 1 ? matches[0][1] : null;
}
async function selectedFailedArticle(github, run, core) {
  try {
    const result = await github.rest.actions.listJobsForWorkflowRun({
      owner: OWNER, repo: SITE, run_id: run.id, per_page: 50
    });
    for (const job of result.data.jobs || []) {
      if (job.name !== 'release-due-one' || job.conclusion !== 'failure') continue;
      const response = await github.rest.actions.downloadJobLogsForWorkflowRun({
        owner: OWNER, repo: SITE, job_id: job.id
      });
      const raw = response.data;
      const logs = typeof raw === 'string' ? raw
        : Buffer.isBuffer(raw) ? raw.toString('utf8')
        : raw instanceof ArrayBuffer ? Buffer.from(raw).toString('utf8')
        : raw instanceof Uint8Array ? Buffer.from(raw).toString('utf8') : null;
      const id = selectedReleaseFromLogs(logs);
      if (id && RELEASE_ID.test(id)) return id;
    }
  } catch (error) {
    core.warning('Cannot inspect failed release job logs: ' + String(error.message).slice(0,160));
  }
  return null;
}
async function verifySitePublication(id, queue, publicFetch = fetch) {
  if (!RELEASE_ID.test(id)) return {ok:false, why:'invalid article ID'};
  if (!queue || queue.check_error || !Array.isArray(queue.published_site_first))
    return {ok:false, why:'verified queue snapshot unavailable'};
  const record = queue.published_site_first.find(r => r.id === id);
  if (!record || !Number.isFinite(Date.parse(record.published_at_utc || '')))
    return {ok:false, why:'article missing from main news.json or its HTML is not committed'};
  const url = 'https://iipike.ru/articles/' + id + '/';
  try {
    const response = await publicFetch(url, {
      method:'GET', signal:AbortSignal.timeout(12000),
      headers:{'User-Agent':'HPII-Watchdog/1.2'}
    });
    if (response.status !== 200)
      return {ok:false, why:'public page returned HTTP ' + response.status};
    const html = await response.text();
    if (!html.includes('<link rel="canonical" href="' + url + '"') ||
        !html.includes('property="article:published_time"'))
      return {ok:false, why:'public page has no matching canonical article metadata'};
    return {ok:true, url, publishedAt:record.published_at_utc};
  } catch (error) {
    return {ok:false, why:'public page check unavailable: ' + String(error.message).slice(0,140)};
  }
}


async function canAutoCloseIncident(key, findings, checked, releaseProof) {
  if (findings.has(key)) return false;
  if (key.startsWith(RELEASE_PREFIX)) {
    const id = key.slice(RELEASE_PREFIX.length);
    if (!RELEASE_ID.test(id)) return false;
    return (await releaseProof(id)).ok === true;
  }
  // Old generic incidents lack article identity: only a human may close them.
  if (key === 'site-scheduler' || key === 'site-queue' || key === 'site-public')
    return false;
  return checked.has(key);
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
  let queueHealth = null;
  const failedReleases = [];
  let failedPublisherRuns = [];
  const put = (key, message) => { if (!findings.has(key)) findings.set(key, message); };
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
  // A healthy later cron proves the scheduler ran, not that a failed article shipped.
  // Remember the exact failed release ID from the real publication step logs.
  try {
    const r = await runs(SITE, 'site-first-scheduled-release.yml');
    checked.add('site-scheduler-heartbeat');
    const problem = evaluateRun('очереди iipike.ru', r, 85, now,
      'https://github.com/' + OWNER + '/' + SITE + '/actions/workflows/site-first-scheduled-release.yml');
    const latest = latestNonCancelled(r);
    const failures = r.filter(x => x.status === 'completed' && x.conclusion === 'failure' &&
      ageMinutes(x.created_at, now) >= 0 && ageMinutes(x.created_at, now) <= 24 * 60).slice(0, 6);
    failedPublisherRuns = failures;
    let latestTarget = null;
    for (const failed of failures) {
      const id = await selectedFailedArticle(github, failed, core);
      if (!id) continue;
      failedReleases.push({id, run:failed});
      if (failed.id === latest?.id) latestTarget = id;
    }
    if (problem) {
      if (latest?.conclusion === 'failure') {
        if (!latestTarget) put('site-scheduler', problem +
          '. Идентификатор не установлен; только ручное закрытие после проверки.');
      } else {
        put('site-scheduler-heartbeat', problem);
      }
    }
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
  // Monitor the actual GitHub Pages workflow independently of the scheduler.
  // A completed failed/abandoned deploy must not be hidden by news.json.
  try {
    const pageRuns = await github.rest.actions.listWorkflowRunsForRepo({
      owner: OWNER, repo: SITE, per_page: 100
    });
    checked.add('site-pages');
    const problem = evaluatePagesBuilds(pageRuns.data.workflow_runs || [], now);
    if (problem) put('site-pages', problem);
  } catch (error) {
    notes.push('Не удалось проверить GitHub Pages: ' + String(error.message).slice(0,160));
  }
  // Read queue via local git, not repeated GitHub API calls. Inspection failures are NOT a publication outage.
  try {
    const fs = require('node:fs');
    const q = JSON.parse(fs.readFileSync('/tmp/hpii-queue-health.json', 'utf8'));
    queueHealth = q;
    if (q.check_error) {
      notes.push('Состояние очереди не подтверждено: ' + String(q.check_error).slice(0,180));
    } else {
      checked.add('site-queue');
      // Per-article incidents cannot disappear merely because the next cron
      // succeeds or the story leaves the eligible list due to a validation error.
      const queueUrl = 'https://github.com/' + OWNER + '/' + SITE +
        '/blob/editorial-intake/editorial_inbox/QUEUE_STATUS.md';
      for (const x of (Array.isArray(q.overdue) ? q.overdue : []).slice(0,10)) {
        if (RELEASE_ID.test(x.id))
          put(RELEASE_PREFIX + x.id, 'Статья просрочена (+' + x.minutes +
            ' разрешённых минут): ' + x.id + '. Очередь: ' + queueUrl);
      }
      for (const id of (Array.isArray(q.blocked_unverified_dzen_ids) ?
        q.blocked_unverified_dzen_ids : []).slice(0,10)) {
        if (RELEASE_ID.test(id))
          put(RELEASE_PREFIX + id, 'Статья заблокирована непроверенной ссылкой Дзена: ' +
            id + '. Очередь: ' + queueUrl);
      }
      for (const id of (Array.isArray(q.blocked_invalid_markdown_ids) ?
        q.blocked_invalid_markdown_ids : []).slice(0,10)) {
        if (RELEASE_ID.test(id))
          put(RELEASE_PREFIX + id, 'Статья заблокирована некорректным Markdown: ' +
            id + '. Очередь: ' + queueUrl);
      }
      if (q.newest_id && ageMinutes(q.newest_published_at_utc, now) > 45) {
        const url = 'https://iipike.ru/articles/' + encodeURIComponent(q.newest_id) + '/';
        try {
          const response = await fetch(url, {method:'GET', signal:AbortSignal.timeout(12000),
            headers:{'User-Agent':'HPII-Watchdog/1.1'}});
          checked.add('site-public');
          if (response.status === 404 || response.status >= 500) {
            put(RELEASE_PREFIX + q.newest_id, 'Страница из main не открывается: HTTP ' + response.status + ', ' + url);
          }
        } catch (error) {
          notes.push('Сайт извне проверить не удалось: ' + String(error.message).slice(0,160));
        }
      }
    }
  } catch (error) {
    notes.push('Диагностика очереди не завершена: ' + String(error.message).slice(0,160));
  }
  // Confirm individual deliveries only with *both* the main branch catalog
  // and the canonical public page. A green Actions run is never proof.
  const proofCache = new Map();
  async function releaseProof(id) {
    if (!proofCache.has(id))
      proofCache.set(id, await verifySitePublication(id, queueHealth));
    return proofCache.get(id);
  }
  // Independent failure alarm: if the next run is green but no later site
  // article shipped, the earlier failed publication is NOT fixed.
  const unresolvedRuns = unrecoveredPublisherFailures(
    failedPublisherRuns, queueHealth?.newest_published_at_utc, now);
  if (unresolvedRuns.length) {
    const latest = unresolvedRuns[0];
    put('site-publisher-blocked', 'Выпуск сайта падал ' + unresolvedRuns.length +
      ' раз за последние 3 часа; после последней ошибки новая публикация ' +
      'на сайте не подтверждена. Последняя ошибка: ' + latest.html_url +
      '. Проверьте release-due-one, даже если следующий Action зелёный.');
  }
  for (const entry of failedReleases) {
    const proof = await releaseProof(entry.id);
    if (proof.ok) continue;
    put(RELEASE_PREFIX + entry.id, 'Выпуск ' + entry.id +
      ' завершился ошибкой: ' + entry.run.html_url +
      '. Публикация не подтверждена (' + proof.why + ').');
  }
  for (const key of [...findings.keys()]) {
    if (!key.startsWith(RELEASE_PREFIX)) continue;
    const proof = await releaseProof(key.slice(RELEASE_PREFIX.length));
    if (proof.ok) findings.delete(key);
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
    if (key === 'site-publisher-blocked') {
      const newest = Date.parse(queueHealth?.newest_published_at_utc || '');
      const opened = Date.parse(incident.created_at || '');
      const proof = queueHealth?.newest_id
        ? await releaseProof(queueHealth.newest_id) : {ok:false};
      if (!findings.has(key) && proof.ok && newest > opened) {
        await github.rest.issues.createComment({owner:OWNER, repo:SITE,
          issue_number:incident.number,
          body:'После обнаруженного сбоя подтверждена новая site-first публикация: ' +
            proof.url + '. Прогресс очереди восстановлен; инцидент закрыт.'});
        await github.rest.issues.update({owner:OWNER, repo:SITE,
          issue_number:incident.number, state:'closed'});
      }
      continue;
    }
    if (key.startsWith(RELEASE_PREFIX)) {
      const id = key.slice(RELEASE_PREFIX.length);
      if (!(await canAutoCloseIncident(key, findings, checked, releaseProof))) {
        if (!findings.has(key)) {
          const proof = await releaseProof(id);
          notes.push('Инцидент ' + key + ' остаётся открытым: ' + proof.why);
        }
        continue;
      }
      const proof = await releaseProof(id);
      await github.rest.issues.createComment({owner:OWNER, repo:SITE, issue_number:incident.number,
        body:'Выпуск статьи **' + id + '** подтверждён: запись с временем публикации ' +
          proof.publishedAt + ' есть в news.json, HTML существует в main, ' +
          'и публичный URL отвечает HTTP 200 с корректным canonical и метаданными статьи: ' +
          proof.url + '. Инцидент закрыт автоматически по подтверждённой доставке.'});
      await github.rest.issues.update({owner:OWNER, repo:SITE,
        issue_number:incident.number, state:'closed'});
      continue;
    }
    // Legacy generic site incidents lack an article ID. Never mark delivery
    // complete from scheduler health alone; owner reviews them manually.
    if (await canAutoCloseIncident(key, findings, checked, releaseProof)) {
      await github.rest.issues.createComment({owner:OWNER, repo:SITE, issue_number:incident.number,
        body:'Проверяемый компонент снова работает. Это подтверждение здоровья ' +
          'компонента, не доказательство доставки отдельной публикации.'});
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
module.exports = {main, ageMinutes, dueAgeMinutes, latestNonCancelled,
  unrecoveredPublisherFailures, evaluateRun,
  evaluatePagesBuilds, selectedReleaseFromLogs, verifySitePublication, canAutoCloseIncident};
