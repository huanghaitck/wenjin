const state = {
  snapshot: null, capabilities: null, view: null, thread: null, threadId: '', pageIndex: 0, zoom: 1,
  libraryScan: null, libraryWorks: [], libraryWork: null, libraryWorkId: '',
};
const $ = (id) => document.getElementById(id);

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}

function reviewerPayload() {
  const reviewer = $('reviewer').value.trim();
  const reason = $('reason').value.trim();
  if (!reviewer || !reason) throw new Error('提交前请填写复核人和修正依据。');
  return { reviewer, reason };
}

async function loadSnapshot(selectId = '') {
  [state.snapshot, state.capabilities] = await Promise.all([
    request('/api/snapshot'),
    request('/api/capabilities'),
  ]);
  renderAgentShell();
  state.libraryWorks = state.snapshot.library_works || [];
  renderLibraryShell();
  const select = $('sourceSelect');
  select.replaceChildren();
  if (!state.snapshot.sources.length) {
    select.append(new Option('尚无文献', ''));
    state.view = null;
    render();
    return;
  }
  for (const source of state.snapshot.sources) select.append(new Option(source.title, source.source_id));
  select.value = selectId || select.value || state.snapshot.sources[0].source_id;
  await loadSource(select.value);
}

const actionLabels = {
  register_new: '新作品', new_version: '同一文件的新版本', exact_duplicate: '精确重复位置',
  unchanged: '内容未变化', error: '读取失败',
};
const triageLabels = {
  likely_historical: '较可能是历史材料', uncertain: '需要人工判断', needs_visual_triage: '需要查看原页',
  not_obviously_historical: '暂未发现历史线索', unsupported: '当前不解析', error: '读取失败',
};

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

function renderLibraryShell() {
  const library = state.snapshot?.library;
  $('libraryRoot').textContent = library ? `索引位置：${library.library_root}` : '图书馆尚未初始化';
  const counts = library?.counts || {};
  $('libraryCounts').textContent = `${counts.works || 0} 部作品 · ${counts.library_files || 0} 个文件位置 · ${counts.file_versions || 0} 个精确版本`;
  const skills = $('intakeSkill'); skills.replaceChildren();
  for (const skill of (library?.skills || [])) {
    const option = new Option(`${skill.name} · ${skill.execution}`, skill.name);
    option.title = `${skill.description}\nSHA-256 ${skill.sha256}`; skills.append(option);
  }
  renderScan(); renderWorkList(); renderWorkDetail();
  if (!state.libraryWorkId && state.libraryWorks.length) {
    loadWork(state.libraryWorks[0].work_id).catch((error) => notice(error.message, true));
  }
}

