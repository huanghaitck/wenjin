const state = {
  snapshot: null, capabilities: null, view: null, thread: null, threadId: '', pageIndex: 0, zoom: 1,
  libraryScan: null, libraryWorks: [], libraryWork: null, libraryWorkId: '',
  contextMode: 'sources', retrievalRecord: null,
  manuscriptId: '', sectionId: '', authoringMode: 'dialogue', proposalId: '',
  document: null, documentManuscriptId: '', selection: null, browserSession: null,
  modelSettings: null, sessionToken: '', lastDocxExport: '', nativeBridge: '',
};
const $ = (id) => document.getElementById(id);

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function nativeAvailable() {
  return Boolean(state.nativeBridge);
}

function tauriInvoke() {
  if(window.parent!==window){
    return (command,args={})=>new Promise((resolve,reject)=>{
      const id=crypto.randomUUID();
      const receive=(event)=>{
        const response=event.data?.hrwDesktopResponse;
        if(event.source!==window.parent||response?.id!==id)return;
        window.removeEventListener('message',receive);
        if(response.error)reject(new Error(response.error));else resolve(response.result);
      };
      window.addEventListener('message',receive);
      window.parent.postMessage({hrwDesktopRequest:{id,command,args}},'*');
    });
  }
  if(window.__TAURI__?.core?.invoke)return window.__TAURI__.core.invoke;
  if(window.__TAURI_INTERNALS__?.invoke)return window.__TAURI_INTERNALS__.invoke;
  return null;
}

async function nativeInvoke(command, args = {}) {
  if (!nativeAvailable()) throw new Error('这个动作只在安装后的桌面客户端中可用。');
  return tauriInvoke()(command, args);
}

function localSessionOptions(payload) {
  return {method:'POST', headers:{'Content-Type':'application/json','X-HRW-Session':state.sessionToken}, body:JSON.stringify(payload)};
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
  const [snapshot, capabilities, modelSettings, session] = await Promise.all([
    request('/api/snapshot'),
    request('/api/capabilities'),
    request('/api/model-settings'),
    request('/api/session'),
  ]);
  state.snapshot = snapshot; state.capabilities = capabilities;
  state.modelSettings = modelSettings; state.sessionToken = session.token;
  state.nativeBridge='';
  if(state.snapshot?.runtime?.mode==='desktop'&&tauriInvoke()){
    try{
      state.nativeBridge=await tauriInvoke()('desktop_status');
      await request('/api/desktop/bridge-ready',localSessionOptions({build:state.nativeBridge}));
    }catch(error){console.warn('Desktop bridge unavailable',error);}
  }
  for (const element of document.querySelectorAll('.desktop-only')) element.hidden = !nativeAvailable();
  renderAgentShell();
  renderAuthoring();
  state.libraryWorks = state.snapshot.library_works || [];
  renderLibraryShell();
  renderSettings();
  renderBrowserControls();
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
  renderContext();
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
    const add = document.createElement('button'); add.textContent = '加入当前项目文献';
    add.disabled = file.file_state !== 'matches_registered_version' || !file.path.toLowerCase().endsWith('.pdf');
    add.onclick = () => addLibraryFile(work.work_id, file.file_id).catch((error) => notice(error.message, true));
    heading.append(title, status, open, add); section.append(heading);
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
  const projectSelect = $('projectSelect'); projectSelect.replaceChildren();
  for (const project of (state.snapshot?.workspace?.projects || [])) {
    const option = new Option(`${project.title} · ${project.source_count} 项文献`, project.project_id);
    option.selected = project.project_id === state.snapshot?.project?.project_id;
    option.disabled = !project.available; projectSelect.append(option);
  }
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
  renderContext();
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
    card.append(role, text);
    if (message.context_binding) {
      const context = document.createElement('small'); context.className = 'message-context';
      const binding = message.context_binding;
      context.textContent = `稿件 ${binding.manuscript_id || '—'} · 修订 ${binding.revision_id || '—'} · 章节 ${binding.section_id || '—'}${binding.selection_hash ? ` · 选区 ${binding.selection_hash.slice(0, 10)}` : ''}`;
      card.append(context);
    }
    messages.append(card);
  }
  if (!state.thread) messages.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'创建线程后，可以让 Agent 查看项目、来源和页面，并在写入前等待你的决定。'}));
  messages.scrollTop = messages.scrollHeight;
  renderApproval(run); renderTimeline(run);
}

function card(title, detail = '') {
  const node = document.createElement('article'); node.className = 'context-card';
  const heading = document.createElement('h3'); heading.textContent = title; node.append(heading);
  if (detail) node.append(Object.assign(document.createElement('p'), {textContent:detail}));
  return node;
}

function actionButton(label, handler, primary = false) {
  const button = document.createElement('button'); button.textContent = label;
  if (primary) button.className = 'primary-inline';
  button.onclick = () => Promise.resolve(handler()).catch((error) => notice(error.message, true));
  return button;
}

function formField(label, id, value = '', area = false) {
  const wrapper = document.createElement('label'); wrapper.textContent = label;
  const input = document.createElement(area ? 'textarea' : 'input'); input.id = id; input.value = value;
  wrapper.append(input); return wrapper;
}

async function refreshResearch(message = '') {
  state.snapshot = await request('/api/snapshot');
  state.libraryWorks = state.snapshot.library_works || [];
  renderAgentShell();
  if (message) notice(message);
}

async function addLibraryFile(workId, fileId) {
  notice('正在复制精确图书馆版本并执行逐页处理；不会修改图书馆原件……');
  const result = await request('/api/library/add-to-project', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({work_id:workId, file_id:fileId})});
  await loadSnapshot(result.source.source_id);
  state.contextMode = 'sources'; renderContext();
  notice(`已加入项目并处理 ${result.intake.page_count} 个物理页。`);
}

