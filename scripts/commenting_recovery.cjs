const MAX_AGE_MS = 90 * 60_000;

async function checkRecovery({ github, context, core }, now = Date.now()) {
  let file;
  try {
    ({ data: file } = await github.rest.repos.getContent({ ...context.repo,
      path: 'commenting/queue.json', ref: 'commenting-data' }));
  } catch (error) {
    if (error.status !== 404) throw error;
    core.warning('Очередь commenting-data отсутствует. Запускаем обычный сборщик.');
    core.setOutput('due', true);
    return;
  }
  if (file.encoding !== 'base64' || typeof file.content !== 'string') throw new Error('Invalid commenting queue file');
  const queue = JSON.parse(Buffer.from(file.content, 'base64').toString('utf8'));
  const updatedAt = Date.parse(queue.updated_at);
  if (queue.schema_version !== 1 || !Number.isFinite(updatedAt) || updatedAt > now) {
    throw new Error('Invalid commenting queue timestamp');
  }
  const age = now - updatedAt;
  if (age > MAX_AGE_MS) {
    core.warning(`Очередь комментинга не обновлялась ${Math.floor(age / 60_000)} мин. Запускаем обычный сборщик.`);
  }
  core.setOutput('due', age > MAX_AGE_MS);
}

module.exports = { checkRecovery };