function renderScan() {
  const summary = $('scanSummary'); const container = $('scanCandidates');
  summary.replaceChildren(); container.replaceChildren();
  if (!state.libraryScan) {
    summary.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'填写一个明确文件夹后，系统先生成候选清单。'}));
    $('approveCandidates').hidden = true; return;
  }
  const scan = state.libraryScan;
  const heading = document.createElement('article'); heading.className = 'scan-receipt';
  const title = document.createElement('strong'); title.textContent = `${scan.candidates.length} 个候选 · ${scan.status}`;
  const skill = document.createElement('small'); skill.textContent = `${scan.skill_name} · Skill SHA-256 ${scan.skill_sha256}`;
  const root = document.createElement('small'); root.textContent = scan.root_path;
  heading.append(title, skill, root); summary.append(heading);
  const unsupported = scan.candidates.filter((item) => item.triage_state === 'unsupported');
  if (unsupported.length) {
    const formats = Object.entries(unsupported.reduce((result, item) => {
      result[item.format] = (result[item.format] || 0) + 1; return result;
    }, {})).map(([format, count]) => `${format.toUpperCase()} ${count}`).join(' · ');
    const note = document.createElement('p'); note.className = 'boundary-note';
    note.textContent = `${unsupported.length} 个当前不解析的文件已保留在盘点收据中，不在此展开：${formats}`;
    summary.append(note);
  }
  let selectable = 0;
  for (const candidate of scan.candidates.filter((item) => item.triage_state !== 'unsupported')) {
    const card = document.createElement('article'); card.className = `candidate ${candidate.triage_state}`;
    const check = document.createElement('input'); check.type = 'checkbox'; check.dataset.candidateId = candidate.candidate_id;
    check.disabled = candidate.status !== 'preview' || ['unsupported', 'error', 'unchanged'].includes(candidate.triage_state) || candidate.proposed_action === 'unchanged';
    check.checked = !check.disabled; if (!check.disabled) selectable += 1;
    const body = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = candidate.suggested_title;
    const meta = document.createElement('small'); meta.textContent = `${actionLabels[candidate.proposed_action] || candidate.proposed_action} · ${triageLabels[candidate.triage_state] || candidate.triage_state} · ${candidate.format.toUpperCase()} · ${formatBytes(candidate.byte_count)}`;
    const bibliography = document.createElement('small'); bibliography.textContent = [candidate.suggested_author || '责任者待核', candidate.suggested_year || '年代待核', candidate.suggested_publisher || '出版信息待核'].join(' · ');
    const reason = document.createElement('p'); reason.textContent = candidate.triage_reason;
    const path = document.createElement('small'); path.className = 'path'; path.textContent = candidate.path;
    const exact = document.createElement('details');
    const exactTitle = document.createElement('summary'); exactTitle.textContent = '精确盘点信息';
    const exactText = document.createElement('pre'); exactText.textContent = `SHA-256  ${candidate.sha256 || '未取得'}\n物理页    ${candidate.page_count ?? '不适用'}\n已检查页  ${candidate.inspected_pages}\n文本层    ${candidate.text_layer}\n文件时间  ${new Date(candidate.modified_ns / 1e6).toLocaleString()}\n候选编号  ${candidate.candidate_id}${candidate.error ? `\n错误      ${candidate.error}` : ''}`;
    exact.append(exactTitle, exactText); body.append(name, meta, bibliography, reason, path, exact); card.append(check, body); container.append(card);
  }
  $('approveCandidates').hidden = selectable === 0;
}

function renderWorkList() {
  const list = $('workList'); list.replaceChildren();
  if (!state.libraryWorks.length) {
    list.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'图书馆还没有已批准材料。盘点不会自动入库。'})); return;
  }
  for (const work of state.libraryWorks) {
    const button = document.createElement('button'); button.className = 'work-row';
    button.classList.toggle('selected', work.work_id === state.libraryWorkId);
    const title = document.createElement('strong'); title.textContent = work.canonical_title;
    const author = document.createElement('span'); author.textContent = work.author || '作者待核';
    const meta = document.createElement('small'); meta.textContent = `${work.material_type} · ${work.file_count} 个位置 · ${work.version_count} 个版本`;
    const tags = document.createElement('small'); tags.textContent = work.tags.map((item) => item.name).join(' · ');
    button.append(title, author, meta, tags);
    button.onclick = () => loadWork(work.work_id).catch((error) => notice(error.message, true)); list.append(button);
  }
}

async function loadWork(workId) {
  state.libraryWorkId = workId;
  state.libraryWork = await request(`/api/library/work?id=${encodeURIComponent(workId)}`);
  renderWorkList(); renderWorkDetail();
}

function detailField(labelText, value, name) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input'); input.value = value || ''; input.dataset.field = name;
  label.append(input); return label;
}