function renderContext() {
  const container = $('contextContent'); if (!container || !state.snapshot) return;
  container.replaceChildren();
  for (const button of $('contextTabs').querySelectorAll('button')) button.classList.toggle('selected', button.dataset.context === state.contextMode);
  const research = state.snapshot.research || {};
  if (state.contextMode === 'sources') {
    for (const source of state.snapshot.sources || []) {
      const node = card(source.title, `${source.original_name} · ${source.processing_state}`);
      const chip = document.createElement('small'); chip.className = `status-chip ${source.use_state}`; chip.textContent = source.use_state;
      node.append(chip, actionButton('查看原页与文本', async () => { await loadSource(source.source_id); setMode('source'); })); container.append(node);
    }
    if (!state.snapshot.sources.length) container.append(card('项目还没有文献', '从图书馆加入书籍，或在顶部导入 PDF。'));
  } else if (state.contextMode === 'library') {
    for (const work of state.libraryWorks || []) {
      const node = card(work.canonical_title, `${work.author || '责任者待核'} · ${work.version_count} 个精确版本`);
      node.append(actionButton('选择版本并加入项目', async () => {
        const detail = await request(`/api/library/work?id=${encodeURIComponent(work.work_id)}`);
        const file = detail.files.find((item) => item.file_state === 'matches_registered_version' && item.path.toLowerCase().endsWith('.pdf'));
        if (!file) throw new Error('这部作品当前没有可用的已登记 PDF 版本。');
        await addLibraryFile(work.work_id, file.file_id);
      }, true)); container.append(node);
    }
  } else if (state.contextMode === 'retrieval') {
    const form = document.createElement('section'); form.className = 'context-form';
    const provider = document.createElement('select'); provider.id = 'researchProvider';
    for (const item of state.capabilities?.research_connectors || []) {
      const option = new Option(`${item.provider}${item.available ? '' : '（未配置）'}`, item.provider); option.disabled = !item.available; provider.append(option);
    }
    const label = document.createElement('label'); label.textContent = '开放数据库'; label.append(provider);
    form.append(label, formField('有界检索式', 'researchQuery'));
    form.append(actionButton('检索并保存回执', async () => {
      const result = await request('/api/research/search', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({provider:$('researchProvider').value, query:$('researchQuery').value, limit:10})});
      state.retrievalRecord = result; await refreshResearch(`检索完成：${result.result_count} 条线索，均为 DISCOVERED。`);
    }, true)); container.append(form);
    const records = state.snapshot.retrievals || [];
    for (const record of records) {
      const node = card(`${record.provider} · ${record.query}`, `${record.result_count} 条 · ${record.status} · ${new Date(record.created_at).toLocaleString()}`);
      node.append(actionButton('查看结果', async () => { state.retrievalRecord = await request(`/api/research/record?id=${encodeURIComponent(record.record_id)}`); renderContext(); })); container.append(node);
    }
    for (const item of state.retrievalRecord?.results || []) {
      const node = card(item.title || '无题名', `${item.authors || '作者待核'} · ${item.publication_year || '年代待核'} · ${item.qualification}`);
      if (item.url) { const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.textContent = '打开来源页'; node.append(link); }
      container.append(node);
    }
  } else if (state.contextMode === 'evidence') {
    const translation = state.capabilities?.translation;
    container.append(card('模型搭档', `主模型负责研究对话；视觉模型负责扫描页建议；翻译模型：${translation?.available ? `${translation.provider} / ${translation.model}` : '尚未配置，入口保持可见'}`));
    const form = document.createElement('section'); form.className = 'context-form';
    form.append(formField('候选主张', 'claimText', '', true), actionButton('建立候选主张', async () => {
      await request('/api/claim/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:$('claimText').value})});
      await refreshResearch('候选主张已保存，尚未冻结。');
    }, true)); container.append(form);
    for (const claim of research.claims || []) {
      const node = card(claim.text, `${claim.evidence.length} 条已核页面证据 · ${claim.status}`);
      if (state.view?.pages?.length) {
        const evidenceForm = document.createElement('div'); evidenceForm.className = 'context-form';
        const blocks = state.view.pages.flatMap((page) => page.blocks.map((block) => ({page, block}))).filter((item) => item.block.use_state === 'research_usable' && item.page.use_state === 'research_usable');
        const select = document.createElement('select'); select.dataset.role = 'evidence-block';
        for (const item of blocks) select.append(new Option(`物理页 ${item.page.physical_page} · ${item.block.effective_text.slice(0,42)}`, item.block.block_id));
        const quote = document.createElement('textarea'); quote.placeholder = '粘贴所选已核块中的原文；必须逐字存在';
        const note = document.createElement('input'); note.placeholder = '为何与主张有关';
        const relation = document.createElement('select'); for (const value of ['supports','weakens','background','counterevidence']) relation.append(new Option(value, value));
        evidenceForm.append(select, quote, note, relation, actionButton('人工提交证据', async () => {
          await request('/api/evidence/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({claim_id:claim.claim_id, block_id:select.value, quote:quote.value, note:note.value, relation:relation.value})});
          await refreshResearch('证据已固定到精确页面块和来源版本。');
        }, true)); node.append(evidenceForm);
      }
      for (const evidence of claim.evidence) {
        node.append(Object.assign(document.createElement('p'), {textContent:`${evidence.relation} · 物理页 ${evidence.physical_page} · “${evidence.quote}”`}));
        const translate = actionButton(translation?.available ? '调用翻译搭档' : '翻译搭档未配置', async () => {
          await request('/api/translation/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({evidence_id:evidence.evidence_id, target_language:'Chinese'})});
          await refreshResearch('译文已保存为派生稿，原文和页面锚点未改变。');
        }); translate.disabled = !translation?.available; node.append(translate);
      }
      container.append(node);
    }
  } else if (state.contextMode === 'writing') {
    const claims = research.claims || [];
    const form = document.createElement('section'); form.className = 'context-form'; form.append(formField('冻结包标题', 'freezeTitle', '试写证据包'));
    for (const claim of claims) { const label = document.createElement('label'); const check = document.createElement('input'); check.type='checkbox'; check.value=claim.claim_id; check.disabled=!claim.evidence.length; label.append(check, document.createTextNode(claim.text)); form.append(label); }
    form.append(actionButton('创建待批准冻结包', async () => {
      const claim_ids = [...form.querySelectorAll('input[type=checkbox]:checked')].map((item)=>item.value);
      await request('/api/freeze/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('freezeTitle').value, claim_ids})}); await refreshResearch('冻结包已创建，等待教授批准。');
    }, true)); container.append(form);
    for (const freeze of research.freezes || []) {
      const node = card(freeze.title, `${freeze.payload.claims.length} 个主张 · ${freeze.status}`);
      if (freeze.status === 'pending') node.append(actionButton('人工批准冻结', async () => { await request('/api/freeze/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({freeze_id:freeze.freeze_id, reviewer:'human-reviewer'})}); await refreshResearch('冻结包已人工批准。'); }, true));
      if (freeze.status === 'approved') node.append(actionButton('由冻结证据生成试写', async () => { await request('/api/draft/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({freeze_id:freeze.freeze_id, title:freeze.title})}); await refreshResearch('可追溯试写已生成。'); }, true));
      container.append(node);
    }
    for (const artifact of research.artifacts || []) {
      const version = artifact.versions[0]; const node = card(artifact.title, `${artifact.artifact_type} · ${version.version_id}`);
      const pre = document.createElement('pre'); pre.textContent = version.content; node.append(pre);
      node.append(actionButton('来源批判评审', async () => { const result = await request('/api/review/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({version_id:version.version_id})}); await refreshResearch(result.report); }));
      node.append(actionButton('导出 Markdown', async () => { const result = await request('/api/artifact/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({artifact_id:artifact.artifact_id})}); notice(`已导出：${result.project_path}`); }, true)); container.append(node);
    }
  } else if (state.contextMode === 'browser') {
    const form = document.createElement('section'); form.className = 'context-form';
    form.append(formField('起始网址', 'browserUrl', 'https://www.crossref.org/'), formField('允许域名', 'browserDomain', 'crossref.org'));
    form.append(actionButton('进入中央研究浏览器', async () => { state.browserSession = await request('/api/browser/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({start_url:$('browserUrl').value, allowed_domain:$('browserDomain').value})}); $('browserAddress').value=state.browserSession.start_url; await refreshResearch('研究浏览会话回执已保存；登录和下载仍由你决定。'); setMode('browser'); $('researchFrame').src=state.browserSession.start_url; }, true)); container.append(form);
    container.append(card('浏览器边界', '网页占据中央区域；只记录允许域名、起始页和操作回执，不读取 Cookie，不代替你登录、过验证码、付费或提交。'));
    for (const session of research.browser_sessions || []) container.append(card(session.allowed_domain, `${session.start_url} · ${session.status}`));
  } else if (state.contextMode === 'memory') {
    const form = document.createElement('section'); form.className = 'context-form';
    form.append(formField('类别', 'memoryCategory', '研究判断'), formField('候选内容', 'memoryContent', '', true), formField('来源 ID（逗号分隔）', 'memoryRefs'));
    form.append(actionButton('保存为记忆候选', async () => { await request('/api/memory/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({category:$('memoryCategory').value, content:$('memoryContent').value, source_refs:$('memoryRefs').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})}); await refreshResearch('只保存为项目内候选，尚未写入长期记忆库。'); }, true)); container.append(form);
    for (const item of research.memory_candidates || []) { const node = card(item.category, `${item.content}\n来源：${item.source_refs.join('、')} · ${item.status}`); if(item.status==='candidate') node.append(actionButton('批准为本地候选', async()=>{await request('/api/memory/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:item.candidate_id,approved:true})}); await refreshResearch('记忆候选已批准，但仍未自动写入外部知识库。');},true)); container.append(node); }
  }
}

function selectedManuscript() {
  return (state.snapshot?.authoring?.manuscripts || []).find((item) => item.manuscript_id === state.manuscriptId);
}

function selectedSection() {
  return selectedManuscript()?.sections.find((item) => item.section_id === state.sectionId);
}

async function loadDocument(manuscriptId) {
  if (!manuscriptId) { state.document = null; state.documentManuscriptId = ''; return; }
  state.document = await request(`/api/manuscript/document?id=${encodeURIComponent(manuscriptId)}`);
  state.documentManuscriptId = manuscriptId;
}

function documentSection() {
  return state.document?.document?.children?.find((item) => item.section_id === state.sectionId);
}

function renderDocumentCanvas() {
  const canvas = $('documentCanvas'); canvas.replaceChildren();
  const section = documentSection();
  if (!section) {
    canvas.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'选择稿件章节后开始编辑。'}));
    return;
  }
  const activeNotes = (state.document?.notes || []).filter((note) => note.status === 'active');
  for (const node of section.children || []) {
    const element = document.createElement(node.type === 'quote' ? 'blockquote' : 'p');
    element.dataset.nodeId = node.node_id; element.dataset.nodeType = node.type;
    const placements = activeNotes.map((note, index) => ({note, number:index + 1}))
      .filter((item) => item.note.anchor_node_id === node.node_id)
      .sort((a,b) => a.note.anchor_offset - b.note.anchor_offset);
    let cursor = 0;
    for (const item of placements) {
      const offset = Math.min(Math.max(cursor, item.note.anchor_offset), node.text.length);
      element.append(document.createTextNode(node.text.slice(cursor, offset)));
      const marker = document.createElement('sup'); marker.className='note-marker'; marker.contentEditable='false';
      marker.textContent=String(item.number); marker.title=item.note.current?.rendered_text || item.note.rendered_text;
      marker.onclick=()=>{state.authoringMode='notes'; renderAuthoringControl(section, null);};
      element.append(marker); cursor=offset;
    }
    element.append(document.createTextNode(node.text.slice(cursor)));
    canvas.append(element);
  }
}

function captureDocumentSection() {
  const section = documentSection();
  if (!section) throw new Error('请先选择稿件章节。');
  section.children = [...$('documentCanvas').children].filter((node) => node.matches('p, blockquote, li')).map((node) => ({
    type: node.tagName === 'BLOCKQUOTE' ? 'quote' : (node.tagName === 'LI' ? 'list_item' : 'paragraph'),
    node_id: node.dataset.nodeId || `NOD_${crypto.randomUUID().replaceAll('-', '')}`,
    text: (() => { const clone=node.cloneNode(true); clone.querySelectorAll('.note-marker').forEach((marker)=>marker.remove()); return clone.innerText.trim(); })(),
  }));
  if (!section.children.length) section.children.push({type:'paragraph', node_id:`NOD_${crypto.randomUUID().replaceAll('-', '')}`, text:''});
}

function currentSelectionContext() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !$('documentCanvas').contains(selection.anchorNode)) return state.selection || {text:'', nodeId:'', offset:0};
  const text = selection.toString().trim();
  const range=selection.getRangeAt(0);
  const startElement=(range.startContainer.nodeType===Node.ELEMENT_NODE?range.startContainer:range.startContainer.parentElement)?.closest?.('[data-node-id]');
  const endElement=(range.endContainer.nodeType===Node.ELEMENT_NODE?range.endContainer:range.endContainer.parentElement)?.closest?.('[data-node-id]');
  if (!startElement || startElement !== endElement) { notice('注释选区必须位于同一段落内。', true); return state.selection || {text:'',nodeId:'',offset:0}; }
  const before=range.cloneRange(); before.selectNodeContents(startElement); before.setEnd(range.endContainer,range.endOffset);
  const fragment=before.cloneContents(); fragment.querySelectorAll?.('.note-marker').forEach((marker)=>marker.remove());
  state.selection = {text, nodeId:startElement.dataset.nodeId || '', offset:fragment.textContent.length};
  $('selectionContext').textContent = text ? `已固定选区：“${text.slice(0, 42)}${text.length > 42 ? '…' : ''}”` : '当前稿件、修订、章节与选区会随消息保存';
  return state.selection;
}

async function refreshAuthoring(message = '') {
  state.snapshot = await request('/api/snapshot');
  state.libraryWorks = state.snapshot.library_works || [];
  renderAgentShell(); renderLibraryShell();
  if (state.manuscriptId) await loadDocument(state.manuscriptId);
  renderAuthoring();
  if (message) notice(message);
}

function renderAuthoring() {
  if (!state.snapshot || !$('manuscriptList')) return;
  const manuscripts = state.snapshot.authoring?.manuscripts || [];
  if (!state.manuscriptId && manuscripts.length) state.manuscriptId = manuscripts[0].manuscript_id;
  let manuscript = selectedManuscript();
  if (state.manuscriptId && !manuscript) { state.manuscriptId = manuscripts[0]?.manuscript_id || ''; manuscript = selectedManuscript(); }
  if (!state.sectionId && manuscript?.sections.length) state.sectionId = manuscript.sections[0].section_id;
  let section = selectedSection();
  if (state.sectionId && !section) { state.sectionId = manuscript?.sections[0]?.section_id || ''; section = selectedSection(); }
  const list = $('manuscriptList'); list.replaceChildren();
  for (const item of manuscripts) {
    const node = document.createElement('article'); node.className = 'manuscript-row';
    node.append(Object.assign(document.createElement('h3'), {textContent:item.title}));
    for (const part of item.sections) {
      const button = document.createElement('button'); button.textContent = `${part.section_order}. ${part.heading}`;
      button.classList.toggle('selected', part.section_id === state.sectionId);
      button.onclick = () => { state.manuscriptId=item.manuscript_id; state.sectionId=part.section_id; state.proposalId=''; renderAuthoring(); };
      node.append(button);
    }
    list.append(node);
  }
  if (state.manuscriptId && state.documentManuscriptId !== state.manuscriptId) {
    loadDocument(state.manuscriptId).then(renderAuthoring).catch((error) => notice(error.message, true)); return;
  }
  $('sectionHeading').textContent = section?.heading || '选择一个章节';
  $('sectionVersion').textContent = state.document ? `${state.document.current_revision_id} · 结构化稿件修订` : (section ? `${section.current_version_id} · ${section.operation}` : '人工保存后才产生新修订');
  $('sectionBase').value = section?.content || '';
  const proposals = section?.proposals || [];
  let proposal = proposals.find((item) => item.proposal_id === state.proposalId) || proposals.find((item) => item.status === 'pending') || proposals[0];
  if (proposal) state.proposalId = proposal.proposal_id;
  $('sectionProposal').value = proposal?.proposed_content || '';
  const templateSelect=$('exportTemplate'); const previous=templateSelect.value; templateSelect.replaceChildren();
  for(const template of state.snapshot.authoring?.journal_templates||[]) templateSelect.append(new Option(template.name,template.template_id));
  templateSelect.value=previous||'builtin-history-research';
  const text=state.document?.document ? state.document.document.children.flatMap((part)=>part.children||[]).map((node)=>node.text).join('') : '';
  const notes=state.document?.notes||[];
  $('manuscriptStats').textContent=state.document ? `${text.length} 字符 · ${state.document.document.children.length} 节 · ${notes.filter((note)=>note.status==='active').length} 条已批准注释 · ${notes.filter((note)=>note.pending).length} 条待审` : '尚未选择稿件';
  renderDocumentCanvas();
  renderAuthoringControl(section, proposal);
}

function renderAuthoringControl(section, proposal) {
  const container = $('authoringContent'); container.replaceChildren();
  for (const button of $('authoringTabs').querySelectorAll('button')) button.classList.toggle('selected', button.dataset.authoring === state.authoringMode);
  const authoring = state.snapshot.authoring || {};
  if (state.authoringMode === 'dialogue') {
    const threads = state.snapshot.threads || [];
    const form = document.createElement('section'); form.className = 'context-form';
    const select = document.createElement('select'); select.id = 'manuscriptThread';
    select.append(new Option('选择研究线程', ''));
    for (const thread of threads) select.append(new Option(thread.title, thread.thread_id));
    select.value = state.threadId || '';
    const label = document.createElement('label'); label.textContent = '同一个项目主 Agent'; label.append(select);
    form.append(label, formField('围绕当前章节或选区讨论', 'manuscriptMessage', '', true));
    form.append(actionButton('新建稿件讨论线程', async()=>{
      const created = await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`稿件讨论｜${selectedManuscript()?.title || '未命名稿件'}`})});
      state.threadId=created.thread_id; await refreshAuthoring('已建立项目级稿件讨论线程。');
    }));
    form.append(actionButton('带上下文发送', async()=>{
      if (!select.value) throw new Error('请先在研究对话中新建或选择一个线程。');
      const selection = currentSelectionContext();
      const context = {manuscript_id:state.manuscriptId, revision_id:state.document?.current_revision_id || '', section_id:state.sectionId, node_id:selection.nodeId, selection_text:selection.text, attached_refs:[]};
      state.threadId = select.value;
      state.thread = await request('/api/agent/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({thread_id:select.value,content:$('manuscriptMessage').value,context})});
      await refreshAuthoring('消息已保存，并固定到当前稿件修订与选区；不会自动写入正文。');
    }, true)); container.append(form);
    container.append(card('上下文边界', `稿件 ${state.manuscriptId || '—'}\n修订 ${state.document?.current_revision_id || '—'}\n章节 ${state.sectionId || '—'}\n灵感讨论默认只留在对话。`));
  } else if (state.authoringMode === 'notes') {
    const selection=state.selection||{text:'',nodeId:'',offset:0};
    container.append(card('当前注释位置', selection.nodeId ? `选区：“${selection.text || '光标位置'}”\n段落 ${selection.nodeId} · 字符位置 ${selection.offset}` : '先在正文同一段落中选中文字，再点击“插入注释”。'));
    const form=document.createElement('section'); form.className='context-form';
    const template=document.createElement('select'); template.id='noteTemplate';
    for(const item of authoring.journal_templates||[]) template.append(new Option(`${item.name} · ${item.version_label||'人工模板'}`,item.template_id));
    template.value=$('exportTemplate').value||'builtin-history-research';
    const templateLabel=document.createElement('label'); templateLabel.textContent='注释模板'; templateLabel.append(template);
    const mode=document.createElement('select'); mode.id='noteMode';
    mode.append(new Option('核对原页后插入','VERIFY_AND_INSERT'),new Option('元数据已核，页码稍后补','METADATA_FIRST_PAGE_LATER'),new Option('只整理现有注释文字','REFORMAT_EXISTING'));
    const modeLabel=document.createElement('label'); modeLabel.textContent='处理模式'; modeLabel.append(mode);
    const evidence=document.createElement('select'); evidence.id='noteEvidence'; evidence.append(new Option('未选择页块证据',''));
    for(const claim of state.snapshot.research?.claims||[]) for(const item of claim.evidence||[]) evidence.append(new Option(`${item.source_title||item.source_id} · 物理页 ${item.physical_page||'—'} · ${item.quote.slice(0,32)}`,item.evidence_id));
    const evidenceLabel=document.createElement('label'); evidenceLabel.textContent='已冻结到原页的证据'; evidenceLabel.append(evidence);
    form.append(templateLabel,modeLabel,evidenceLabel,
      formField('来源类型（book/article/archive/classic）','noteSourceType','book'),formField('作者','noteAuthor'),formField('题名','noteTitle'),
      formField('出版地','notePlace'),formField('出版者','notePublisher'),formField('年份','noteYear'),
      formField('原书页码或稳定定位','noteOriginalPage'),formField('数字文件页（仅辅助定位）','noteDigitalPage'),
      formField('已有注释原文（仅“整理现有注释”使用）','noteExisting','',true));
    form.append(actionButton('生成待审注释',async()=>{
      if(!state.manuscriptId||!selection.nodeId) throw new Error('请先在正文同一段落中选中文字。');
      const citation_data={source_type:$('noteSourceType').value,author:$('noteAuthor').value,title:$('noteTitle').value,place:$('notePlace').value,publisher:$('notePublisher').value,year:$('noteYear').value,original_page:$('noteOriginalPage').value,digital_page:$('noteDigitalPage').value,user_supplied_text:$('noteExisting').value};
      await request('/api/note/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,anchor_node_id:selection.nodeId,anchor_offset:selection.offset,anchor_text:selection.text,template_id:template.value,mode:mode.value,citation_data,evidence_id:evidence.value})});
      await refreshAuthoring('注释已生成待审版本；批准前不会进入正文或导出文件。');
    },true)); container.append(form);
    for(const note of state.document?.notes||[]){
      const shown=note.pending||note.current||note.versions[0];
      const templateName=(authoring.journal_templates||[]).find((item)=>item.template_id===shown.template_id)?.name||shown.template_id;
      const locator=[shown.citation_data?.original_page&&`原书页 ${shown.citation_data.original_page}`,shown.citation_data?.digital_page&&`数字页 ${shown.citation_data.digital_page}`].filter(Boolean).join(' · ');
      const node=card(shown.rendered_text,`${templateName} · ${shown.verification_state} · ${note.status}${locator?` · ${locator}`:''}`);
      const badge=document.createElement('span');badge.className=`note-state ${note.status}`;badge.textContent=note.status;node.append(badge);
      if(shown.source_refs?.length) node.append(actionButton('打开原 PDF 对应页',async()=>{const ref=shown.source_refs[0];state.view=await request(`/api/source?id=${encodeURIComponent(ref.source_id)}`);state.pageIndex=Math.max(0,state.view.pages.findIndex((page)=>page.page_id===ref.page_id));renderWorkbench();setMode('source');}));
      if(note.current&&!note.pending) node.append(actionButton('修改并生成新版本',async()=>{const edited=window.prompt('修改注释文字；旧版会继续生效，直到新版本获批。',note.current.rendered_text);if(!edited?.trim())return;await request('/api/note/revise',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note_id:note.note_id,mode:'REFORMAT_EXISTING',citation_data:{user_supplied_text:edited}})});await refreshAuthoring('注释修订已生成待审版本；当前已批准版本仍继续生效。');}));
      if(note.pending){const row=document.createElement('div');row.className='row';row.append(actionButton('人工核对后批准',async()=>{await request('/api/note/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note_version_id:note.pending.note_version_id,approved:true,reviewer:'human-reviewer'})});await refreshAuthoring('注释版本已批准并进入正文视图。');},true),actionButton('拒绝',async()=>{await request('/api/note/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note_version_id:note.pending.note_version_id,approved:false,reviewer:'human-reviewer'})});await refreshAuthoring('注释提案已拒绝。');}));node.append(row);} container.append(node);
    }
  } else if (state.authoringMode === 'evidence') {
    const claims = state.snapshot.research?.claims || [];
    if (!claims.length) container.append(card('还没有主张与证据', '先在研究对话的“证据与论点”中建立主张，并回到原页固定证据。'));
    for (const claim of claims) container.append(card(claim.text, `${claim.status} · ${claim.evidence.length} 条页块证据`));
  } else if (state.authoringMode === 'versions') {
    if (!state.document) { container.append(card('尚无结构化版本', '选择稿件后自动建立兼容修订。')); return; }
    for (const revision of state.document.revisions || []) container.append(card(revision.revision_id, `${revision.source_format} · ${revision.status} · ${new Date(revision.created_at).toLocaleString()}\n文本指纹 ${revision.plain_text_hash.slice(0, 16)}…`));
    for (const receipt of state.document.io_receipts || []) container.append(card(`${receipt.direction} ${receipt.format.toUpperCase()}`, `${receipt.fidelity.level} · ${(receipt.fidelity.warnings || []).join('；') || '无保真警告'}`));
  } else if (state.authoringMode === 'write') {
    const model = authoring.writing_model || {};
    container.append(card('写作模型', model.available ? `${model.provider} / ${model.model}` : '未配置真实模型；保真门禁和规则型演示仍可使用'));
    if (!section) { container.append(card('尚未选择章节', '先导入 Markdown 稿件。')); return; }
    const form = document.createElement('section'); form.className='context-form';
    const operation = document.createElement('select'); operation.id='writingOperation';
    operation.append(new Option('保真润色','polish'), new Option('基于冻结证据分节写作','section_draft'));
    const operationLabel=document.createElement('label'); operationLabel.textContent='操作'; operationLabel.append(operation);
    const freeze=document.createElement('select'); freeze.id='writingFreeze'; freeze.append(new Option('不使用冻结包',''));
    for (const item of state.snapshot.research?.freezes || []) if(item.status==='approved') freeze.append(new Option(item.title,item.freeze_id));
    const freezeLabel=document.createElement('label'); freezeLabel.textContent='批准的证据冻结包'; freezeLabel.append(freeze);
    form.append(operationLabel, formField('修改或写作要求','writingInstruction','保持史学语气，不改变事实与引文',true), freezeLabel);
    form.append(actionButton('生成待审提案', async()=>{
      const result=await request('/api/writing/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section_id:section.section_id,operation:operation.value,instruction:$('writingInstruction').value,freeze_id:freeze.value})});
      state.proposalId=result.proposal_id; await refreshAuthoring(result.validation.valid?'写作提案已生成，等待逐项核对。':'提案缺少受保护标记，已阻断批准。');
    },true)); container.append(form);
    if (proposal) {
      const node=card(`${proposal.operation} · ${proposal.status}`, proposal.validation.valid?'受保护标记完整':'缺失：'+proposal.validation.missing_markers.join('、'));
      node.append(Object.assign(document.createElement('small'),{textContent:`基础版本 ${proposal.base_version_id} · ${new Date(proposal.created_at).toLocaleString()}`}));
      if(proposal.status==='pending') {
        const row=document.createElement('div'); row.className='row';
        row.append(actionButton('核对后批准',async()=>{await request('/api/writing/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:proposal.proposal_id,approved:true,reviewer:'human-reviewer',edited_content:$('sectionProposal').value})}); state.proposalId=''; await refreshAuthoring('已保存为新的批准章节版本，旧版本仍保留。');},true));
        row.append(actionButton('拒绝提案',async()=>{await request('/api/writing/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:proposal.proposal_id,approved:false,reviewer:'human-reviewer'})}); state.proposalId=''; await refreshAuthoring('提案已拒绝，当前章节未改变。');})); node.append(row);
      }
      container.append(node);
    }
  } else if (state.authoringMode === 'reading') {
    const form=document.createElement('section'); form.className='context-form';
    form.append(formField('阅读任务','readingTitle','围绕研究问题的定向阅读'),formField('研究问题','readingQuestion','',true));
    const mode=document.createElement('select'); mode.id='readingMode'; mode.append(new Option('元数据阅读','metadata'),new Option('定向阅读','targeted'),new Option('分批全文阅读','full')); form.append(mode);
    for(const source of state.snapshot.sources||[]){const label=document.createElement('label');const check=document.createElement('input');check.type='checkbox';check.value=source.source_id;label.append(check,document.createTextNode(source.title));form.append(label);}
    form.append(formField('停止条件','readingStop','完成所选来源当前可用页块后停止'));
    form.append(actionButton('建立并执行有界阅读',async()=>{const source_ids=[...form.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);await request('/api/reading/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('readingTitle').value,question:$('readingQuestion').value,mode:mode.value,source_ids,stop_condition:$('readingStop').value})});await refreshAuthoring('阅读札记已生成；它们不是证据。');},true));container.append(form);
    for(const job of authoring.reading_jobs||[]){const node=card(job.title,`${job.mode} · ${job.status} · ${job.notes.length} 份札记`);node.append(Object.assign(document.createElement('p'),{textContent:`问题：${job.question}；停止条件：${job.stop_condition}`}));for(const note of job.notes){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`${note.source_id} · ${note.qualification}`;const pre=document.createElement('pre');pre.textContent=note.content;details.append(summary,pre);node.append(details);}container.append(node);}
  } else if (state.authoringMode === 'historiography') {
    const form=document.createElement('section');form.className='context-form';
    for(const [label,id,area] of [['著作/论文','histWork',false],['核心立场','histPosition',true],['贡献','histContribution',true],['限制','histLimitation',true],['与当前问题关系','histRelevance',true],['来源引用（逗号分隔）','histRefs',false]]) form.append(formField(label,id,'',area));
    form.append(actionButton('保存学术史候选条目',async()=>{await request('/api/historiography/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_title:$('histWork').value,position:$('histPosition').value,contribution:$('histContribution').value,limitation:$('histLimitation').value,relevance:$('histRelevance').value,source_refs:$('histRefs').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})});await refreshAuthoring('学术史候选条目已保存，等待研究判断。');},true));container.append(form);
    for(const item of authoring.historiography||[]){const node=card(item.work_title,`${item.status} · 来源 ${item.source_refs.join('、')}`);node.append(Object.assign(document.createElement('p'),{textContent:`立场：${item.position}\n贡献：${item.contribution}\n限制：${item.limitation}\n关系：${item.relevance}`}));container.append(node);}
  } else if (state.authoringMode === 'journal') {
    const form=document.createElement('section');form.className='context-form';form.append(formField('模板名称','journalName'),formField('注释规则','journalCitation'),formField('章节顺序（逗号分隔）','journalSections'));
    form.append(actionButton('保存人工模板',async()=>{await request('/api/journal/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('journalName').value,citation_style:$('journalCitation').value,section_rules:$('journalSections').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})});await refreshAuthoring('期刊模板已保存；投稿前仍须核对最新规范。');},true));container.append(form);
    for(const item of authoring.journal_templates||[]){const node=card(item.name,`${item.version_label||'人工模板'} · ${item.verification_status||'USER_DEFINED'}`);node.append(Object.assign(document.createElement('p'),{textContent:`${item.citation_style}\n${item.section_rules.join(' → ')}\n核验：${item.verified_at||'由用户维护'}`}));if(item.source_url){const link=document.createElement('a');link.href=item.source_url;link.target='_blank';link.rel='noreferrer';link.textContent='查看规则来源';node.append(link);}container.append(node);}
  }
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

function renderSettings() {
  const container = $('settingsContent'); if (!container || !state.snapshot) return; container.replaceChildren();
  const project = state.snapshot.project || {}; const caps = state.capabilities || {};
  const runtime=state.snapshot.runtime||{};
  container.append(card('版本与项目', `Historical Research Workbench ${project.app_version || '—'} · Project schema ${project.schema_version || '—'}\n客户端：${runtime.mode||'browser'}${runtime.desktop_build ? ` · build ${runtime.desktop_build}` : ''} · 原生桥接：${state.nativeBridge?`已就绪 ${state.nativeBridge}`:'不可用'}\n${project.title || ''} · ${project.project_id || ''}\n项目文件保持本地，原始材料只读。`));
  for(const item of state.modelSettings?.roles||[]){
    const panel=card(item.label, `${item.provider==='disabled'?'尚未启用':`${item.provider} / ${item.model}`} · 密钥：${item.has_secret?'已保存到 Windows 凭据管理器':'未保存'}`);
    const form=document.createElement('section');form.className='context-form model-role-form';
    const provider=document.createElement('select');
    provider.append(new Option('未启用','disabled'),new Option('本地 Ollama','ollama'),new Option('OpenAI 兼容接口','openai_compatible'));provider.value=item.provider;
    const providerLabel=document.createElement('label');providerLabel.textContent='接口类型';providerLabel.append(provider);
    const model=document.createElement('input');model.value=item.model;model.placeholder='例如 qwen3.5:9b 或 glm-4.6v-flash';
    const modelLabel=document.createElement('label');modelLabel.textContent='模型名称';modelLabel.append(model);
    const baseUrl=document.createElement('input');baseUrl.value=item.base_url;baseUrl.placeholder='例如 http://127.0.0.1:11434';
    const urlLabel=document.createElement('label');urlLabel.textContent='接口地址';urlLabel.append(baseUrl);
    const apiKey=document.createElement('input');apiKey.type='password';apiKey.autocomplete='new-password';apiKey.placeholder=item.has_secret?'已安全保存；留空表示不更换':'远程接口需要，Ollama 留空';
    const keyLabel=document.createElement('label');keyLabel.textContent='API Key';keyLabel.append(apiKey);
    const timeout=document.createElement('input');timeout.type='number';timeout.min='5';timeout.max='600';timeout.value=item.timeout_seconds;
    const timeoutLabel=document.createElement('label');timeoutLabel.textContent='超时（秒）';timeoutLabel.append(timeout);
    const clear=document.createElement('input');clear.type='checkbox';clear.style.minHeight='auto';
    const clearLabel=document.createElement('label');clearLabel.append(clear,document.createTextNode(' 清除已经保存的密钥'));
    const row=document.createElement('div');row.className='row';
    row.append(actionButton('保存并应用',async()=>{
      try{
        const result=await request('/api/model-settings/save',localSessionOptions({role:item.role,provider:provider.value,model:model.value,base_url:baseUrl.value,api_key:apiKey.value,clear_secret:clear.checked,timeout_seconds:Number(timeout.value)}));
        state.modelSettings=result.settings;await loadSnapshot();notice(`${item.label}已经保存；之后的新任务会记录实际模型快照。`);
      }catch(error){notice(error.message,true);}
    },true),actionButton('测试连接',async()=>{
      try{const result=await request('/api/model-settings/probe',localSessionOptions({role:item.role}));notice(result.detail,!result.available);}catch(error){notice(error.message,true);}
    }));
    form.append(providerLabel,modelLabel,urlLabel,keyLabel,timeoutLabel,clearLabel,row);panel.append(form);container.append(panel);
  }
  const models = card('当前生效快照', '主推理模型可以在研究对话中选择；视觉 OCR 与翻译是辅助角色，输出仍须人工验收。');
  for (const profile of state.snapshot.model_profiles || []) models.append(Object.assign(document.createElement('p'), {textContent:`${profile.assigned ? '当前主模型' : profile.status} · ${profile.provider} / ${profile.model} · ${profile.endpoint||'本机规则'}`}));
  models.append(Object.assign(document.createElement('p'), {textContent:`视觉辅助：${caps.vision_ocr?.available ? `${caps.vision_ocr.provider} / ${caps.vision_ocr.model}` : '未配置'}\n翻译辅助：${caps.translation?.available ? `${caps.translation.provider} / ${caps.translation.model}` : '未配置'}`})); container.append(models);
  const skills = card('Skills 兼容', '当前只发现并展示 SKILL.md 指令，不自动执行任意脚本。');
  for (const skill of state.snapshot.library?.skills || []) skills.append(Object.assign(document.createElement('p'), {textContent:`${skill.name} · ${skill.execution}\n${skill.description}`})); container.append(skills);
  const connectors = card('研究连接器', '公开数据库可有界检索；已登录数据库只能在用户合法权限内操作。');
  for (const capability of caps.research_connectors || []) connectors.append(Object.assign(document.createElement('p'), {textContent:`${capability.provider} · ${capability.available ? '可用' : '未配置'} · ${capability.mode}${capability.missing?.length ? ` · 缺少 ${capability.missing.join('、')}` : ''}`})); container.append(connectors);
  container.append(card('隐私与人工门禁', '不保存 Cookie、密码、API Key 或未脱敏网络日志。远程模型只接收用户明确选择的页块、章节和选区。证据冻结、正文采用与记忆提升都必须由人决定。'));
}

function renderBrowserControls() {
  const container = $('browserControls'); if (!container) return; container.replaceChildren();
  const url = $('browserAddress').value.trim();
  const domain = (() => { try { return new URL(url).hostname; } catch { return ''; } })();
  const form = document.createElement('section'); form.className = 'context-form';
  form.append(formField('允许域名', 'centralBrowserDomain', domain));
  form.append(actionButton('保存浏览会话回执', async()=>{
    state.browserSession = await request('/api/browser/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_url:$('browserAddress').value,allowed_domain:$('centralBrowserDomain').value})});
    await refreshResearch('浏览会话回执已保存。网页内容仍只是研究线索，未自动成为证据。'); setMode('browser'); renderBrowserControls();
  }, true)); container.append(form);
  container.append(card('收集边界', '网页、下载和网址先进入图书馆收件箱；只有回到可核验原页并经人工资格判断后，才能成为证据。'));
  for (const session of state.snapshot?.research?.browser_sessions || []) container.append(card(session.allowed_domain, `${session.start_url}\n${session.status} · ${session.session_id}`));
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
  $('articleWorkbench').hidden = mode !== 'article';
  $('pdfWorkbench').hidden = mode !== 'source';
  $('browserWorkbench').hidden = mode !== 'browser';
  $('settingsWorkbench').hidden = mode !== 'settings';
  $('libraryMode').classList.toggle('mode-active', mode === 'library');
  $('agentMode').classList.toggle('mode-active', mode === 'agent');
  $('articleMode').classList.toggle('mode-active', mode === 'article');
  $('settingsMode').classList.toggle('mode-active', mode === 'settings');
  if (mode === 'settings') renderSettings();
  if (mode === 'browser') renderBrowserControls();
}
$('libraryMode').onclick = () => setMode('library');
$('agentMode').onclick = () => setMode('agent');
$('articleMode').onclick = () => { setMode('article'); renderAuthoring(); };
$('settingsMode').onclick = () => setMode('settings');
$('openSourceRepair').onclick = () => { if (!state.view) { notice('当前项目还没有可复核的 PDF。', true); return; } setMode('source'); };
$('backToLibrary').onclick = () => setMode('library');
$('authoringTabs').onclick = (event) => {
  const button = event.target.closest('button[data-authoring]');
  if (!button) return; state.authoringMode = button.dataset.authoring; renderAuthoring();
};
$('importManuscript').onclick = async () => {
  try {
    const result = await request('/api/manuscript/import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('manuscriptTitle').value, markdown:$('manuscriptMarkdown').value})});
    state.manuscriptId=result.manuscript_id; state.sectionId=result.sections[0]?.section_id||''; state.proposalId='';
    $('manuscriptTitle').value=''; $('manuscriptMarkdown').value=''; await refreshAuthoring('稿件已导入并按 Markdown 标题分节。');
  } catch (error) { notice(error.message, true); }
};
$('importDocx').onclick = async () => {
  const file = $('manuscriptDocx').files[0]; if (!file) { notice('请先选择一个 DOCX。', true); return; }
  try {
    const result = await request(`/api/manuscript/import-docx?title=${encodeURIComponent($('manuscriptTitle').value || file.name.replace(/\.docx$/i,''))}`, {method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},body:await file.arrayBuffer()});
    state.manuscriptId=result.manuscript_id; state.sectionId=result.document.children[0]?.section_id||''; state.document=result; state.documentManuscriptId=result.manuscript_id;
    await refreshAuthoring(`DOCX 已导入。保真提示：${result.import_fidelity.warnings.join('；')}`);
  } catch (error) { notice(error.message, true); }
};
$('saveDocument').onclick = async () => {
  try { captureDocumentSection(); state.document = await request('/api/manuscript/document/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,document:state.document.document})}); await refreshAuthoring('结构化稿件已保存为新修订；旧修订保持不变。'); }
  catch (error) { notice(error.message, true); }
};
async function exportCurrentDocument(format) {
  if (!state.manuscriptId) throw new Error('请先选择稿件。');
  const result = await request('/api/manuscript/document/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,format,template_id:$('exportTemplate').value})});
  if(result.native_path){
    if(format==='docx'){state.lastDocxExport=result.native_path;$('openInWord').disabled=false;}
  }else{
    const link=document.createElement('a'); link.href=result.download_url; link.download=''; document.body.append(link); link.click(); link.remove();
  }
  await loadDocument(state.manuscriptId); renderAuthoring();
  notice(`${format.toUpperCase()} 已导出${result.native_path?`到项目目录：${result.native_path}`:''}。保真级别：${result.fidelity.level}${result.fidelity.warnings.length ? `；${result.fidelity.warnings.join('；')}` : ''}`);
}
$('exportMarkdown').onclick = () => exportCurrentDocument('markdown').catch((error)=>notice(error.message,true));
$('exportDocx').onclick = () => exportCurrentDocument('docx').catch((error)=>notice(error.message,true));
$('openInWord').onclick=()=>nativeInvoke('open_in_word',{path:state.lastDocxExport}).then(()=>notice('已经把这一精确导出版本交给 Microsoft Word；保存后可用“导回 Word 修改稿”。')).catch((error)=>notice(error.message,true));
$('reimportWord').onclick=async()=>{
  if(!state.manuscriptId){notice('请先选择要接收 Word 修改稿的稿件。',true);return;}
  try{
    const path=await nativeInvoke('choose_file',{kind:'docx'});if(!path)return;
    const result=await request('/api/desktop/import-path',localSessionOptions({kind:'docx',path,manuscript_id:state.manuscriptId}));
    state.document=result;state.documentManuscriptId=state.manuscriptId;state.sectionId=result.document.children[0]?.section_id||'';
    await refreshAuthoring(`Word 修改稿已导回为新修订。保真提示：${result.import_fidelity.warnings.join('；')}`);
  }catch(error){notice(error.message,true);}
};
$('insertNote').onclick = () => { currentSelectionContext(); state.authoringMode='notes'; renderAuthoringControl(selectedSection(),null); };
for (const button of document.querySelectorAll('[data-command]')) button.onclick = () => document.execCommand(button.dataset.command, false);
$('paragraphButton').onclick = () => document.execCommand('formatBlock', false, 'p');
$('quoteButton').onclick = () => document.execCommand('formatBlock', false, 'blockquote');
$('documentCanvas').onmouseup = currentSelectionContext;
$('documentCanvas').onkeyup = currentSelectionContext;
$('contextTabs').onclick = (event) => {
  const button = event.target.closest('button[data-context]');
  if (!button) return; state.contextMode = button.dataset.context; renderContext();
};
$('projectSelect').onchange = async (event) => {
  try {
    await request('/api/project/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_id:event.target.value})});
    state.threadId = ''; state.thread = null; state.view = null; state.libraryWork = null; state.libraryWorkId = ''; state.manuscriptId=''; state.sectionId='';
    await loadSnapshot(); setMode('agent'); notice('已切换项目；对话和研究对象按项目隔离。');
  } catch (error) { notice(error.message, true); }
};
$('newProject').onclick = async () => {
  const title = window.prompt('新项目名称', '新的历史研究项目'); if (!title?.trim()) return;
  try {
    await request('/api/project/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    state.threadId = ''; state.thread = null; state.view = null; state.libraryWork = null; state.libraryWorkId = ''; state.manuscriptId=''; state.sectionId='';
    await loadSnapshot(); setMode('agent'); notice('新项目已建立，可以从图书馆加入材料。');
  } catch (error) { notice(error.message, true); }
};
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
$('chooseFolder').onclick=async()=>{try{const path=await nativeInvoke('choose_folder');if(path)$('scanRoot').value=path;}catch(error){notice(error.message,true);}};
$('choosePdf').onclick=async()=>{
  try{
    const path=await nativeInvoke('choose_file',{kind:'pdf'});if(!path)return;
    notice('正在复制原 PDF、渲染页面并检查文本层……');
    const result=await request('/api/desktop/import-path',localSessionOptions({kind:'pdf',path}));
    await loadSnapshot(result.source.source_id);setMode('library');notice(`已导入 ${result.intake.page_count} 页；原文件没有被修改。`);
  }catch(error){notice(error.message,true);}
};
$('chooseDocx').onclick=async()=>{
  try{
    const path=await nativeInvoke('choose_file',{kind:'docx'});if(!path)return;
    const result=await request('/api/desktop/import-path',localSessionOptions({kind:'docx',path,title:$('manuscriptTitle').value}));
    state.manuscriptId=result.manuscript_id;state.sectionId=result.document.children[0]?.section_id||'';state.document=result;state.documentManuscriptId=result.manuscript_id;
    await refreshAuthoring(`DOCX 已导入。保真提示：${result.import_fidelity.warnings.join('；')}`);
  }catch(error){notice(error.message,true);}
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
    await loadSnapshot(result.source.source_id); setMode('library'); notice(`已作为项目私有材料导入 ${result.intake.page_count} 页；发现 ${result.intake.anomaly_count || 0} 个待复核项，可在“当前项目文献”打开原页复核。`);
  } catch (error) { notice(error.message, true); }
};

$('loadBrowser').onclick = () => {
  const url = $('browserAddress').value.trim(); try { new URL(url); } catch { notice('请输入完整的网址。', true); return; }
  $('researchFrame').src = url; renderBrowserControls(); notice('正在中央研究浏览器中打开；若站点拒绝嵌入，请使用系统浏览器。');
};
$('externalBrowser').onclick = () => { const url=$('browserAddress').value.trim(); try { new URL(url); window.open(url,'_blank','noopener'); } catch { notice('请输入完整的网址。',true); } };

const initialMode = new URLSearchParams(window.location.search).get('mode');
setMode(['agent', 'article', 'library', 'settings', 'browser', 'source'].includes(initialMode) ? initialMode : 'agent');
loadSnapshot().then(() => notice('对话工作台已就绪。')).catch((error) => notice(error.message, true));
