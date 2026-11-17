'use strict';

// Runs only from the default branch via an issues.opened event. NO PUBLICATION.
module.exports = async function recordReview({github, context}) {
  const {owner, repo} = context.repo;
  const issue = context.payload.issue;
  if (!issue || issue.user?.login !== owner) return;
  const text = issue.body || '';
  const match = text.match(/^<!-- HPII_AUTO_REVIEW_V1 -->\s*([\s\S]*?)\s*<!-- \/HPII_AUTO_REVIEW_V1 -->\s*(?:Проверка решения выполняется GitHub Actions\. Ничего не публикуется\.)?\s*$/);
  if (!match || match[1].length > 6000) throw Error('Invalid review request');
  const request = JSON.parse(match[1]);
  const expected = ['action','article_id','note','revision','schema_version','updated_at'].sort();
  if (!request || Array.isArray(request) || JSON.stringify(Object.keys(request).sort()) !== JSON.stringify(expected)) throw Error('Unexpected request structure');
  if (request.schema_version !== 1 ||
      !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(request.article_id) ||
      request.article_id.length > 72 ||
      !Number.isSafeInteger(request.revision) || request.revision < 1 ||
      !['approve_text','revise','reject'].includes(request.action) ||
      typeof request.note !== 'string' || request.note.length > 4000 ||
      typeof request.updated_at !== 'string' ||
      (request.action !== 'approve_text' && !request.note.trim())) throw Error('Invalid request fields');

  const branch = 'editorial-intake';
  const draftPath = 'editorial_inbox/auto_drafts/' + request.article_id + '.json';
  const response = await github.rest.repos.getContent({owner,repo,path:draftPath,ref:branch});
  const file = response.data;
  if (Array.isArray(file) || file.type !== 'file') throw Error('Draft missing');
  const draft = JSON.parse(Buffer.from(file.content,'base64').toString('utf8'));
  if (draft.article_id !== request.article_id ||
      draft.revision !== request.revision ||
      draft.updated_at !== request.updated_at ||
      draft.status !== 'ready_for_review') throw Error('Draft revision changed: refresh admin panel');

  const decisionPath = 'editorial_inbox/auto_decisions/' + request.article_id + '-r' + request.revision + '.json';
  // A decision is immutable: any duplicate or conflict must fail safely.
  try {
    await github.rest.repos.getContent({owner,repo,path:decisionPath,ref:branch});
    throw Error('A decision for this revision already exists');
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  const status = request.action === 'revise' ? 'feedback_pending_revision' :
                 request.action === 'reject' ? 'rejected' : 'text_approved_cover_pending';
  const decision = {
    schema_version:1, article_id:request.article_id, revision:request.revision,
    updated_at:request.updated_at, action:request.action, note:request.note,
    issue_number:issue.number, decided_by:issue.user.login,
    decided_at:issue.created_at, draft_blob_sha:file.sha, status
  };
  const content = Buffer.from(JSON.stringify(decision,null,2)+'\n').toString('base64');
  await github.rest.repos.createOrUpdateFileContents({
    owner,repo,path:decisionPath,branch,content,
    message:'review(auto-editor): record '+request.article_id+' r'+request.revision
  });
  await github.rest.issues.createComment({
    owner,repo,issue_number:issue.number,
    body:'✅ Решение сохранено: `'+decisionPath+'` (ветка `editorial-intake`). Статус: `'+status+'`. Публикация не запускалась.'
  });
};