function renderWorkDetail() {
  const container = $('workDetail'); container.replaceChildren();
  const work = state.libraryWork;
  if (!work) {
    container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'选择一部作品，查看完整书目信息、文件位置与每一次精确版本。'})); return;
  }
  const form = document.createElement('section'); form.className = 'bibliography-form';
  const edition = work.editions[0] || {};
  form.append(
    detailField('作品题名', work.canonical_title, 'canonical_title'),
    detailField('作者 / 责任者', work.author, 'author'),
    detailField('语言', work.language, 'language'),
    detailField('材料类型', work.material_type, 'material_type'),
    detailField('版本说明', edition.edition_label, 'edition_label'),
    detailField('出版者', edition.publisher, 'publisher'),
    detailField('出版年', edition.publication_year, 'publication_year'),
    detailField('ISBN', edition.isbn, 'isbn'),
    detailField('用户标签（逗号分隔）', work.tags.filter((item) => item.origin === 'user').map((item) => item.name).join(', '), 'tags'),
  );
  const actions = document.createElement('div'); actions.className = 'detail-actions';
  const save = document.createElement('button'); save.className = 'primary-inline'; save.textContent = '保存人工书目';
  save.onclick = async () => {
    try {
      const values = Object.fromEntries([...form.querySelectorAll('input')].map((input) => [input.dataset.field, input.value.trim()]));
      const tags = values.tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean); delete values.tags;
      values.edition_id = edition.edition_id || '';
      state.libraryWork = await request('/api/library/work/update', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({work_id:work.work_id, fields:values, tags})});
      await refreshLibrary(); notice('人工书目信息和标签已保存。');
    } catch (error) { notice(error.message, true); }
  };
  const link = document.createElement('button'); link.textContent = work.project_links.length ? '已关联当前项目' : '关联到当前项目'; link.disabled = work.project_links.length > 0;
  link.onclick = async () => {
    try {
      state.libraryWork = await request('/api/library/link', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({work_id:work.work_id})});
      renderWorkDetail(); notice('作品已关联到当前研究项目，原文件仍保持原位。');
    } catch (error) { notice(error.message, true); }
  };
  actions.append(save, link); form.append(actions); container.append(form);

  for (const file of work.files) {
    const section = document.createElement('section'); section.className = 'file-history';
    const heading = document.createElement('div'); heading.className = 'file-heading';
    const title = document.createElement('strong'); title.textContent = file.path;
    const fileStates = {
      matches_registered_version: '当前字节与已登记版本一致',
      changed_since_last_scan: '文件自上次登记后又有变化，请重新盘点',
      missing: '原文件当前位置已不可用',
    };
    const status = document.createElement('small'); status.textContent = fileStates[file.file_state] || file.file_state;
    const open = document.createElement('a'); open.textContent = '打开当前原文件'; open.href = `/api/library/file?id=${encodeURIComponent(file.file_id)}`; open.target = '_blank';
    heading.append(title, status, open); section.append(heading);
    for (const version of file.versions) {
      const card = document.createElement('article'); card.className = `version-card ${version.is_current ? 'current' : ''}`;
      const label = document.createElement('strong'); label.textContent = version.is_current ? '当前精确版本' : '历史版本记录';
      const availability = version.bytes_available ? '当前路径字节可打开' : '仅保留记录，旧字节未归档';
      const values = document.createElement('pre'); values.textContent = `Version ID  ${version.version_id}\nSHA-256    ${version.sha256}\n大小        ${formatBytes(version.byte_count)}\n文件时间    ${new Date(version.modified_ns / 1e6).toLocaleString()}\n发现时间    ${new Date(version.discovered_at).toLocaleString()}\n格式 / 页数 ${version.format.toUpperCase()} / ${version.page_count ?? '不适用'}\n文本层      ${version.text_layer}\n分诊        ${triageLabels[version.triage_state] || version.triage_state}\n资格        ${version.qualification}（不是 CITABLE）\nSkill       ${version.skill_name}\nSkill Hash  ${version.skill_sha256}\n字节可用性  ${availability}`;
      card.append(label, values); section.append(card);
    }
    container.append(section);
  }
}

async function refreshLibrary() {
  state.snapshot = await request('/api/snapshot');
  state.libraryWorks = state.snapshot.library_works || [];
  if (state.libraryWorkId) state.libraryWork = await request(`/api/library/work?id=${encodeURIComponent(state.libraryWorkId)}`);
  renderLibraryShell();
}

function renderAgentShell() {
  const models = $('modelProfile'); models.replaceChildren();
  for (const profile of (state.snapshot?.model_profiles || [])) {
    const option = new Option(`${profile.provider} · ${profile.model}`, profile.profile_id);
    option.selected = profile.assigned; option.disabled = profile.status !== 'available'; models.append(option);
  }
  const list = $('threadList'); list.replaceChildren();
  const threads = state.snapshot?.threads || [];
  if (!threads.length) list.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'还没有研究线程。'}));
  for (const thread of threads) {
    const button = document.createElement('button');
    const title = document.createElement('strong'); title.textContent = thread.title;
    const meta = document.createElement('small'); meta.textContent = `${thread.message_count} 条消息 · ${thread.latest_run_status || '尚未运行'}`;
    button.append(title, meta); button.classList.toggle('selected', thread.thread_id === state.threadId);
    button.onclick = () => loadThread(thread.thread_id).catch((error) => notice(error.message, true));
    list.append(button);
  }
  if (!state.threadId && threads.length) loadThread(threads[0].thread_id).catch((error) => notice(error.message, true));
  else renderThread();
}

