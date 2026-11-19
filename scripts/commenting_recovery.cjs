const MAX_AGE_MS = 90 * 60_000;
const ATTEMPT_CONTEXT = 'hpii/commenting-recovery-attempt';

async function readQueue(github, repo, ref) {
  const { data } = await github.rest.repos.getContent({ ...repo, path: 'commenting/queue.json', ref });
  if (data.encoding !== 'base64' || typeof data.content !== 'string') throw new Error('Invalid commenting queue file');
  return Buffer.from(data.content, 'base64');
}

// Called inside the shared collector lock, immediately before any generation.
// The status records an attempt for this data commit even if the job later fails.
async function claimRecovery({ github, context, core }, now = Date.now()) {
  const { repo } = context;
  let sha, previous;
  try {
    ({ data: { object: { sha } } } = await github.rest.git.getRef({ ...repo, ref: 'heads/commenting-data' }));
    previous = await readQueue(github, repo, sha);
  } catch (error) {
    if (error.status !== 404) throw error;
    core.warning('Очередь отсутствует. Для первого запуска используйте ручной запуск сборщика на main.');
    return null;
  }
  const queue = JSON.parse(previous.toString('utf8'));
  const updatedAt = Date.parse(queue.updated_at);
  if (queue.schema_version !== 1 || !Number.isFinite(updatedAt) || updatedAt > now) {
    throw new Error('Invalid commenting queue timestamp');
  }
  const age = now - updatedAt;
  if (age <= MAX_AGE_MS) return null;

  const statuses = await github.paginate(github.rest.repos.listCommitStatusesForRef, { ...repo, ref: sha });
  if (statuses.some((status) => status.context === ATTEMPT_CONTEXT)) {
    core.warning('Очередь всё ещё старше 90 минут. Резервная попытка для этого снимка уже зарегистрирована.');
    return null;
  }
  await github.rest.repos.createCommitStatus({ ...repo, sha, context: ATTEMPT_CONTEXT, state: 'success',
    description: 'Automatic attempt recorded. See the run for its outcome.',
    target_url: `${context.serverUrl}/${repo.owner}/${repo.repo}/actions/runs/${context.runId}` });
  core.warning(`Очередь комментинга не обновлялась ${Math.floor(age / 60_000)} мин. Запускаем штатный сборщик.`);
  return previous;
}

module.exports = { claimRecovery, readQueue };