async function loadThread(threadId) {
  state.threadId = threadId;
  state.thread = await request(`/api/thread?id=${encodeURIComponent(threadId)}`);
  renderAgentShell();
}

function latestRun() { return state.thread?.runs?.[0]; }

function renderThread() {
  $('threadTitle').textContent = state.thread?.thread?.title || '新建一个研究线程';
  const run = latestRun();
  $('runState').textContent = run ? `${run.status} · ${run.model_snapshot.provider} / ${run.model_snapshot.model}` : '对话与运行状态会保存在本地项目中';
  const messages = $('messages'); messages.replaceChildren();
  for (const message of (state.thread?.messages || [])) {
    const card = document.createElement('article'); card.className = `message ${message.role}`;
    const role = document.createElement('small'); role.textContent = message.role === 'user' ? '教授' : 'Research Agent';
    const text = document.createElement('p'); text.textContent = message.content.text || '';
    card.append(role, text); messages.append(card);
  }
  if (!state.thread) messages.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'创建线程后，可以让 Agent 查看项目、来源和页面，并在写入前等待你的决定。'}));
  messages.scrollTop = messages.scrollHeight;
  renderApproval(run); renderTimeline(run);
}

function renderApproval(run) {
  const panel = $('approvalPanel'); panel.replaceChildren();
  const approval = run?.approvals?.find((item) => item.status === 'pending');
  if (!approval) {
    panel.append(Object.assign(document.createElement('p'), {className:'empty approval-empty', textContent:'当前没有等待决定的操作。'}));
    return;
  }
  const card = document.createElement('article'); card.className = 'approval-card';
  const heading = document.createElement('h3'); heading.textContent = '保存研究札记？';
  const warning = document.createElement('p'); warning.textContent = '这是 Agent 的提案。请修改并确认后再写入项目。';
  const titleLabel = document.createElement('label'); titleLabel.textContent = '标题';
  const title = document.createElement('input'); title.value = approval.request.title || ''; titleLabel.append(title);
  const contentLabel = document.createElement('label'); contentLabel.textContent = '札记内容';
  const content = document.createElement('textarea'); content.value = approval.request.content || ''; contentLabel.append(content);
  const reviewerLabel = document.createElement('label'); reviewerLabel.textContent = '决定人';
  const reviewer = document.createElement('input'); reviewer.value = $('reviewer').value || 'human-reviewer'; reviewerLabel.append(reviewer);
  const reasonLabel = document.createElement('label'); reasonLabel.textContent = '决定依据';
  const reason = document.createElement('input'); reason.placeholder = '例如：已核对项目状态'; reasonLabel.append(reason);
  const actions = document.createElement('div'); actions.className = 'approval-actions';
  const approve = document.createElement('button'); approve.className = 'primary-inline'; approve.textContent = '修改后批准';
  const reject = document.createElement('button'); reject.textContent = '拒绝写入';
  const decide = async (approved) => {
    if (!reviewer.value.trim() || !reason.value.trim()) throw new Error('请填写决定人和决定依据。');
    state.thread = await request('/api/approval/decide', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      approval_id:approval.approval_id, approved, reviewer:reviewer.value, reason:reason.value,
      edited_request:{title:title.value, content:content.value},
    })});
    await refreshAgentSnapshot(); notice(approved ? '札记已经人工核准并保存。' : '提案已拒绝，没有写入札记。');
  };
  approve.onclick = () => decide(true).catch((error) => notice(error.message, true));
  reject.onclick = () => decide(false).catch((error) => notice(error.message, true));
  actions.append(approve, reject); card.append(heading, warning, titleLabel, contentLabel, reviewerLabel, reasonLabel, actions); panel.append(card);
}

function renderTimeline(run) {
  const timeline = $('runTimeline'); timeline.replaceChildren();
  if (!run) { timeline.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'运行后会显示模型、工具、错误和审批时间线。'})); return; }
  for (const event of [...run.events].reverse()) {
    const row = document.createElement('article'); row.className = 'timeline-event';
    const title = document.createElement('strong'); title.textContent = event.event_type;
    const meta = document.createElement('small'); meta.textContent = `#${event.sequence} · ${new Date(event.created_at).toLocaleString()}`;
    let detail = '';
    if (event.payload.tool) detail = event.payload.tool;
    else if (event.payload.error) detail = event.payload.error;
    const text = document.createElement('p'); text.textContent = detail;
    row.append(title, meta); if (detail) row.append(text); timeline.append(row);
  }
}

async function refreshAgentSnapshot() {
  state.snapshot = await request('/api/snapshot');
  if (state.threadId) state.thread = await request(`/api/thread?id=${encodeURIComponent(state.threadId)}`);
  renderAgentShell();
}

async function loadSource(sourceId, keepPage = false) {
  state.view = await request(`/api/source?id=${encodeURIComponent(sourceId)}`);
  if (!keepPage) state.pageIndex = 0;
  state.pageIndex = Math.min(state.pageIndex, Math.max(0, state.view.pages.length - 1));
  render();
}

function currentPage() { return state.view?.pages[state.pageIndex]; }
function openAnomalies() { return (state.view?.anomalies || []).filter((item) => item.status === 'open'); }
function pageAnomaly(page) { return openAnomalies().find((item) => item.scope_type === 'page' && item.target_id === page?.page_id); }

function renderRail() {
  const rail = $('pageRail'); rail.replaceChildren();
  for (const [index, page] of (state.view?.pages || []).entries()) {
    const button = document.createElement('button');
    button.textContent = `第 ${page.physical_page} 页${page.printed_page ? ` · ${page.printed_page}` : ''}`;
    button.classList.toggle('selected', index === state.pageIndex);
    button.classList.toggle('blocked', page.use_state === 'blocked');
    button.onclick = () => { state.pageIndex = index; render(); };
    rail.append(button);
  }
}

function blockCard(block, pageAnomaly) {
  const card = document.createElement('article'); card.className = 'block-card';
  const anomaly = openAnomalies().find((item) => item.scope_type === 'block' && item.target_id === block.block_id);
  card.classList.toggle('blocked', Boolean(anomaly)); card.dataset.order = block.block_order;
  const meta = document.createElement('div'); meta.className = 'block-meta';
  const region = block.source_region ? Object.values(block.source_region).map((v) => Number(v).toFixed(2)).join(', ') : '未定位';
  const label = document.createElement('span'); label.textContent = `块 ${block.block_order} · 区域 ${region}`;
  const type = document.createElement('select'); type.className = 'block-type';
  for (const value of ['paragraph', 'heading', 'footnote', 'header', 'footer', 'page_number']) type.append(new Option(value, value));
  type.value = block.block_type; meta.append(label, type);
  const textarea = document.createElement('textarea'); textarea.value = block.effective_text; textarea.dataset.blockId = block.block_id;
  card.append(meta, textarea);
  if (anomaly && !pageAnomaly) {
    const actions = document.createElement('div'); actions.className = 'block-actions';
    const button = document.createElement('button'); button.textContent = '提交这一小段';
    button.onclick = async () => {
      try {
        await request('/api/repair/block', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ anomaly_id: anomaly.anomaly_id, text: textarea.value, ...reviewerPayload() }) });
        await loadSource(state.view.source.source_id, true); notice('局部修正已提交，其他异常保持不变。');
      } catch (error) { notice(error.message, true); }
    };
    actions.append(button); card.append(actions);
  }
  return card;
}

function renderBlocks() {
  const page = currentPage(); const container = $('blocks'); container.replaceChildren();
  if (!page) { container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'导入 PDF 后显示逐页文本。'})); return; }
  const pageIssue = pageAnomaly(page);
  const blocks = page.blocks.length ? page.blocks : [{block_id:'', block_order:1, block_type:'paragraph', effective_text:'', source_region:null}];
  for (const block of blocks) container.append(blockCard(block, pageIssue));
  $('pageRepair').hidden = !pageIssue;
  $('pageRepair').onclick = async () => {
    try {
      const cards = [...container.querySelectorAll('.block-card')];
      const repaired = cards.map((card, index) => ({
        order: Number(card.dataset.order || index + 1),
        type: card.querySelector('.block-type').value,
        text: card.querySelector('textarea').value,
      }));
      await request('/api/repair/page', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({anomaly_id:pageIssue.anomaly_id, blocks:repaired, ...reviewerPayload()}) });
      await loadSource(state.view.source.source_id, true); notice('整页修正已提交，并保留原机器结果和修正记录。');
    } catch (error) { notice(error.message, true); }
  };
}

function proposalBlock(block) {
  const card = document.createElement('article'); card.className = 'proposal-block'; card.dataset.order = block.order;
  card.dataset.region = JSON.stringify(block.region || null);
  const meta = document.createElement('div'); meta.className = 'block-meta';
  const label = document.createElement('span'); label.textContent = `建议块 ${block.order}`;
  const type = document.createElement('select'); type.className = 'block-type';
  for (const value of ['paragraph', 'heading', 'footnote', 'header', 'footer', 'page_number']) type.append(new Option(value, value));
  type.value = block.type; meta.append(label, type);
  const textarea = document.createElement('textarea'); textarea.value = block.text;
  card.append(meta, textarea); return card;
}

function renderOcrProposal() {
  const page = currentPage();
  const container = $('ocrProposal'); container.replaceChildren();
  const button = $('ocrPropose');
  const capability = state.capabilities?.vision_ocr;
  if (capability?.available) {
    $('ocrCapability').textContent = `${capability.provider} · ${capability.model} · 输出只作为待审建议`;
  } else {
    const missing = capability?.missing?.join('、') || '尚未配置';
    $('ocrCapability').textContent = `视觉模型不可用：${missing}`;
  }
  if (!page) { button.hidden = true; return; }
  const proposals = (state.view?.ocr_proposals || []).filter((item) => item.page_id === page.page_id);
  const pending = proposals.find((item) => item.status === 'pending');
  const anomaly = pageAnomaly(page);
  button.hidden = !capability?.available || !anomaly || Boolean(pending);
  button.onclick = async () => {
    button.disabled = true;
    try {
      notice(`正在让 ${capability.model} 分析当前原页；结果不会自动写入正文……`);
      await request('/api/ocr/propose', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({page_id:page.page_id})});
      await loadSource(state.view.source.source_id, true); notice('模型建议已保存为待复核记录，请对照左侧原页修改。');
    } catch (error) { notice(error.message, true); }
    finally { button.disabled = false; }
  };
  if (!pending) {
    const latest = proposals[0];
    const text = latest ? `最近建议：${latest.provider} · ${latest.model} · ${latest.status}` : '当前页还没有模型建议。';
    container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:text}));
    return;
  }
  const card = document.createElement('article'); card.className = 'proposal-card';
  const meta = document.createElement('p'); meta.className = 'proposal-meta';
  meta.textContent = `${pending.provider} · ${pending.model} · ${pending.prompt_version} · 尚未进入正文`;
  card.append(meta);
  const blocks = document.createElement('div'); blocks.className = 'proposal-blocks';
  for (const block of pending.normalized_payload.blocks) blocks.append(proposalBlock(block));
  card.append(blocks);
  const warnings = pending.normalized_payload.warnings || [];
  if (warnings.length) card.append(Object.assign(document.createElement('small'), {textContent:`模型警告：${warnings.join('；')}`}));
  const actions = document.createElement('div'); actions.className = 'proposal-actions';
  const accept = document.createElement('button'); accept.className = 'primary-inline'; accept.textContent = '核对后接受修正';
  accept.onclick = async () => {
    try {
      const edited = [...blocks.querySelectorAll('.proposal-block')].map((item, index) => ({
        order: Number(item.dataset.order || index + 1),
        type: item.querySelector('.block-type').value,
        text: item.querySelector('textarea').value,
        region: JSON.parse(item.dataset.region),
      }));
      await request('/api/ocr/accept', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({proposal_id:pending.proposal_id, blocks:edited, ...reviewerPayload()})});
      await loadSource(state.view.source.source_id, true); notice('模型建议经人工核对后已作为整页修正提交。');
    } catch (error) { notice(error.message, true); }
  };
  const reject = document.createElement('button'); reject.textContent = '拒绝这份建议';
  reject.onclick = async () => {
    try {
      await request('/api/ocr/reject', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({proposal_id:pending.proposal_id, ...reviewerPayload()})});
      await loadSource(state.view.source.source_id, true); notice('模型建议已拒绝，页面异常仍保持待复核。');
    } catch (error) { notice(error.message, true); }
  };
  actions.append(accept, reject); card.append(actions); container.append(card);
}

function renderAnomalies() {
  const container = $('anomalies'); container.replaceChildren();
  const anomalies = openAnomalies();
  if (!anomalies.length) { container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'当前没有待复核项。'})); return; }
  for (const anomaly of anomalies) {
    const card = document.createElement('article'); card.className = 'anomaly';
    const message = document.createElement('p'); message.textContent = anomaly.message;
    const meta = document.createElement('small'); meta.textContent = `${anomaly.scope_type} · ${anomaly.category} · ${anomaly.severity}`;
    card.append(message, meta);
    if (anomaly.scope_type === 'relation') {
      const relation = state.view.relations.find((item) => item.relation_id === anomaly.target_id);
      const actions = document.createElement('div'); actions.className = 'relation-actions';
      for (const [label, continues] of [['确认跨页续接', true], ['确认不续接', false]]) {
        const button = document.createElement('button'); button.textContent = label;
        button.onclick = async () => {
          try {
            await request('/api/repair/relation', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({anomaly_id:anomaly.anomaly_id, continues, ...reviewerPayload()})});
            await loadSource(state.view.source.source_id, true); notice(`跨页关系已人工确认：${continues ? '续接' : '不续接'}。`);
          } catch (error) { notice(error.message, true); }
        };
        actions.append(button);
      }
      if (relation) { const detail = document.createElement('small'); detail.textContent = ` ${relation.from_block_id} → ${relation.to_block_id}`; card.append(detail); }
      card.append(actions);
    }
    container.append(card);
  }
}

function render() {
  renderRail(); renderOcrProposal(); renderBlocks(); renderAnomalies();
  const page = currentPage(); const source = state.view?.source;
  $('sourceTitle').textContent = source?.title || '尚未导入文献';
  $('sourceState').textContent = source ? `${source.processing_state} · ${source.use_state}` : '等待材料';
  $('pageLabel').textContent = page ? `物理页 ${page.physical_page}${page.printed_page ? ` · 印刷页 ${page.printed_page}` : ''}` : '原 PDF 页面始终是校对依据';
  $('pageImage').src = page ? `/api/page-image?id=${encodeURIComponent(page.page_id)}` : '';
  $('pageImage').style.transform = `scale(${state.zoom})`;
  $('zoomValue').textContent = `${Math.round(state.zoom * 100)}%`;
}

$('sourceSelect').onchange = (event) => loadSource(event.target.value).catch((error) => notice(error.message, true));
function setMode(mode) {
  $('libraryWorkbench').hidden = mode !== 'library';
  $('agentWorkbench').hidden = mode !== 'agent';
  $('pdfWorkbench').hidden = mode !== 'source';
  $('libraryMode').classList.toggle('mode-active', mode === 'library');
  $('agentMode').classList.toggle('mode-active', mode === 'agent');
  $('sourceMode').classList.toggle('mode-active', mode === 'source');
}
$('libraryMode').onclick = () => setMode('library');
$('agentMode').onclick = () => setMode('agent');
$('sourceMode').onclick = () => setMode('source');
$('scanLibrary').onclick = async () => {
  const sourceRoot = $('scanRoot').value.trim();
  if (!sourceRoot) { notice('请先填写本次允许盘点的文件夹。', true); return; }
  $('scanLibrary').disabled = true;
  try {
    notice('正在只读盘点明确选择的目录；尚未把任何材料加入图书馆……');
    state.libraryScan = await request('/api/library/scan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_root:sourceRoot, skill_name:$('intakeSkill').value})});
    renderScan(); notice(`盘点完成：${state.libraryScan.candidates.length} 个候选，等待你决定是否入库。`);
  } catch (error) { notice(error.message, true); }
  finally { $('scanLibrary').disabled = false; }
};
$('approveCandidates').onclick = async () => {
  const candidateIds = [...$('scanCandidates').querySelectorAll('input[type=checkbox]:checked')].map((item) => item.dataset.candidateId);
  if (!candidateIds.length) { notice('请至少选择一个可入库候选。', true); return; }
  $('approveCandidates').disabled = true;
  try {
    const result = await request('/api/library/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:state.libraryScan.session_id, candidate_ids:candidateIds})});
    state.libraryScan = await request(`/api/library/scan?id=${encodeURIComponent(state.libraryScan.session_id)}`);
    if (result.approved[0]) state.libraryWorkId = result.approved[0].work_id;
    await refreshLibrary(); notice(`已人工批准 ${result.approved.length} 个候选；原文件没有移动或修改。`);
  } catch (error) { notice(error.message, true); }
  finally { $('approveCandidates').disabled = false; }
};
$('searchLibrary').onclick = async () => {
  try {
    state.libraryWorks = await request(`/api/library/search?q=${encodeURIComponent($('libraryQuery').value.trim())}`);
    renderWorkList(); notice(`找到 ${state.libraryWorks.length} 部作品。`);
  } catch (error) { notice(error.message, true); }
};
$('libraryQuery').onkeydown = (event) => { if (event.key === 'Enter') $('searchLibrary').click(); };
$('newThread').onclick = async () => {
  const title = window.prompt('这个研究线程讨论什么？', '新的研究讨论');
  if (!title?.trim()) return;
  try {
    const thread = await request('/api/thread/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    state.threadId = thread.thread_id; await refreshAgentSnapshot(); notice('研究线程已创建并保存在本地项目。');
  } catch (error) { notice(error.message, true); }
};
$('modelProfile').onchange = async (event) => {
  try {
    await request('/api/model/assign', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({profile_id:event.target.value})});
    await refreshAgentSnapshot(); notice('主模型配置已更新；只影响之后的新 Run。');
  } catch (error) { notice(error.message, true); }
};
$('sendMessage').onclick = async () => {
  const content = $('messageInput').value.trim();
  if (!state.threadId) { notice('请先创建一个研究线程。', true); return; }
  if (!content) { notice('请输入研究任务。', true); return; }
  $('sendMessage').disabled = true;
  try {
    notice('Agent 正在读取项目并调用工具……');
    state.thread = await request('/api/agent/message', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({thread_id:state.threadId, content})});
    $('messageInput').value = ''; await refreshAgentSnapshot(); notice(latestRun()?.status === 'WAITING_FOR_APPROVAL' ? 'Agent 已暂停，等待你检查右侧提案。' : '本次运行已完成。');
  } catch (error) { notice(error.message, true); }
  finally { $('sendMessage').disabled = false; }
};
$('zoomIn').onclick = () => { state.zoom = Math.min(3, state.zoom + .2); render(); };
$('zoomOut').onclick = () => { state.zoom = Math.max(.4, state.zoom - .2); render(); };
$('importButton').onclick = async () => {
  const file = $('pdfFile').files[0];
  if (!file) { notice('请先选择一个 PDF。', true); return; }
  try {
    notice('正在复制原文件、渲染页面并检查文本层……');
    const result = await request(`/api/import?filename=${encodeURIComponent(file.name)}&title=${encodeURIComponent(file.name.replace(/\.pdf$/i,''))}`, {method:'POST', headers:{'Content-Type':'application/pdf'}, body:await file.arrayBuffer()});
    await loadSnapshot(result.source.source_id); notice(`已导入 ${result.intake.page_count} 页；发现 ${result.intake.anomaly_count || 0} 个待复核项。`);
  } catch (error) { notice(error.message, true); }
};

loadSnapshot().then(() => notice('本地项目已就绪。')).catch((error) => notice(error.message, true));
