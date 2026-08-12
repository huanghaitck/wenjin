const state = {
  snapshot: null, capabilities: null, view: null, thread: null, threadId: '', pageIndex: 0, zoom: 1,
  libraryScan: null, libraryWorks: [], libraryWork: null, libraryWorkId: '',
  contextMode: 'sources', retrievalRecord: null,
  manuscriptId: sessionStorage.getItem('hrwManuscriptId') || '',
  sectionId: sessionStorage.getItem('hrwSectionId') || '', authoringMode: 'dialogue', proposalId: '',
  document: null, documentManuscriptId: '', selection: null, browserSession: null,
  modelSettings: null, sessionToken: '', lastDocxExport: '', nativeBridge: '',
  eventFreezeDraft: [],
  planningMode: sessionStorage.getItem('hrwPlanningMode') || 'independent_planning',
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

function clearReviewReason() {
  $('reason').value = '';
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
  renderSkillCatalog();
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
  const shelfSelect=$('libraryShelf');const selectedShelf=shelfSelect.value;shelfSelect.replaceChildren(new Option('全部书架',''));
  for(const [value,label] of Object.entries(state.snapshot.library_shelves||{})) shelfSelect.append(new Option(label,value));
  shelfSelect.value=selectedShelf;
  const skills = $('intakeSkill'); skills.replaceChildren();
  for (const skill of (library?.skills || []).filter((item)=>item.compatible_actions?.includes('library_intake'))) {
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
  const visible=state.libraryWorks.filter((work)=>!$('libraryShelf').value||work.shelf===$('libraryShelf').value);
  if (!visible.length) {
    list.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'图书馆还没有已批准材料。盘点不会自动入库。'})); return;
  }
  for (const work of visible) {
    const button = document.createElement('button'); button.className = 'work-row';
    button.classList.toggle('selected', work.work_id === state.libraryWorkId);
    const title = document.createElement('strong'); title.textContent = work.canonical_title;
    const author = document.createElement('span'); author.textContent = work.author || '作者待核';
    const meta = document.createElement('small'); meta.textContent = `${work.shelf_label} · ${work.material_type} · ${work.file_count} 个位置 · ${work.version_count} 个版本`;
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
  const shelfLabel=document.createElement('label');shelfLabel.textContent='书架（人工移动，不改变引用资格）';
  const shelf=document.createElement('select');shelf.id='workShelf';
  for(const [value,name] of Object.entries(state.snapshot.library_shelves||{})) shelf.append(new Option(name,value));
  shelf.value=work.shelf||'unclassified';shelfLabel.append(shelf);
  form.append(
    shelfLabel,
    detailField('作品题名', work.canonical_title, 'canonical_title'),
    detailField('作者 / 责任者', work.author, 'author'),
    detailField('语言', work.language, 'language'),
    detailField('材料类型', work.material_type, 'material_type'),
    detailField('版本说明', edition.edition_label, 'edition_label'),
    detailField('出版者', edition.publisher, 'publisher'),
    detailField('出版年', edition.publication_year, 'publication_year'),
    detailField('ISBN', edition.isbn, 'isbn'),
    detailField('用户标签（逗号分隔）', work.tags.filter((item) => item.origin === 'user'&&!item.name.startsWith('shelf:')).map((item) => item.name).join(', '), 'tags'),
  );
  const actions = document.createElement('div'); actions.className = 'detail-actions';
  const move=document.createElement('button');move.textContent='移动到所选书架';
  move.onclick=async()=>{try{state.libraryWork=await request('/api/library/work/shelf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_id:work.work_id,shelf:shelf.value})});await refreshLibrary();notice('书架已更新；原文件位置和研究资格均未改变。');}catch(error){notice(error.message,true);}};
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
  actions.append(move, save, link); form.append(actions); container.append(form);

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
  $('planningMode').value = state.planningMode;
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
  const historyCount=run?.model_snapshot?.history_message_ids?.length||0;
  const toolFailureCount = run?.tool_calls?.filter((call) => call.status === 'FAILED').length || 0;
  const outcome = run?.status === 'FAILED' && run.error
    ? ` · 原因：${run.error}`
    : run?.status === 'COMPLETED' && toolFailureCount
      ? ` · 本轮记录 ${toolFailureCount} 次工具错误`
      : '';
  $('runState').textContent = run ? `${run.status} · ${run.model_snapshot.provider} / ${run.model_snapshot.model} · ${run.model_snapshot.planning_mode === 'independent_planning' ? '独立构思（不带旧对话）' : `按计划执行 · 沿用${historyCount}条历史${run.model_snapshot.history_truncated?'（已裁剪）':''}`}${outcome}` : '对话与运行状态会保存在本地项目中';
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

function journalTemplateLabel(item) {
  const name=item.origin==='user'&&item.name==='《唐都学刊》'?'《唐都学刊》（旧人工模板）':item.name;
  return `${name} · ${item.version_label||'人工模板'}`;
}

function renderResearchDesign(container) {
  const design = state.snapshot.research_design || {versions:[]};
  const baseline = design.researcher_baseline;
  const shared = design.shared_design;
  const summary = document.createElement('section'); summary.className = 'context-form';
  summary.append(
    card('研究者意图基线（不向独立构思 Agent 提供）', baseline
      ? `${baseline.title} · ${baseline.design_id}。这是研究者已外化、可修订的研究认知轨迹，不是心理画像或来源证据。`
      : '尚未批准。可从旧对话恢复研究方向，但须区分原话、复原和推断待确认。'),
    card('共同批准研究设计（执行时加载）', shared
      ? `${shared.title} · ${shared.design_id}。这是人机讨论后由研究者批准的可执行版本。`
      : '尚未批准。研究者意图不会自动变成共同研究设计。'),
  );
  container.append(summary);

  const form = document.createElement('section'); form.className = 'context-form';
  const role = document.createElement('select'); role.id = 'designRole';
  role.append(new Option('研究者意图基线（隐藏）','researcher_baseline'), new Option('共同研究设计','shared_design'));
  const roleLabel = document.createElement('label'); roleLabel.textContent = '计划角色'; roleLabel.append(role);
  const title = formField('标题', 'designTitle');
  const content = formField('计划正文（可粘贴 Markdown / 纯文本）', 'designContent', '', true);
  const file = document.createElement('input'); file.type='file'; file.accept='.md,.txt,text/plain,text/markdown';
  const fileLabel = document.createElement('label'); fileLabel.textContent='或导入文本计划'; fileLabel.append(file);
  file.onchange = async () => {
    const selected=file.files[0]; if(!selected)return;
    $('designContent').value=await selected.text();
    if(!$('designTitle').value.trim())$('designTitle').value=selected.name.replace(/\.(md|txt)$/i,'');
  };
  form.append(roleLabel, title, content, fileLabel, actionButton('保存为待审草案', async () => {
    await request('/api/research-design/draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      title:$('designTitle').value,content:$('designContent').value,plan_role:role.value,
      origin:file.files[0]?'imported':'manual',created_by:'Professor',
      base_design_id:role.value==='researcher_baseline'?(baseline?.design_id||''):(shared?.design_id||''),
    })});
    await refreshResearch('研究计划草案已保存；尚未改变任何批准版本。'); state.contextMode='design'; renderContext();
  }, true));
  container.append(form);

  for (const item of design.versions || []) {
    const node=card(`${item.plan_role === 'researcher_baseline' ? '研究者意图基线' : '共同研究设计'} · ${item.title}`,
      `${item.status} · ${item.origin} · ${item.design_id} · ${new Date(item.created_at).toLocaleString()}`);
    const text=document.createElement('textarea'); text.value=item.content; text.readOnly=item.status!=='draft'; node.append(text);
    if(item.change_summary)node.append(Object.assign(document.createElement('small'),{textContent:`变更摘要：${item.change_summary}`}));
    if(item.status==='draft'){
      const decide=async(approved)=>{
        const reviewer=window.prompt('决定人','Professor'); if(!reviewer)return;
        const reason=window.prompt(approved?'批准依据':'拒绝依据','与研究者当前判断核对'); if(!reason)return;
        await request('/api/research-design/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          design_id:item.design_id,approved,reviewer,reason,title:item.title,content:text.value,
        })});
        await refreshResearch(approved?'新计划版本已人工批准；旧批准版仍保留。':'草案已拒绝；当前批准版未改变。');
        state.contextMode='design'; renderContext();
      };
      node.append(actionButton('修改后批准',()=>decide(true),true),actionButton('拒绝',()=>decide(false)));
    } else if(item.decision_reason) {
      node.append(Object.assign(document.createElement('small'),{textContent:`人工决定：${item.decided_by}｜${item.decision_reason}`}));
    }
    container.append(node);
  }
}

function renderResearchEvents(container) {
  const stateValue=state.snapshot.research_events||{events:[],counts:{}};
  container.append(card('逐事件比较表',
    `待核 ${stateValue.counts.draft||0} · 已批准 ${stateValue.counts.approved||0} · 已拒绝 ${stateValue.counts.rejected||0}。批准事件仍不是冻结证据。`));
  container.append(actionButton('导出已批准事件清单',async()=>{
    const result=await request('/api/research-events/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({statuses:['approved']})});
    notice(`已导出 ${result.row_count} 项事件：${result.native_path||result.project_path}`);
  },true));
  if(!stateValue.events.length){container.append(card('尚无事件候选','在研究对话中让 Agent 定位来源页并提交 research_event.propose_batch。'));return;}
  const labels={case_id:'比较个案',event_date:'日期',start_place:'起点',end_place:'行程终点',route:'路线/通道',movement_time:'移动时间',distance_original:'原载距离',distance_normalized:'换算',movement_mode:'移动方式',investigation_object:'调查对象',recording_technique:'记录技术',genre:'体裁',chinese_participants:'中国参与者',participant_visibility:'参与者可见度',institutional_task:'机构任务',outcome_destination:'成果/知识产出去向（非行程终点）',translation:'译文',missing_reason:'缺失原因',notes:'备注'};
  const sourceFields=new Set(['event_date','start_place','end_place','route','movement_time','distance_original','movement_mode','investigation_object','recording_technique','genre','chinese_participants','participant_visibility','institutional_task','outcome_destination','translation','original_text']);
  for(const item of stateValue.events){
    const node=card(`${item.case_id} · ${item.event_date||'日期待核'}`,`${item.status} · 物理页 ${(item.physical_pages||[]).join('–')||'待核'} · ${item.event_id}`);
    const editors={};const anchorEditors={};
    for(const [key,label] of Object.entries(labels)){
      const wrapper=document.createElement('label');wrapper.textContent=label;
      const input=document.createElement(['translation','notes'].includes(key)?'textarea':'input');input.value=item[key]||'';input.readOnly=item.status==='rejected';editors[key]=input;wrapper.append(input);node.append(wrapper);
      const anchors=item.field_anchors?.[key]||[];
      if(item.status!=='rejected'&&sourceFields.has(key)){
        const anchorLabel=document.createElement('label');anchorLabel.textContent='字段锚点（逗号分隔）';
        const anchorInput=document.createElement('input');anchorInput.value=anchors.join(', ');anchorEditors[key]=anchorInput;anchorLabel.append(anchorInput);node.append(anchorLabel);
      }else if(anchors.length)node.append(Object.assign(document.createElement('small'),{textContent:`字段锚点：${anchors.join('、')}`}));
    }
    const quoteLabel=document.createElement('label');quoteLabel.textContent='原文（必须逐字存在于所引文本块）';
    const quote=document.createElement('textarea');quote.value=item.original_text;quote.readOnly=item.status==='rejected';editors.original_text=quote;quoteLabel.append(quote);node.append(quoteLabel);
    const quoteAnchors=item.field_anchors?.original_text||[];
    if(item.status!=='rejected'){
      const anchorLabel=document.createElement('label');anchorLabel.textContent='原文锚点（逗号分隔）';
      const anchorInput=document.createElement('input');anchorInput.value=quoteAnchors.join(', ');anchorEditors.original_text=anchorInput;anchorLabel.append(anchorInput);node.append(anchorLabel);
    }else if(quoteAnchors.length)node.append(Object.assign(document.createElement('small'),{textContent:`原文锚点：${quoteAnchors.join('、')}`}));
    node.append(Object.assign(document.createElement('small'),{textContent:`来源 ${item.source_id} · 版本 ${item.source_version_id} · Blocks ${item.block_ids.join('、')} · ${item.qualification}`}));
    node.append(actionButton('打开原页并人工核对',async()=>{await loadSource(item.source_id);const pageId=item.page_ids?.[0];const index=state.view.pages.findIndex((page)=>page.page_id===pageId);if(index>=0)state.pageIndex=index;setMode('source');render();notice('请对照原图核验并确认候选引用的文本块；返回逐事件表后再批准。');}));
    if(item.status==='draft'){
      node.append(actionButton('按当前已核锚块刷新原文',async()=>{const current=await request(`/api/research-event/anchor-text?id=${encodeURIComponent(item.event_id)}`);quote.value=current.original_text;notice(current.changed?'已把当前锚块文本回填到审批表单；尚未保存或批准。':'锚块文本与候选原文一致。');}));
      const decide=async(approved)=>{const reviewer=window.prompt('决定人','Professor');if(!reviewer)return;const reason=window.prompt(approved?'批准依据':'拒绝依据',approved?'已核原页与事件编码':'候选不符合比较口径');if(!reason)return;const edits=Object.fromEntries(Object.entries(editors).map(([key,input])=>[key,input.value]));const field_anchors=Object.fromEntries(Object.entries(anchorEditors).map(([key,input])=>[key,input.value.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean)]));await request('/api/research-event/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_id:item.event_id,approved,reviewer,reason,edits,field_anchors:approved?field_anchors:undefined})});await refreshResearch(approved?'事件行已人工批准；仍须另建主张和冻结证据。':'事件候选已拒绝，记录保留。');state.contextMode='events';renderContext();};
      node.append(actionButton('核页后批准',()=>decide(true),true),actionButton('拒绝候选',()=>decide(false)));
    } else if(item.status==='approved'){
      const revise=async()=>{const reviewer=window.prompt('修订人','Professor');if(!reviewer)return;const reason=window.prompt('修订依据','根据已核原页补齐比较字段');if(!reason)return;const edits=Object.fromEntries(Object.entries(editors).map(([key,input])=>[key,input.value]));const field_anchors=Object.fromEntries(Object.entries(anchorEditors).map(([key,input])=>[key,input.value.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean)]));await request('/api/research-event/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_id:item.event_id,approved:true,reviewer,reason,edits,field_anchors})});await refreshResearch('已批准事件的人工修订已保存；原决定与差异保留在审计记录中。');state.contextMode='events';renderContext();};
      node.append(actionButton('保存人工修订',()=>revise(),true));
      if(item.decision_reason)node.append(Object.assign(document.createElement('small'),{textContent:`最近人工决定：${item.decided_by}｜${item.decision_reason}`}));
    } else if(item.decision_reason){node.append(Object.assign(document.createElement('small'),{textContent:`人工决定：${item.decided_by}｜${item.decision_reason}`}));}
    container.append(node);
  }
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
      node.append(chip);
      if (source.original_name.toLowerCase().endsWith('.docx') && source.page_count === 0 && source.byte_count > 0) {
        node.append(actionButton('生成译稿定位文本', async () => {
          const result = await request('/api/source/ingest-docx-locator', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_id:source.source_id})});
          await refreshResearch(`译稿已建立 ${result.segment_count} 个逻辑片段；只能用于定位，不能直接建证。`);
          await loadSource(source.source_id); setMode('source');
        }, true));
      } else if (source.page_count > 0) {
        node.append(actionButton(source.use_state === 'locator_only' ? '查看定位文本' : '查看原页与文本', async () => { await loadSource(source.source_id); setMode('source'); }));
      } else {
        const unavailable = actionButton('清洗未完成，暂无页面', () => {}); unavailable.disabled = true; node.append(unavailable);
      }
      if (source.use_state !== 'blocked' || source.processing_state !== 'error') {
        node.append(actionButton('标记整份文件不符', async () => {
          const reviewer = window.prompt('复核人', 'Professor'); if (!reviewer) return;
          const reason = window.prompt('文件身份为何不符？'); if (!reason) return;
          await request('/api/source/reject-identity', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_id:source.source_id, reviewer, reason})});
          await refreshResearch('整份文件已阻断；原文件和审计记录保留。'); state.contextMode='sources'; renderContext();
        }));
      }
      container.append(node);
    }
    if (!state.snapshot.sources.length) container.append(card('项目还没有文献', '从图书馆加入书籍，或在顶部导入 PDF。'));
  } else if (state.contextMode === 'library') {
    for (const work of state.libraryWorks || []) {
      const node = card(work.canonical_title, `${work.author || '责任者待核'} · ${work.version_count} 个精确版本`);
      node.append(actionButton('选择版本并加入项目', async () => {
        const detail = await request(`/api/library/work?id=${encodeURIComponent(work.work_id)}`);
        const file = detail.files.find((item) => item.file_state === 'matches_registered_version' && /\.(pdf|docx)$/i.test(item.path));
        if (!file) throw new Error('这部作品当前没有可用的已登记 PDF 或 DOCX 版本。');
        await addLibraryFile(work.work_id, file.file_id);
      }, true)); container.append(node);
    }
  } else if (state.contextMode === 'design') {
    renderResearchDesign(container);
  } else if (state.contextMode === 'events') {
    renderResearchEvents(container);
  } else if (state.contextMode === 'retrieval') {
    container.append(card('已登录学术数据库', '知网、读秀和学校数据库通过用户可见的浏览器会话工作：程序保存检索式、题录和下载回执；验证码、授权提示与下载确认由研究者处理。'));
    const form = document.createElement('section'); form.className = 'context-form';
    const provider = document.createElement('select'); provider.id = 'researchProvider';
    for (const item of state.capabilities?.research_connectors || []) {
      if (item.mode === 'user_visible_session') continue;
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
      const routeLabels = {project_candidate:'拟纳入项目', fulltext_queue:'待读全文', metadata_only:'仅题录', duplicate:'重复版本', inaccessible:'无权访问', excluded:'排除'};
      const routeDetail = item.route ? ` · ${routeLabels[item.route]}（${item.route_reason}）` : ' · 尚未分流';
      const node = card(item.title || '无题名', `${item.authors || '作者待核'} · ${item.publication_year || '年代待核'} · ${item.qualification}${routeDetail}`);
      if (item.url) { const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.textContent = '打开来源页'; node.append(link); }
      const routing = document.createElement('div'); routing.className = 'context-form';
      const select = document.createElement('select');
      for (const [value,label] of Object.entries(routeLabels)) select.append(new Option(label,value));
      select.value = item.route || 'fulltext_queue';
      const reason = document.createElement('input'); reason.placeholder = '分流依据（必填）'; reason.value = item.route_reason || '';
      routing.append(select, reason, actionButton('保存人工分流', async () => {
        const decidedBy = window.prompt('决定人', item.route_decided_by || 'Professor'); if (!decidedBy) return;
        if (!reason.value.trim()) throw new Error('请填写分流依据。');
        state.retrievalRecord = await request('/api/research/result/route', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({result_id:item.result_id, route:select.value, reason:reason.value, decided_by:decidedBy})});
        renderContext(); notice('检索线索已分流；这不会自动提升其来源资格。');
      }, true));
      node.append(routing);
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
        evidenceForm.id = `evidence-form-${claim.claim_id}`;
        const humanStates = new Set(['human_verified', 'human_repaired']);
        const decorativeTypes = new Set(['header', 'footer', 'page_number']);
        const blocks = state.view.pages.flatMap((page) => page.blocks.map((block) => ({page, block}))).filter((item) =>
          item.block.use_state === 'research_usable' && item.page.use_state === 'research_usable'
          && humanStates.has(item.block.verification_state) && !decorativeTypes.has(item.block.block_type));
        const select = document.createElement('select'); select.dataset.role = 'evidence-block'; select.id = `evidence-block-${claim.claim_id}`;
        const endSelect = document.createElement('select'); endSelect.dataset.role = 'evidence-block-end'; endSelect.id = `evidence-block-end-${claim.claim_id}`;
        for (const item of blocks) {
          const label = `物理页 ${item.page.physical_page}${item.page.printed_page ? ` / 印刷页 ${item.page.printed_page}` : ''} · ${item.block.verification_state} · ${item.block.effective_text.slice(0,42)}`;
          select.append(new Option(label, item.block.block_id)); endSelect.append(new Option(label, item.block.block_id));
        }
        const quote = document.createElement('textarea'); quote.id = `evidence-quote-${claim.claim_id}`; quote.placeholder = '粘贴所选已核块中的原文；必须逐字存在';
        const note = document.createElement('input'); note.id = `evidence-note-${claim.claim_id}`; note.placeholder = '为何与主张有关';
        const relation = document.createElement('select'); relation.id = `evidence-relation-${claim.claim_id}`; for (const value of ['supports','weakens','background','counterevidence']) relation.append(new Option(value, value));
        const spanBlocks = () => {
          const start = blocks.findIndex((item) => item.block.block_id === select.value);
          const end = blocks.findIndex((item) => item.block.block_id === endSelect.value);
          if (start < 0 || end < start) throw new Error('结束段必须位于起始段之后。');
          return blocks.slice(start, end + 1);
        };
        const fillSpanQuote = () => { try { quote.value = spanBlocks().map((item) => item.block.effective_text).join('\n'); } catch (_) {} };
        select.onchange = () => { endSelect.value = select.value; fillSpanQuote(); };
        endSelect.onchange = fillSpanQuote;
        if (blocks.length) { endSelect.value = select.value; fillSpanQuote(); }
        if (!blocks.length) evidenceForm.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'当前打开来源还没有人工核验的文本块。请先在原页界面逐段核验。'}));
        const submitEvidence = actionButton('人工提交证据', async () => {
          if (!select.value) throw new Error('请先选择一个人工核验的页面块。');
          const selected = spanBlocks();
          await request('/api/evidence/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({claim_id:claim.claim_id, block_id:select.value, block_ids:selected.map((item)=>item.block.block_id), quote:quote.value, note:note.value, relation:relation.value})});
          await refreshResearch('证据已固定到精确页面块和来源版本。');
        }, true); submitEvidence.id = `evidence-submit-${claim.claim_id}`;
        const startLabel=document.createElement('label'); startLabel.textContent='证据起始段'; startLabel.append(select);
        const endLabel=document.createElement('label'); endLabel.textContent='证据结束段（单段时与起始段相同）'; endLabel.append(endSelect);
        evidenceForm.append(startLabel, endLabel, quote, note, relation, submitEvidence); node.append(evidenceForm);
      }
      for (const evidence of claim.evidence) {
        node.append(Object.assign(document.createElement('p'), {textContent:`${evidence.relation} · 物理页 ${(evidence.physical_pages || [evidence.physical_page]).join('–')} · “${evidence.quote}”`}));
        const translate = actionButton(translation?.available ? '调用翻译搭档' : '翻译搭档未配置', async () => {
          await request('/api/translation/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({evidence_id:evidence.evidence_id, target_language:'Chinese'})});
          await refreshResearch('译文已保存为派生稿，原文和页面锚点未改变。');
        }); translate.disabled = !translation?.available; node.append(translate);
      }
      container.append(node);
    }
  } else if (state.contextMode === 'writing') {
    const claims = research.claims || [];
    const approvedEvents = (state.snapshot.research_events?.events || []).filter((item) => item.status === 'approved');
    const eventForm = document.createElement('section'); eventForm.className = 'context-form';
    eventForm.append(
      Object.assign(document.createElement('h3'), {textContent:'逐事件表正式冻结'}),
      Object.assign(document.createElement('p'), {className:'boundary-note', textContent:'只接受已人工批准、保留原页锚点的事件；待核和已拒绝事件不能进入冻结包。'}),
      formField('冻结包标题', 'eventFreezeTitle', '秦岭三案比较正式证据包（1871—1875）'),
      formField('最低可写主张', 'eventFreezeClaim', '', true),
      formField('不能支持的强说法', 'eventFreezeLimit', '', true),
    );
    const eventSelect = document.createElement('select'); eventSelect.id = 'eventFreezeEvents'; eventSelect.multiple = true; eventSelect.size = 9;
    for (const item of approvedEvents) {
      const summary = item.route || item.investigation_object || item.institutional_task || item.outcome_destination || item.notes;
      eventSelect.append(new Option(`${item.case_id} · ${item.event_date || '日期待核'} · ${item.event_id} · ${String(summary).slice(0,62)}`, item.event_id));
    }
    const eventLabel = document.createElement('label'); eventLabel.textContent = '支持该主张的已批准事件（可多选）'; eventLabel.append(eventSelect);
    const relation = document.createElement('select'); relation.id = 'eventFreezeRelation';
    for (const value of ['supports','background','counterevidence','weakens']) relation.append(new Option(value, value));
    const relationLabel = document.createElement('label'); relationLabel.textContent = '证据关系'; relationLabel.append(relation);
    const draftList = document.createElement('div'); draftList.className = 'event-freeze-draft';
    const renderEventDraft = () => {
      draftList.replaceChildren();
      for (const [index, item] of state.eventFreezeDraft.entries()) {
        const draft = card(item.text, `${item.evidence.length} 条事件证据 · ${item.evidence[0]?.relation || 'supports'}`);
        if (item.does_not_support) draft.append(Object.assign(document.createElement('small'), {textContent:`禁写边界：${item.does_not_support}`}));
        draft.append(actionButton('从草案移除', () => { state.eventFreezeDraft.splice(index, 1); renderEventDraft(); }));
        draftList.append(draft);
      }
    };
    const addClaim = actionButton('加入冻结草案', () => {
      const text = $('eventFreezeClaim').value.trim();
      const eventIds = [...eventSelect.selectedOptions].map((option) => option.value);
      if (!text || !eventIds.length) throw new Error('请填写主张并至少选择一条已批准事件。');
      state.eventFreezeDraft.push({
        text,
        does_not_support: $('eventFreezeLimit').value.trim(),
        evidence: eventIds.map((event_id) => ({event_id, relation: relation.value})),
      });
      $('eventFreezeClaim').value = ''; $('eventFreezeLimit').value = '';
      for (const option of eventSelect.options) option.selected = false;
      renderEventDraft();
    }, true);
    eventForm.append(
      eventLabel, relationLabel, addClaim, draftList,
      formField('未决项（每行一项）', 'eventFreezeUnresolved', '', true),
      formField('禁止主张（每行一项）', 'eventFreezeProhibited', '', true),
      actionButton('创建待批准的逐事件冻结包', async () => {
        if (!state.eventFreezeDraft.length) throw new Error('冻结草案中还没有主张。');
        const lines = (id) => $(id).value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
        await request('/api/freeze/events/create', {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
            title:$('eventFreezeTitle').value,
            claims:state.eventFreezeDraft,
            unresolved:lines('eventFreezeUnresolved'),
            prohibited_claims:lines('eventFreezeProhibited'),
          }),
        });
        state.eventFreezeDraft = [];
        await refreshResearch('逐事件冻结包已创建，仍需教授人工批准。');
      }, true),
    );
    renderEventDraft(); container.append(eventForm);

    const form = document.createElement('section'); form.className = 'context-form'; form.append(formField('冻结包标题', 'freezeTitle', '试写证据包'));
    for (const claim of claims) { const label = document.createElement('label'); const check = document.createElement('input'); check.type='checkbox'; check.value=claim.claim_id; check.disabled=!claim.evidence.length; label.append(check, document.createTextNode(claim.text)); form.append(label); }
    form.append(actionButton('创建待批准冻结包', async () => {
      const claim_ids = [...form.querySelectorAll('input[type=checkbox]:checked')].map((item)=>item.value);
      await request('/api/freeze/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('freezeTitle').value, claim_ids})}); await refreshResearch('冻结包已创建，等待教授批准。');
    }, true)); container.append(form);
    for (const freeze of research.freezes || []) {
      const node = card(freeze.title, `${freeze.payload.claims.length} 个主张 · ${freeze.status}`);
      node.append(Object.assign(document.createElement('p'), {className:'boundary-note', textContent:`冻结边界：${freeze.payload.boundary}`}));
      if (freeze.payload.classifications) {
        const groups = freeze.payload.classifications;
        node.append(Object.assign(document.createElement('small'), {textContent:
          `逐事件冻结｜可写 ${groups.FROZEN_WRITABLE?.length || 0} · 语境 ${groups.CONTEXT_ONLY?.length || 0} · 反证 ${groups.COUNTEREVIDENCE?.length || 0} · 未决 ${groups.UNRESOLVED?.length || 0} · 禁止主张 ${groups.PROHIBITED_CLAIM?.length || 0}`}));
      }
      for (const claim of freeze.payload.claims) {
        const counters = claim.evidence.filter((item) => ['weakens', 'counterevidence'].includes(item.relation)).length;
        node.append(Object.assign(document.createElement('small'), {textContent:`${claim.evidence.length} 条证据${counters ? ` · ${counters} 条削弱/反证` : ''}｜${claim.text}`}));
      }
      if (freeze.status === 'pending') {
        const approval = document.createElement('section'); approval.className = 'context-form';
        const reviewer = document.createElement('input'); reviewer.value = 'human-reviewer'; reviewer.placeholder = '决定人';
        const reason = document.createElement('textarea'); reason.placeholder = '批准依据与禁止越界的说明';
        approval.append(reviewer, reason, actionButton('人工批准冻结', async () => {
          if (!reviewer.value.trim() || !reason.value.trim()) throw new Error('请填写决定人和批准依据。');
          await request('/api/freeze/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({freeze_id:freeze.freeze_id, reviewer:reviewer.value, reason:reason.value})});
          await refreshResearch('冻结包已人工批准，决定人与依据已写入冻结记录。');
        }, true)); node.append(approval);
      }
      if (freeze.status === 'approved') node.append(actionButton('由冻结证据生成试写', async () => { await request('/api/draft/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({freeze_id:freeze.freeze_id, title:freeze.title})}); await refreshResearch('可追溯试写已生成。'); }, true));
      container.append(node);
    }
    for (const artifact of research.artifacts || []) {
      const version = artifact.versions[0]; const node = card(artifact.title, `${artifact.artifact_type} · ${version.version_id}`);
      const pre = document.createElement('pre'); pre.textContent = version.content; node.append(pre);
      node.append(actionButton('来源批判评审', async () => { const result = await request('/api/review/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({version_id:version.version_id})}); await refreshResearch(result.report); }));
      node.append(actionButton('进入文章工作台', async () => { const result=await request('/api/manuscript/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:artifact.title,markdown:version.content})});state.manuscriptId=result.manuscript_id;state.sectionId=result.sections[0]?.section_id||'';state.proposalId='';setMode('article');await refreshAuthoring('冻结试写已转为结构化稿件，原始试写仍保留。'); }, true));
      node.append(actionButton('导出 Markdown', async () => { const result = await request('/api/artifact/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({artifact_id:artifact.artifact_id})}); notice(`已导出：${result.project_path}`); })); container.append(node);
    }
  } else if (state.contextMode === 'browser') {
    const form = document.createElement('section'); form.className = 'context-form';
    form.append(formField('起始网址', 'browserUrl', 'https://www.crossref.org/'), formField('允许域名', 'browserDomain', 'crossref.org'));
    form.append(actionButton('进入中央研究浏览器', async () => { state.browserSession = await request('/api/browser/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({start_url:$('browserUrl').value, allowed_domain:$('browserDomain').value})}); $('browserAddress').value=state.browserSession.start_url; await refreshResearch('研究浏览会话回执已保存；登录和下载仍由你决定。'); setMode('browser'); $('researchFrame').src=state.browserSession.start_url; }, true)); container.append(form);
    container.append(card('浏览器边界', '网页占据中央区域；只记录允许域名、起始页和操作回执，不读取 Cookie，不代替你登录、过验证码、付费或提交。'));
    for (const session of research.browser_sessions || []) container.append(card(session.allowed_domain, `${session.start_url} · ${session.status}`));
  } else if (state.contextMode === 'memory') {
    container.append(card('四层分开，不自动沉淀',
      '研究图书馆保存原文件与版本；项目知识保存研究设计、逐事件表、证据冻结和稿件；对话、检索和工具记录只属于工作过程；长期记忆先在本项目生成带来源候选。即使候选获准保留，也不会自动写入外部长期记忆库。'));
    const form = document.createElement('section'); form.className = 'context-form';
    form.append(formField('类别', 'memoryCategory', '研究判断'), formField('候选内容', 'memoryContent', '', true), formField('稳定来源 ID（必填，逗号分隔）', 'memoryRefs'));
    form.append(actionButton('保存为记忆候选', async () => { await request('/api/memory/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({category:$('memoryCategory').value, content:$('memoryContent').value, source_refs:$('memoryRefs').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})}); await refreshResearch('只保存为项目内候选，尚未写入长期记忆库。'); }, true)); container.append(form);
    for (const item of research.memory_candidates || []) { const node = card(item.category, `${item.content}\n来源：${item.source_refs.join('、')} · ${item.status}`); if(item.status==='candidate') node.append(actionButton('批准留在本项目候选区', async()=>{await request('/api/memory/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:item.candidate_id,approved:true})}); await refreshResearch('候选已批准留在本项目；仍未同步到任何外部长期记忆库。');},true)); container.append(node); }
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
    if (node.type === 'table') {
      const table=document.createElement('table');table.dataset.nodeId=node.node_id;table.dataset.nodeType='table';
      const body=document.createElement('tbody');
      for (const [rowIndex,row] of (node.rows||[]).entries()) {
        const tr=document.createElement('tr');
        for (const value of row) {
          const cell=document.createElement(rowIndex===0?'th':'td');cell.textContent=value;tr.append(cell);
        }
        body.append(tr);
      }
      table.append(body);canvas.append(table);continue;
    }
    const element = document.createElement(node.type === 'quote' ? 'blockquote' : (node.type === 'subheading' ? 'h3' : 'p'));
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
  const manuscriptTitle=$('manuscriptTitleEdit').value.trim();
  if(!manuscriptTitle) throw new Error('稿件题名不能为空。');
  state.document.document.title=manuscriptTitle;
  const heading=$('sectionHeading').innerText.trim();
  if(!heading) throw new Error('章节标题不能为空。');
  section.heading=heading;
  for (const child of [...$('documentCanvas').childNodes]) {
    if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim()) continue;
    const paragraph=document.createElement('p');paragraph.textContent=child.textContent;
    $('documentCanvas').replaceChild(paragraph,child);
  }
  section.children = [...$('documentCanvas').children].filter((node) => node.matches('p, blockquote, li, h3, table')).map((node) => {
    if (node.tagName === 'TABLE') return {
      type:'table',node_id:node.dataset.nodeId||`NOD_${crypto.randomUUID().replaceAll('-', '')}`,
      rows:[...node.rows].map((row)=>[...row.cells].map((cell)=>cell.innerText.trim())),
    };
    return {
      type: node.tagName === 'BLOCKQUOTE' ? 'quote' : (node.tagName === 'LI' ? 'list_item' : (node.tagName === 'H3' ? 'subheading' : 'paragraph')),
      node_id: node.dataset.nodeId || `NOD_${crypto.randomUUID().replaceAll('-', '')}`,
      text: (() => { const clone=node.cloneNode(true); clone.querySelectorAll('.note-marker').forEach((marker)=>marker.remove()); return clone.innerText.trim(); })(),
    };
  });
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
  if (startElement.dataset.nodeType === 'table') { notice('表格来源请在表题或表下注释段落中插入注释。', true); return {text:'',nodeId:'',offset:0}; }
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
  sessionStorage.setItem('hrwManuscriptId', state.manuscriptId);
  sessionStorage.setItem('hrwSectionId', state.sectionId);
  const list = $('manuscriptList'); list.replaceChildren();
  for (const item of manuscripts) {
    const node = document.createElement('article'); node.className = 'manuscript-row';
    node.append(Object.assign(document.createElement('h3'), {textContent:item.title}));
    for (const part of item.sections) {
      const button = document.createElement('button'); button.textContent = `${part.section_order}. ${part.heading}`;
      button.classList.toggle('selected', part.section_id === state.sectionId);
      button.onclick = () => { state.manuscriptId=item.manuscript_id; state.sectionId=part.section_id; state.proposalId=''; sessionStorage.setItem('hrwManuscriptId',state.manuscriptId);sessionStorage.setItem('hrwSectionId',state.sectionId);renderAuthoring(); };
      node.append(button);
    }
    list.append(node);
  }
  if (state.manuscriptId && state.documentManuscriptId !== state.manuscriptId) {
    loadDocument(state.manuscriptId).then(renderAuthoring).catch((error) => notice(error.message, true)); return;
  }
  $('sectionHeading').textContent = section?.heading || '选择一个章节';
  $('sectionHeading').contentEditable=section?'true':'false';
  $('sectionHeading').title=section?'可直接修改标题；保存新修订后生效。':'';
  $('sectionHeading').onfocus = selectEditableHeading;
  $('sectionVersion').textContent = state.document ? `${state.document.current_revision_id} · 结构化稿件修订` : (section ? `${section.current_version_id} · ${section.operation}` : '人工保存后才产生新修订');
  $('sectionBase').value = section?.content || '';
  $('manuscriptTitleEdit').value=state.document?.document?.title||manuscript?.title||'';
  const proposals = section?.proposals || [];
  let proposal = proposals.find((item) => item.proposal_id === state.proposalId) || proposals.find((item) => item.status === 'pending') || proposals[0];
  if (proposal) state.proposalId = proposal.proposal_id;
  $('sectionProposal').value = proposal?.proposed_content || '';
  const templateSelect=$('exportTemplate'); const previous=templateSelect.value; templateSelect.replaceChildren();
  for(const template of state.snapshot.authoring?.journal_templates||[]) templateSelect.append(new Option(journalTemplateLabel(template),template.template_id));
  templateSelect.value=previous||'builtin-history-research';
  const text=state.document?.document ? state.document.document.children.flatMap((part)=>part.children||[]).map((node)=>node.type==='table'?(node.rows||[]).flat().join(''):node.text||'').join('') : '';
  const notes=state.document?.notes||[];
  $('manuscriptStats').textContent=state.document ? `${text.length} 字符 · ${state.document.document.children.length} 节 · ${notes.filter((note)=>note.status==='active').length} 条已批准注释 · ${notes.filter((note)=>note.pending).length} 条待审` : '尚未选择稿件';
  renderDocumentCanvas();
  renderAuthoringControl(section, proposal);
}

function renderAuthoringControl(section, proposal) {
  const container = $('authoringContent'); container.replaceChildren();
  for (const button of $('authoringTabs').querySelectorAll('button')) button.classList.toggle('selected', button.dataset.authoring === state.authoringMode);
  const authoring = state.snapshot.authoring || {};
  const readiness=authoring.formal_research_readiness;
  if(readiness){
    const gate=card(readiness.status==='READY'?'正式研究门禁已满足':'正式研究门禁未满足',
      readiness.status==='READY'
        ? `依据 ${readiness.design_title}，当前可进入正式成稿与投稿导出。`
        : [...(readiness.blockers||[]),...(readiness.warnings||[])].join('\n'));
    gate.classList.add(readiness.status==='READY'?'gate-ready':'gate-blocked');
    container.append(gate);
  }
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
    for(const item of authoring.journal_templates||[]) template.append(new Option(journalTemplateLabel(item),item.template_id));
    template.value=$('exportTemplate').value||'builtin-history-research';
    const selectedTemplate=(authoring.journal_templates||[]).find((item)=>item.template_id===template.value)||{};
    const sequential=selectedTemplate.requirements?.citation_system==='sequential_reference';
    template.onchange=()=>{$('exportTemplate').value=template.value;renderAuthoringControl(section,proposal);};
    const templateLabel=document.createElement('label'); templateLabel.textContent='注释模板'; templateLabel.append(template);
    if(sequential){
      container.append(card('《唐都学刊》分开处理两类标记','引用文献：正文上标［序号］页码，并自动汇入文后参考文献。\n补充说明：才使用①②③页脚注；不能把书目引证放入脚注。'));
      const citeForm=document.createElement('section');citeForm.className='context-form';
      const source=document.createElement('select');source.id='directCitationSource';source.append(new Option('选择已核验书目信息的项目文献',''));
      for(const item of state.snapshot.sources||[]) if(item.citation_verification_status==='HUMAN_VERIFIED') source.append(new Option(item.title,item.source_id));
      const sourceLabel=document.createElement('label');sourceLabel.textContent='正文引用来源';sourceLabel.append(source);
      const page=document.createElement('select');page.id='directCitationPage';page.append(new Option('先选择来源',''));
      const pageLabel=document.createElement('label');pageLabel.textContent='已经逐页人工核验的原书页';pageLabel.append(page);
      source.onchange=async()=>{
        page.replaceChildren(new Option('选择已核验原页',''));
        if(!source.value)return;
        const view=await request(`/api/source?id=${encodeURIComponent(source.value)}`);
        for(const item of view.pages||[]) if(['human_verified','human_repaired'].includes(item.verification_state)&&item.use_state==='research_usable'&&item.printed_page){
          page.append(new Option(`原书页 ${item.printed_page} · 物理页 ${item.physical_page}`,item.page_id));
        }
      };
      citeForm.append(sourceLabel,pageLabel,actionButton('插入正文引证并保存新修订',async()=>{
        if(!state.manuscriptId||!selection.nodeId)throw new Error('请先在正文同一段落中选中文字。');
        if(!source.value||!page.value)throw new Error('请选择已经人工核验书目信息和原书页的来源。');
        captureDocumentSection();
        const target=state.document.document.children.flatMap((item)=>item.children||[]).find((item)=>item.node_id===selection.nodeId);
        if(!target||typeof target.text!=='string')throw new Error('当前选区不支持插入正文引证。');
        const marker=`[CITE:${source.value}@${page.value}]`;
        target.text=`${target.text.slice(0,selection.offset)}${marker}${target.text.slice(selection.offset)}`;
        state.document=await request('/api/manuscript/document/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,document:state.document.document})});
        state.documentManuscriptId=state.manuscriptId;state.selection={text:'',nodeId:'',offset:0};
        await refreshAuthoring('正文引证已插入并保存；导出时按首次出现顺序统一编号。');
      },true));container.append(citeForm);
    }
    const mode=document.createElement('select'); mode.id='noteMode';
    if(sequential) mode.append(new Option('仅插入解释性脚注','REFORMAT_EXISTING'));
    else mode.append(new Option('核对原页后插入','VERIFY_AND_INSERT'),new Option('元数据已核，页码稍后补','METADATA_FIRST_PAGE_LATER'),new Option('只整理现有注释文字','REFORMAT_EXISTING'));
    const modeLabel=document.createElement('label'); modeLabel.textContent='处理模式'; modeLabel.append(mode);
    const evidence=document.createElement('select'); evidence.id='noteEvidence'; evidence.append(new Option('未选择页块证据',''));
    for(const claim of state.snapshot.research?.claims||[]) for(const item of claim.evidence||[]) evidence.append(new Option(`${item.source_title||item.source_id} · 物理页 ${item.physical_page||'—'} · ${item.quote.slice(0,32)}`,item.evidence_id));
    const evidenceLabel=document.createElement('label'); evidenceLabel.textContent='已冻结到原页的证据'; evidenceLabel.append(evidence);
    if(sequential) form.append(templateLabel,modeLabel,formField('解释性脚注文字（不得填写书目引证）','noteExisting','',true));
    else form.append(templateLabel,modeLabel,evidenceLabel,
      formField('来源类型（book/article/archive/classic）','noteSourceType','book'),formField('作者','noteAuthor'),formField('题名','noteTitle'),
      formField('出版地','notePlace'),formField('出版者','notePublisher'),formField('年份','noteYear'),
      formField('原书页码或稳定定位','noteOriginalPage'),formField('数字文件页（仅辅助定位）','noteDigitalPage'),
      formField('已有注释原文（仅“整理现有注释”使用）','noteExisting','',true));
    form.append(actionButton('生成待审注释',async()=>{
      if(!state.manuscriptId||!selection.nodeId) throw new Error('请先在正文同一段落中选中文字。');
      const citation_data=sequential
        ? {user_supplied_text:$('noteExisting').value,note_role:'explanatory'}
        : {source_type:$('noteSourceType').value,author:$('noteAuthor').value,title:$('noteTitle').value,place:$('notePlace').value,publisher:$('notePublisher').value,year:$('noteYear').value,original_page:$('noteOriginalPage').value,digital_page:$('noteDigitalPage').value,user_supplied_text:$('noteExisting').value};
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
    const humanizerSkill=(state.snapshot.library?.skills||[]).find((item)=>item.name==='historical-humanizer-zh');
    container.append(card('史学语言技能', humanizerSkill
      ? `historical-humanizer-zh · 指令版本 ${humanizerSkill.sha256.slice(0,12)}…\n只学习史学表达操作，不模仿具体学者，也不追逐检测分数。`
      : '未发现 historical-humanizer-zh；可在项目设置的 Skills 兼容区检查共享技能目录。'));
    const profileForm=document.createElement('section');profileForm.className='context-form';
    profileForm.append(formField('画像名称','styleProfileName','我的历史学期刊论文'),formField('作者或共同体','styleProfileOwner','本人'),formField('适用论文类型','styleProfileScope','历史学期刊论文'));
    profileForm.append(actionButton('用当前整篇稿件建立画像',async()=>{
      await request('/api/style-profile/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,name:$('styleProfileName').value,owner_label:$('styleProfileOwner').value,scope:$('styleProfileScope').value})});
      await refreshAuthoring('已生成 OBSERVED_ONCE 文风候选；只保存高层特征和版本指纹，不保存第二份全文。');
    }));container.append(profileForm);
    for(const profile of authoring.style_profiles||[]){
      const features=profile.features||{};
      const sampleCount=(profile.samples||[]).length;
      const node=card(`${profile.name} · ${profile.status}`,`${profile.owner_label} · ${profile.scope}\n${sampleCount} 篇独立稿件：1 篇仅观察，2 篇可判重复，3 篇并经作者批准才可稳定。\n中位段长 ${features.median_paragraph_chars||0} 字 · 中位句长 ${features.median_sentence_chars||0} 字 · 材料坐标开篇 ${Math.round((features.factual_opening_ratio||0)*100)}%\n仅保存高层特征与样本指纹。`);
      if(profile.status!=='REJECTED') node.append(actionButton('把当前整篇稿件加入此画像',async()=>{await request('/api/style-profile/add-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profile.profile_id,manuscript_id:state.manuscriptId})});await refreshAuthoring('新样本已加入；原有批准状态已回退，须按新的聚合画像重新决定。');}));
      if(['OBSERVED_ONCE','RECURRING','AUTHOR_APPROVED'].includes(profile.status)){
        const decide=async(approved)=>{const reviewer=window.prompt('决定人');if(!reviewer?.trim())return;const reason=window.prompt('批准或拒绝依据');if(!reason?.trim())return;await request('/api/style-profile/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profile.profile_id,approved,reviewer,reason})});await refreshAuthoring(approved?'文风画像已标记为 AUTHOR_APPROVED，可在本项目选择使用。':'文风候选已拒绝，不会再次套用。');};
        const row=document.createElement('div');row.className='row';row.append(actionButton('批准为我的文风偏好',()=>decide(true),true),actionButton('拒绝',()=>decide(false)));node.append(row);
      }
      container.append(node);
    }
    const structuredText=(documentSection()?.children||[]).map((node)=>node.type==='table'
      ? (node.rows||[]).map((row)=>row.join('\t')).join('\n')
      : (node.text||'').trim()).filter(Boolean).join('\n\n');
    if(structuredText!==section.content.trim()) {
      const syncWarning=card('正文尚未同步当前批准章节','导出仍会使用中央正文。请人工确认后把当前批准章节写入新的结构化稿件修订。');
      syncWarning.append(actionButton('同步到正文并创建新修订',async()=>{await request('/api/manuscript/document/sync-section',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,section_id:section.section_id})});await refreshAuthoring('当前批准章节已同步到正文，并保留旧修订。');},true));
      container.append(syncWarning);
    }
    const form = document.createElement('section'); form.className='context-form';
    const operation = document.createElement('select'); operation.id='writingOperation';
    operation.append(new Option('保真润色','polish'), new Option('依据已批准正文生成摘要/投稿信息','metadata_draft'), new Option('史学去模板化（证据保真）','historical_humanize'), new Option('基于冻结证据分节写作','section_draft'));
    const operationLabel=document.createElement('label'); operationLabel.textContent='操作'; operationLabel.append(operation);
    const skill=document.createElement('select');skill.id='writingSkill';
    if(humanizerSkill) skill.append(new Option(`historical-humanizer-zh · ${humanizerSkill.sha256.slice(0,12)}…`,humanizerSkill.name));
    else skill.append(new Option('未发现史学语言技能',''));
    const skillLabel=document.createElement('label');skillLabel.textContent='史学语言技能版本';skillLabel.append(skill);
    const styleProfile=document.createElement('select');styleProfile.id='writingStyleProfile';styleProfile.append(new Option('不套用个人文风画像',''));
    for(const item of authoring.style_profiles||[]) if(['AUTHOR_APPROVED','STABLE_PROFILE'].includes(item.status)) styleProfile.append(new Option(`${item.name} · ${item.status}`,item.profile_id));
    const styleProfileLabel=document.createElement('label');styleProfileLabel.textContent='作者批准的高层文风画像';styleProfileLabel.append(styleProfile);
    const freeze=document.createElement('select'); freeze.id='writingFreeze'; freeze.append(new Option('不使用冻结包',''));
    for (const item of state.snapshot.research?.freezes || []) if(item.status==='approved') freeze.append(new Option(item.title,item.freeze_id));
    const freezeLabel=document.createElement('label'); freezeLabel.textContent='批准的证据冻结包'; freezeLabel.append(freeze);
    const evidenceScope=document.createElement('select');evidenceScope.id='writingEvidenceScope';evidenceScope.multiple=true;evidenceScope.size=7;evidenceScope.disabled=true;
    const evidenceScopeLabel=document.createElement('label');evidenceScopeLabel.textContent='本节允许使用的冻结证据（可多选）';evidenceScopeLabel.append(evidenceScope);
    const populateEvidenceScope=()=>{evidenceScope.replaceChildren();const selectedFreeze=(state.snapshot.research?.freezes||[]).find((item)=>item.freeze_id===freeze.value);const shownEvidence=new Set();for(const claim of selectedFreeze?.payload?.claims||[])for(const item of claim.evidence||[]){if(shownEvidence.has(item.evidence_id))continue;shownEvidence.add(item.evidence_id);evidenceScope.append(new Option(`${item.relation} · 物理页 ${(item.physical_pages||[item.physical_page]).join('–')} · ${item.quote.slice(0,48)}`,item.evidence_id));}evidenceScope.disabled=operation.value!=='section_draft'||!selectedFreeze;skill.disabled=operation.value!=='historical_humanize';styleProfile.disabled=operation.value!=='historical_humanize';};
    freeze.onchange=populateEvidenceScope;operation.onchange=populateEvidenceScope;
    form.append(operationLabel, skillLabel, styleProfileLabel, formField('修改或写作要求','writingInstruction','让材料和行动者先于概念，不改变事实、引文与限定',true), freezeLabel, evidenceScopeLabel);populateEvidenceScope();
    const generate=actionButton('生成待审提案', async()=>{
      const evidence_ids=[...evidenceScope.selectedOptions].map((option)=>option.value);
      if(operation.value==='section_draft'&&!evidence_ids.length) throw new Error('请为本节至少选择一条已冻结证据。');
      generate.disabled=true; notice('写作模型正在生成待审提案，请勿重复提交。');
      try {
        const result=await request('/api/writing/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section_id:section.section_id,operation:operation.value,instruction:$('writingInstruction').value,freeze_id:freeze.value,evidence_ids,skill_name:skill.value,style_profile_id:styleProfile.value})});
        state.proposalId=result.proposal_id; await refreshAuthoring(result.validation.valid?'写作提案已生成，等待逐项核对。':'提案违反证据契约，已阻断批准。');
        const drawer=document.querySelector('details.proposal-drawer'); drawer.open=true; drawer.scrollIntoView({block:'center'});
      } finally { generate.disabled=false; }
    },true); form.append(generate); container.append(form);
    if (proposal) {
      const problems=[];
      if(proposal.validation.missing_markers?.length) problems.push('缺失受保护内容：'+proposal.validation.missing_markers.join('、'));
      if(proposal.validation.altered_quotes?.length) problems.push('发现未获准或被改写的直接引文：'+proposal.validation.altered_quotes.join('；'));
      if(proposal.validation.invalid_evidence_ids?.length) problems.push('无效证据编号：'+proposal.validation.invalid_evidence_ids.join('、'));
      if(proposal.validation.guard_status==='BLOCKED_PROTECTED_CHANGE') problems.push('精确保护项发生变化，禁止批准');
      if(proposal.operation==='section_draft'&&!proposal.validation.evidence_linked) problems.push('正文没有绑定冻结证据编号');
      const contractChecked=proposal.operation!=='section_draft'||Object.hasOwn(proposal.validation,'evidence_linked');
      const detail=!contractChecked?'旧提案未经过当前证据契约检查，不可直接批准。':(proposal.validation.valid?'证据契约检查通过；仍须人工核对解释。':problems.join('\n'));
      const node=card(`${proposal.operation} · ${proposal.status}`, detail);
      node.append(Object.assign(document.createElement('small'),{textContent:`提案 ${proposal.proposed_content.length} 字符 · 基础版本 ${proposal.base_version_id} · ${new Date(proposal.created_at).toLocaleString()}`}));
      if(proposal.operation==='historical_humanize') node.append(Object.assign(document.createElement('p'),{textContent:`精确保护：${proposal.validation.guard_status}；事实、归因、因果、范围和限定仍须逐段人工复核。\n段落决定：${(proposal.validation.paragraph_decisions||[]).map((item)=>`${item.paragraph}:${item.decision}`).join(' · ')||'待核'}`}));
      if(proposal.validation.decision_reason) node.append(Object.assign(document.createElement('p'),{textContent:`人工决定：${proposal.validation.decision_reason}`}));
      if(proposal.status==='pending') {
        node.append(formField('决定人','writingReviewer',''),formField('批准或拒绝依据','writingDecisionReason','',true));
        const row=document.createElement('div'); row.className='row';
        const decide=async(approved)=>{const reviewer=$('writingReviewer').value.trim(),reason=$('writingDecisionReason').value.trim();if(!reviewer||!reason)throw new Error('请填写决定人和批准或拒绝依据。');await request('/api/writing/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:proposal.proposal_id,approved,reviewer,reason,edited_content:approved?$('sectionProposal').value:undefined})});state.proposalId='';await refreshAuthoring(approved?'已保存为新的批准章节版本，旧版本仍保留。':'提案已拒绝并记录理由，当前章节未改变。');};
        const approve=actionButton('核对修改后批准',()=>decide(true),true); approve.disabled=!contractChecked;
        row.append(approve,actionButton('拒绝提案',()=>decide(false))); node.append(row);
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
  } else if (state.authoringMode === 'review') {
    const manuscript=selectedManuscript();
    if(!manuscript){container.append(card('尚未选择稿件','先创建或导入稿件。'));return;}
    const models=authoring.review_models||{};
    container.append(card('评审独立性边界',`主评审：${models.primary?.available?`${models.primary.provider} / ${models.primary.model}`:'未配置'}。三个角色使用彼此隔离的提示与输出，但同一模型仍可能共享盲点。${models.secondary?.available?`\n交叉评审：${models.secondary.provider} / ${models.secondary.model}`:'\n可在项目设置中另配交叉评审模型。'}`));
    const form=document.createElement('section');form.className='context-form';
    const template=document.createElement('select');template.id='reviewTemplate';
    for(const item of authoring.journal_templates||[]) template.append(new Option(journalTemplateLabel(item),item.template_id));
    template.value=$('exportTemplate').value||'builtin-history-research';
    const templateLabel=document.createElement('label');templateLabel.textContent='本轮投稿模板';templateLabel.append(template);form.append(templateLabel);
    const run=actionButton('运行三角色评审（同一主模型）',async()=>{
      run.disabled=true;run.textContent='三位评审并行运行中…';notice('论证、史料与引注评审正在分别运行；正文不会被修改。');
      try{await request('/api/manuscript/review/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,template_id:template.value,use_secondary:false})});await refreshAuthoring('三份独立角色报告已固定到当前章节版本。');}finally{run.disabled=false;run.textContent='运行三角色评审（同一主模型）';}
    },true);run.disabled=!models.primary?.available;form.append(run);
    const hasPrimary=(manuscript.review_groups||[]).some((group)=>group.is_current&&group.reports.some((report)=>report.model_role==='main_reasoning'));
    const cross=actionButton('用第二模型做反方复核',async()=>{
      cross.disabled=true;notice('交叉评审模型正在挑战当前评审共识。');
      try{await request('/api/manuscript/review/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,template_id:template.value,use_secondary:true})});await refreshAuthoring('异构反方评审已保存。');}finally{cross.disabled=false;}
    });cross.disabled=!models.secondary?.available||!hasPrimary;form.append(cross);container.append(form);
    const roleLabels={argument_reviewer:'论证与结构',source_critic:'史料与证据',citation_editor:'引注与模板',adversarial_reviewer:'异构反方'};
    for(const group of manuscript.review_groups||[]){
      const templateName=(authoring.journal_templates||[]).find((item)=>item.template_id===group.template_id)?.name||group.template_id;
      const node=card(`${group.is_current?'当前版本':'已过期'} · ${templateName}`,`${new Date(group.created_at).toLocaleString()} · ${group.review_group_id}`);
      for(const report of group.reports){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`${roleLabels[report.reviewer_role]||report.reviewer_role} · ${report.model_snapshot.provider} / ${report.model_snapshot.model}`;const pre=document.createElement('pre');pre.textContent=report.report;details.append(summary,pre);node.append(details);}container.append(node);
    }
  } else if (state.authoringMode === 'journal') {
    const profile=(authoring.submission_profiles||[]).find((item)=>item.manuscript_id===state.manuscriptId)||{};
    const profileForm=document.createElement('section');profileForm.className='context-form';
    profileForm.append(Object.assign(document.createElement('strong'),{textContent:'当前稿件的作者与投稿信息'}));
    const profileFields=[['姓名','submissionName','name'],['笔名对应真实姓名','submissionRealName','real_name'],['性别','submissionGender','gender'],['民族','submissionEthnicity','ethnicity'],['籍贯','submissionNativePlace','native_place'],['学位及学科','submissionDegree','degree'],['工作单位','submissionAffiliation','affiliation'],['职称','submissionTitle','professional_title'],['职务','submissionPosition','position'],['主要研究方向','submissionInterests','research_interests'],['项目名称','submissionProject','project_source'],['项目编号','submissionProjectNumber','project_number'],['联系电话','submissionPhone','phone'],['详细邮寄地址','submissionAddress','postal_address'],['邮编','submissionPostalCode','postal_code'],['电子邮箱','submissionEmail','email']];
    for(const [label,id,key] of profileFields) profileForm.append(formField(label,id,profile[key]||'',key==='postal_address'||key==='research_interests'));
    profileForm.append(actionButton('保存本稿投稿信息',async()=>{const payload={manuscript_id:state.manuscriptId};for(const [,id,key] of profileFields)payload[key]=$(id).value;await request('/api/manuscript/submission-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});await refreshAuthoring('投稿信息已保存到当前稿件；不会自动复用于其他作者。');},true));container.append(profileForm);
    const form=document.createElement('section');form.className='context-form';form.append(
      formField('模板名称','journalName'),formField('规范版本','journalVersion'),formField('规范发布日期','journalEffective'),
      formField('官方来源网址','journalSource'),formField('本次核验日期','journalVerified'),
      formField('注释与参考文献规则','journalCitation','',true),formField('稿件组成（逗号分隔）','journalSections'),
      formField('其他硬性要求（每行一项）','journalRequirements','',true)
    );
    form.append(actionButton('保存带版本的人工模板',async()=>{const notes=$('journalRequirements').value.split(/\n/).map(v=>v.trim()).filter(Boolean);await request('/api/journal/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('journalName').value,version_label:$('journalVersion').value,effective_date:$('journalEffective').value,source_url:$('journalSource').value,verified_at:$('journalVerified').value,verification_status:'OFFICIAL_SOURCE_CHECKED',citation_style:$('journalCitation').value,section_rules:$('journalSections').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean),requirements:{notes}})});await refreshAuthoring('期刊模板及其规范版本已保存；投稿前仍须核对是否有更新。');},true));container.append(form);
    for(const item of authoring.journal_templates||[]){const oldTangdu=item.origin==='user'&&item.name==='《唐都学刊》';const shownName=oldTangdu?'《唐都学刊》（旧人工模板）':item.name;const node=card(shownName,`${item.version_label||'人工模板'} · ${item.verification_status||'USER_DEFINED'}`);const requirements=item.requirements||{};node.append(Object.assign(document.createElement('p'),{textContent:`${item.citation_style}\n${item.section_rules.join(' → ')}\n${requirements.academic_paper_standard||''} ${requirements.bibliographic_standard||''}\n${requirements.superseded_web_notice||requirements.compliance_scope||''}\n核验：${item.verified_at||'由用户维护'}`}));if(item.source_url){const link=document.createElement('a');link.href=item.source_url;link.target='_blank';link.rel='noreferrer';link.textContent=oldTangdu?'查看旧版网页来源':'查看规则来源';node.append(link);}container.append(node);}
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

function liveRunNotice(run) {
  if (!run) return 'Agent 正在建立本次运行……';
  const event = run.events?.at(-1);
  const tool = event?.payload?.tool;
  if (event?.event_type === 'tool_started') return `Agent 正在调用 ${tool}……`;
  if (event?.event_type === 'tool_completed') return `${tool} 已完成，Agent 正在决定下一步……`;
  if (event?.event_type === 'run_failed') return `本次运行失败：${event.payload.error || run.error || '未知错误'}`;
  return `Agent 正在运行 · 已记录 ${event?.sequence || 0} 个步骤……`;
}

async function pollActiveThread(threadId) {
  if (!threadId || state.threadId !== threadId) return;
  const thread = await request(`/api/thread?id=${encodeURIComponent(threadId)}`);
  if (state.threadId !== threadId) return;
  state.thread = thread;
  renderThread();
  notice(liveRunNotice(latestRun()));
}

async function loadSource(sourceId, keepPage = false) {
  const previousSourceId = state.view?.source?.source_id;
  const previousPageId = currentPage()?.page_id;
  state.view = await request(`/api/source?id=${encodeURIComponent(sourceId)}`);
  if (!keepPage) state.pageIndex = 0;
  state.pageIndex = Math.min(state.pageIndex, Math.max(0, state.view.pages.length - 1));
  if (previousSourceId !== state.view.source?.source_id || previousPageId !== currentPage()?.page_id) {
    clearReviewReason();
  }
  render();
}

function selectEditableHeading() {
  const heading = $('sectionHeading');
  if (!heading?.isContentEditable) return;
  const range = document.createRange();
  range.selectNodeContents(heading);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

function currentPage() { return state.view?.pages[state.pageIndex]; }
function openAnomalies() { return (state.view?.anomalies || []).filter((item) => item.status === 'open'); }
function pageAnomaly(page) { return openAnomalies().find((item) => item.scope_type === 'page' && item.target_id === page?.page_id && item.severity !== 'advisory'); }
function currentPageAnomalies() {
  const page = currentPage(); if (!page) return [];
  const blockIds = new Set(page.blocks.map((block) => block.block_id));
  const relationIds = new Set((state.view?.relations || [])
    .filter((relation) => blockIds.has(relation.from_block_id) || blockIds.has(relation.to_block_id))
    .map((relation) => relation.relation_id));
  return openAnomalies().filter((item) => item.scope_type === 'source'
    || (item.scope_type === 'page' && item.target_id === page.page_id)
    || (item.scope_type === 'block' && blockIds.has(item.target_id))
    || (item.scope_type === 'relation' && relationIds.has(item.target_id)));
}

function renderRail() {
  const rail = $('pageRail'); rail.replaceChildren();
  for (const [index, page] of (state.view?.pages || []).entries()) {
    const button = document.createElement('button');
    button.textContent = page.page_type === 'docx_locator'
      ? `片段 ${page.physical_page}`
      : `第 ${page.physical_page} 页${page.printed_page ? ` · ${page.printed_page}` : ''}`;
    button.classList.toggle('selected', index === state.pageIndex);
    button.classList.toggle('blocked', page.use_state === 'blocked');
    button.onclick = () => { state.pageIndex = index; clearReviewReason(); render(); };
    rail.append(button);
  }
}

function blockCard(block, pageAnomaly) {
  const card = document.createElement('article'); card.className = 'block-card';
  const anomaly = openAnomalies().find((item) => item.scope_type === 'block' && item.target_id === block.block_id);
  card.classList.toggle('blocked', Boolean(anomaly)); card.dataset.order = block.block_order;
  card.dataset.region = JSON.stringify(block.source_region || null);
  const meta = document.createElement('div'); meta.className = 'block-meta';
  const region = block.source_region ? Object.values(block.source_region).map((v) => Number(v).toFixed(2)).join(', ') : '未定位';
  const label = document.createElement('span'); label.textContent = `块 ${block.block_order} · 区域 ${region}`;
  const type = document.createElement('select'); type.className = 'block-type';
  for (const value of ['paragraph', 'heading', 'footnote', 'header', 'footer', 'page_number']) type.append(new Option(value, value));
  type.value = block.block_type;
  const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '从本页删除此块';
  remove.onclick = () => card.remove();
  meta.append(label, type, remove);
  const textarea = document.createElement('textarea'); textarea.value = block.effective_text; textarea.dataset.blockId = block.block_id;
  card.append(meta, textarea);
  if (anomaly) {
    const actions = document.createElement('div'); actions.className = 'block-actions';
    const button = document.createElement('button'); button.textContent = '提交这一小段';
    button.onclick = async () => {
      try {
        await request('/api/repair/block', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ anomaly_id: anomaly.anomaly_id, text: textarea.value, ...reviewerPayload() }) });
        await loadSource(state.view.source.source_id, true); notice('局部修正已提交，其他异常保持不变。');
      } catch (error) { notice(error.message, true); }
    };
    actions.append(button); card.append(actions);
  } else if (block.block_id && currentPage()?.page_type !== 'docx_locator') {
    const actions = document.createElement('div'); actions.className = 'block-actions';
    const verified = ['human_verified', 'human_repaired'].includes(block.verification_state);
    const button = document.createElement('button');
    button.textContent = verified ? '此段已人工核验' : '确认此段与原图一致';
    button.disabled = verified;
    button.onclick = async () => {
      try {
        await request('/api/block/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block_id:block.block_id, ...reviewerPayload()})});
        await loadSource(state.view.source.source_id, true); notice('这一段已经与原图逐字核验，可加入证据卡。');
      } catch (error) { notice(error.message, true); }
    };
    const correct = document.createElement('button');
    correct.textContent = pageAnomaly ? '保存这一小段修正' : '保存这段修正';
    correct.onclick = async () => {
      try {
        await request('/api/block/correct', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block_id:block.block_id, text:textarea.value, block_type:type.value, ...reviewerPayload()})});
        await loadSource(state.view.source.source_id, true); notice('这一段的人工修正已保存，机器原文仍保留在版本记录中。');
      } catch (error) { notice(error.message, true); }
    };
    if (!pageAnomaly) actions.append(button);
    actions.append(correct); card.append(actions);
  }
  return card;
}

function renderBlocks() {
  const page = currentPage(); const container = $('blocks'); container.replaceChildren();
  if (!page) { container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'导入 PDF 后显示逐页文本。'})); return; }
  const pageIssue = pageAnomaly(page);
  const blocks = page.blocks.length ? page.blocks : [{block_id:'', block_order:1, block_type:'paragraph', effective_text:'', source_region:null}];
  for (const block of blocks) container.append(blockCard(block, pageIssue));
  const locator = page.page_type === 'docx_locator';
  const addBlock = document.createElement('button'); addBlock.type = 'button'; addBlock.textContent = '在本页新增一块';
  addBlock.onclick = () => container.append(blockCard({
    block_id: '',
    block_order: container.querySelectorAll('.block-card').length + 1,
    block_type: 'paragraph',
    effective_text: '',
    source_region: null,
  }, pageIssue));
  if (!locator) {
    const twoColumn = document.createElement('button');
    twoColumn.type = 'button'; twoColumn.textContent = '按双栏阅读顺序重排';
    twoColumn.onclick = () => {
      const cards = [...container.querySelectorAll('.block-card')];
      const located = cards.map((card, index) => ({
        card, index, region: JSON.parse(card.dataset.region || 'null'),
      })).filter((item) => item.region);
      const left = located.filter((item) => item.region.x1 <= 0.52 && item.region.y0 >= 0.1);
      const right = located.filter((item) => item.region.x0 >= 0.48 && item.region.y0 >= 0.1);
      const starts = left.flatMap((l) => right
        .filter((r) => Math.abs(l.region.y0 - r.region.y0) <= 0.07)
        .map((r) => Math.max(l.region.y0, r.region.y0)));
      if (!starts.length) { notice('未识别到稳定的双栏起点，请人工调整。', true); return; }
      const start = Math.min(...starts);
      const suffixStarts = located.filter((item) => {
        const width = item.region.x1 - item.region.x0;
        return item.region.y0 > Math.max(0.7, start + 0.2) && width >= 0.55;
      }).map((item) => item.region.y0);
      const suffixStart = suffixStarts.length ? Math.min(...suffixStarts) - 0.03 : 1.1;
      const byPosition = (a, b) => (a.region.y0 - b.region.y0)
        || (a.region.x0 - b.region.x0) || (a.index - b.index);
      const prefix = located.filter((item) => item.region.y0 < start).sort(byPosition);
      const body = located.filter((item) => item.region.y0 >= start && item.region.y0 < suffixStart);
      const bodyLeft = body.filter((item) => (item.region.x0 + item.region.x1) / 2 < 0.5).sort(byPosition);
      const bodyRight = body.filter((item) => (item.region.x0 + item.region.x1) / 2 >= 0.5).sort(byPosition);
      const suffix = located.filter((item) => item.region.y0 >= suffixStart).sort(byPosition);
      const ordered = [...prefix, ...bodyLeft, ...bodyRight, ...suffix];
      if (ordered.length !== cards.length) { notice('本页存在无位置块，未自动重排。', true); return; }
      for (const item of ordered) container.insertBefore(item.card, addBlock);
      notice('已生成双栏顺序：请对照原页检查后，再提交整页修正。');
    };
    container.append(twoColumn, addBlock);
  }
  $('pageRepair').hidden = locator;
  $('pageRepair').textContent = pageIssue ? '提交整页修正' : '保存整页结构修正';
  $('pageRepair').onclick = async () => {
    try {
      const cards = [...container.querySelectorAll('.block-card')];
      const repaired = cards.map((card, index) => ({
        order: index + 1,
        type: card.querySelector('.block-type').value,
        text: card.querySelector('textarea').value,
      }));
      await request('/api/page/revise', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({page_id:page.page_id, blocks:repaired, ...reviewerPayload()}) });
      await loadSource(state.view.source.source_id, true); notice('整页修正已提交，并保留原机器结果和修正记录。');
    } catch (error) { notice(error.message, true); }
  };
  const blocking = currentPageAnomalies().some((item) => item.severity !== 'advisory' && ['page', 'block'].includes(item.scope_type));
  const verified = ['human_verified', 'human_repaired'].includes(page.verification_state);
  const pageUnavailable = page.use_state !== 'research_usable';
  $('pageVerify').hidden = blocking;
  $('pageVerify').disabled = verified || pageUnavailable;
  $('pageVerify').textContent = verified ? '本页已人工核验'
    : pageUnavailable ? '整页仍有待核项（已核段可使用）' : '确认本页与原图一致';
  $('pageVerify').onclick = async () => {
    try {
      await request('/api/page/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({page_id:page.page_id, ...reviewerPayload()})});
      await loadSource(state.view.source.source_id, true); notice('本页已经人工核验，可进入证据卡选择。');
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
  type.value = block.type;
  const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除此块';
  remove.onclick = () => card.remove();
  meta.append(label, type, remove);
  const textarea = document.createElement('textarea'); textarea.value = block.text;
  card.append(meta, textarea); return card;
}

function renderOcrProposal() {
  const page = currentPage();
  const container = $('ocrProposal'); container.replaceChildren();
  const button = $('ocrPropose');
  const capability = state.capabilities?.vision_ocr;
  if (capability?.available) {
    $('ocrCapability').textContent = `${capability.provider} · ${capability.model} · 单并发 · 输出只作为待审建议`;
  } else {
    const missing = capability?.missing?.join('、') || '尚未配置';
    $('ocrCapability').textContent = `视觉模型不可用：${missing}`;
  }
  if (!page) { button.hidden = true; return; }
  const proposals = (state.view?.ocr_proposals || []).filter((item) => item.page_id === page.page_id);
  const pending = proposals.find((item) => item.status === 'pending');
  const verified = ['human_verified', 'human_repaired'].includes(page.verification_state);
  const locator = page.page_type === 'docx_locator';
  button.hidden = !capability?.available || verified || locator || Boolean(pending);
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
  const addBlock = document.createElement('button'); addBlock.type = 'button'; addBlock.textContent = '新增一块';
  addBlock.onclick = () => blocks.append(proposalBlock({
    order: blocks.querySelectorAll('.proposal-block').length + 1,
    type: 'paragraph',
    text: '',
    region: null,
  }));
  card.append(addBlock);
  const warnings = pending.normalized_payload.warnings || [];
  if (warnings.length) card.append(Object.assign(document.createElement('small'), {textContent:`模型警告：${warnings.join('；')}`}));
  const actions = document.createElement('div'); actions.className = 'proposal-actions';
  const accept = document.createElement('button'); accept.className = 'primary-inline'; accept.textContent = '核对后接受修正';
  accept.onclick = async () => {
    try {
      const edited = [...blocks.querySelectorAll('.proposal-block')].map((item, index) => ({
        order: index + 1,
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
  const anomalies = currentPageAnomalies();
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

function renderRelations() {
  const container = $('relations'); container.replaceChildren();
  const page = currentPage();
  if (!page) return;
  const blockIds = new Set(page.blocks.map((block) => block.block_id));
  const relations = (state.view?.relations || []).filter(
    (relation) => blockIds.has(relation.from_block_id) || blockIds.has(relation.to_block_id),
  );
  if (!relations.length) {
    container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'当前页没有跨页关系。'}));
    return;
  }
  const allPages = state.view.pages || [];
  const pageForBlock = (blockId) => allPages.find((item) => item.blocks.some((block) => block.block_id === blockId));
  for (const relation of relations) {
    const leftPage = pageForBlock(relation.from_block_id);
    const rightPage = pageForBlock(relation.to_block_id);
    const card = document.createElement('article'); card.className = 'relation-card';
    const value = relation.effective_value?.continues;
    card.append(Object.assign(document.createElement('small'), {
      textContent:`${relation.relation_id} · ${value === true ? '已确认续接' : value === false ? '已确认不续接' : '待确认'}`,
    }));
    const form = document.createElement('div'); form.className = 'relation-form';
    const from = document.createElement('select');
    const to = document.createElement('select');
    for (const block of leftPage?.blocks || []) from.append(new Option(`第${leftPage.physical_page}页 B${block.block_order} · ${block.block_type}`, block.block_id));
    for (const block of rightPage?.blocks || []) to.append(new Option(`第${rightPage.physical_page}页 B${block.block_order} · ${block.block_type}`, block.block_id));
    from.value = relation.from_block_id; to.value = relation.to_block_id;
    const continues = document.createElement('select');
    continues.append(new Option('确认续接', 'true'), new Option('确认不续接', 'false'));
    continues.value = value === false ? 'false' : 'true';
    const save = document.createElement('button'); save.textContent = '保存关系更正';
    save.onclick = async () => {
      try {
        await request('/api/relation/correct', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
          relation_id:relation.relation_id, from_block_id:from.value, to_block_id:to.value,
          continues:continues.value === 'true', ...reviewerPayload(),
        })});
        await loadSource(state.view.source.source_id, true); notice('跨页关系端点与人工判断已保存，原机器关系仍保留在修复记录中。');
      } catch (error) { notice(error.message, true); }
    };
    form.append(from, to, continues, save); card.append(form); container.append(card);
  }
}

$('jumpToPage').onclick = () => {
  const physicalPage = Number($('pageJump').value);
  const index = (state.view?.pages || []).findIndex((page) => page.physical_page === physicalPage);
  if (index < 0) { notice('没有这个物理页。', true); return; }
  state.pageIndex = index; clearReviewReason(); render();
  $('pageRail').querySelector('.selected')?.scrollIntoView({block:'nearest'});
};

$('savePrintedPage').onclick = async () => {
  const page = currentPage();
  if (!page) return;
  try {
    await request('/api/page/printed-page', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      page_id:page.page_id, printed_page:$('printedPage').value, ...reviewerPayload(),
    })});
    page.printed_page = $('printedPage').value.trim();
    $('pageLabel').textContent = `物理页 ${page.physical_page}${page.printed_page ? ` · 印刷页 ${page.printed_page}` : ''}`;
    notice('物理页与印刷页的人工对应关系已保存。');
  } catch (error) { notice(error.message, true); }
};

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
  const skillItems=state.snapshot.library?.skills||[];
  const skills = card('用户可用 Skills', '只展示能产生明确研究产物的入口；具体页面只会列出与当前动作兼容的技能。');
  for (const skill of skillItems.filter((item)=>item.placement==='user_action')) skills.append(Object.assign(document.createElement('p'), {textContent:`${skill.name} · ${skill.compatible_actions.join('、')} · ${skill.sha256.slice(0,12)}…\n${skill.description}`})); container.append(skills);
  const policies=card('Harness 内部策略', '这些规则由工作流自动调用，不作为教授需要逐项选择的按钮。');
  for(const skill of skillItems.filter((item)=>item.placement==='harness_policy')) policies.append(Object.assign(document.createElement('p'),{textContent:`${skill.name} · ${skill.sha256.slice(0,12)}…\n${skill.description}`}));container.append(policies);
  const integrations=card('程序集成能力','浏览器、长期记忆和 Obsidian 等能力由对应页面或 Harness 调用，不混入史学任务按钮。');
  for(const skill of skillItems.filter((item)=>item.placement==='integration')) integrations.append(Object.assign(document.createElement('p'),{textContent:`${skill.name} · ${skill.sha256.slice(0,12)}…`}));container.append(integrations);
  container.append(card('程序级硬契约','原页锚点、来源资格、证据状态、冻结包、版本指纹和校验器由程序强制执行，不依赖模型是否记得某条 Skill。'));
  const connectors = card('研究连接器', '公开数据库可有界检索；已登录数据库只能在用户合法权限内操作。');
  for (const capability of caps.research_connectors || []) connectors.append(Object.assign(document.createElement('p'), {textContent:`${capability.provider} · ${capability.available ? '可用' : '未配置'} · ${capability.mode}${capability.missing?.length ? ` · 缺少 ${capability.missing.join('、')}` : ''}`})); container.append(connectors);
  container.append(card('隐私与人工门禁', '不保存 Cookie、密码、API Key 或未脱敏网络日志。远程模型只接收用户明确选择的页块、章节和选区。证据冻结、正文采用与记忆提升都必须由人决定。'));
}

function renderSkillCatalog() {
  const container=$('skillCatalog');if(!container||!state.snapshot)return;container.replaceChildren();
  const query=($('skillQuery')?.value||'').trim().toLowerCase();
  const labels={user_action:'可直接调用',harness_policy:'Harness 自动编排',integration:'程序集成'};
  const skills=(state.snapshot.library?.skills||[]).filter((item)=>!query||`${item.name} ${item.description} ${item.agent_program?.display_name||''}`.toLowerCase().includes(query));
  for(const placement of ['user_action','harness_policy','integration']){
    const group=skills.filter((item)=>item.placement===placement);if(!group.length)continue;
    const section=document.createElement('section');section.className='skill-group';
    const heading=document.createElement('h2');heading.textContent=`${labels[placement]} · ${group.length}`;section.append(heading);
    for(const skill of group){
      const program=skill.agent_program||{};
      const node=card(program.display_name||skill.name,`${skill.invocation} · ${skill.sha256.slice(0,12)}…\n${program.short_description||skill.description}\n${placement==='user_action'?'运行时会固定技能与 Agent 程序版本；所有写入仍经过工作台门禁。':placement==='harness_policy'?'由研究阶段和权限自动触发，不提供直接按钮。':'由对应页面调用，不混入研究动作。'}`);
      if(program.sha256) node.append(Object.assign(document.createElement('small'),{textContent:`Agent 程序 ${program.sha256.slice(0,12)}… · ${program.allow_implicit_invocation?'允许 Harness 建议':'仅显式调用'}`}));
      if(placement==='user_action') node.append(actionButton(`在对话中调用 ${skill.invocation}`,()=>{setMode('agent');$('messageInput').value=`${skill.invocation} `;$('messageInput').focus();renderSlashMenu();},true));
      section.append(node);
    }
    container.append(section);
  }
  if(!skills.length)container.append(card('没有匹配项','换一个技能名、研究动作或 Agent 程序关键词。'));
}

function renderSlashMenu() {
  const menu=$('slashMenu');if(!menu||!state.snapshot)return;
  const text=$('messageInput').value;
  if(!text.startsWith('/')){menu.hidden=true;menu.replaceChildren();return;}
  const query=text.slice(1).split(/\s/,1)[0].toLowerCase();
  const matches=(state.snapshot.library?.skills||[]).filter((item)=>item.placement==='user_action'&&item.name.toLowerCase().includes(query)).slice(0,10);
  menu.replaceChildren();
  for(const skill of matches){const button=document.createElement('button');button.type='button';button.textContent=`${skill.invocation}  ${skill.agent_program?.display_name||skill.description}`;button.onclick=()=>{$('messageInput').value=`${skill.invocation} `;menu.hidden=true;$('messageInput').focus();};menu.append(button);}
  menu.hidden=!matches.length||text.includes(' ');
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
  renderRail(); renderOcrProposal(); renderBlocks(); renderRelations(); renderAnomalies();
  const page = currentPage(); const source = state.view?.source;
  $('sourceTitle').textContent = source?.title || '尚未导入文献';
  $('sourceState').textContent = source ? `${source.processing_state} · ${source.use_state}` : '等待材料';
  const citation=source?.citation_metadata||{};
  $('citationAuthor').value=citation.author||'';
  $('citationTitle').value=citation.title||source?.title||'';
  $('citationEdition').value=citation.edition||'';
  $('citationTranslator').value=citation.translator||'';
  $('citationPlace').value=citation.place||'';
  $('citationPublisher').value=citation.publisher||'';
  $('citationYear').value=citation.year||'';
  $('citationTypeCode').value=citation.type_code||'';
  $('citationJournal').value=citation.journal||'';
  $('citationVolume').value=citation.volume||'';
  $('citationIssue').value=citation.issue||'';
  $('citationPageRange').value=citation.page_range||'';
  $('citationVerifiedBy').value=citation.verified_by||'human-reviewer';
  $('citationMetadataState').textContent=citation.verification_status==='HUMAN_VERIFIED'
    ? `已由 ${citation.verified_by} 核验 · ${new Date(citation.verified_at).toLocaleString()}`
    : '未核验的题名页信息不会被导出器补造。';
  const locator = page?.page_type === 'docx_locator';
  $('pageRailTitle').textContent = locator ? '译稿片段' : '物理页';
  $('pageLabel').textContent = page ? (locator ? `逻辑片段 ${page.physical_page} · locator_only` : `物理页 ${page.physical_page}${page.printed_page ? ` · 印刷页 ${page.printed_page}` : ''}`) : '原 PDF 页面始终是校对依据';
  $('pageJump').value = page?.physical_page || '';
  $('printedPage').value = page?.printed_page || '';
  $('pageImage').hidden = Boolean(locator);
  $('locatorNotice').hidden = !locator;
  $('pageImage').src = page && !locator ? `/api/page-image?id=${encodeURIComponent(page.page_id)}` : '';
  $('pageImage').style.transform = `scale(${state.zoom})`;
  $('zoomValue').textContent = `${Math.round(state.zoom * 100)}%`;
}

$('sourceSelect').onchange = (event) => loadSource(event.target.value).catch((error) => notice(error.message, true));
$('saveCitationMetadata').onclick=async()=>{
  const sourceId=state.view?.source?.source_id;if(!sourceId){notice('请先打开一份项目文献。',true);return;}
  try{
    await request('/api/source/citation-metadata',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      source_id:sourceId,author:$('citationAuthor').value,title:$('citationTitle').value,
      edition:$('citationEdition').value,translator:$('citationTranslator').value,
      place:$('citationPlace').value,publisher:$('citationPublisher').value,
      year:$('citationYear').value,type_code:$('citationTypeCode').value,
      journal:$('citationJournal').value,volume:$('citationVolume').value,issue:$('citationIssue').value,
      page_range:$('citationPageRange').value,verified_by:$('citationVerifiedBy').value,
    })});
    await loadSource(sourceId,true);notice('引文元数据已人工核验；导出仍会逐条检查原书页码。');
  }catch(error){notice(error.message,true);}
};
function setMode(mode) {
  $('libraryWorkbench').hidden = mode !== 'library';
  $('agentWorkbench').hidden = mode !== 'agent';
  $('articleWorkbench').hidden = mode !== 'article';
  $('pdfWorkbench').hidden = mode !== 'source';
  $('browserWorkbench').hidden = mode !== 'browser';
  $('settingsWorkbench').hidden = mode !== 'settings';
  $('skillsWorkbench').hidden = mode !== 'skills';
  $('libraryMode').classList.toggle('mode-active', mode === 'library');
  $('agentMode').classList.toggle('mode-active', mode === 'agent');
  $('articleMode').classList.toggle('mode-active', mode === 'article');
  $('settingsMode').classList.toggle('mode-active', mode === 'settings');
  $('skillsMode').classList.toggle('mode-active', mode === 'skills');
  if (mode === 'settings') renderSettings();
  if (mode === 'skills') renderSkillCatalog();
  if (mode === 'browser') renderBrowserControls();
}
$('libraryMode').onclick = () => setMode('library');
$('agentMode').onclick = () => setMode('agent');
$('articleMode').onclick = () => { setMode('article'); renderAuthoring(); };
$('skillsMode').onclick = () => setMode('skills');
$('settingsMode').onclick = () => setMode('settings');
$('skillQuery').oninput=renderSkillCatalog;
$('messageInput').oninput=renderSlashMenu;
$('openSourceRepair').onclick = async () => {
  const sourceId = $('sourceSelect').value;
  if (!sourceId) { notice('当前项目还没有可复核的文献。', true); return; }
  if (state.view?.source?.source_id !== sourceId) await loadSource(sourceId);
  setMode('source');
};
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
$('insertSection').onclick=async()=>{
  if(!state.document||!documentSection()){notice('请先选择稿件章节。',true);return;}
  const heading=window.prompt('新章节标题','摘要与关键词');if(!heading?.trim())return;
  const tree=structuredClone(state.document.document);const currentIndex=tree.children.findIndex((item)=>item.section_id===state.sectionId);
  const nodeId=`NOD_${crypto.randomUUID().replaceAll('-', '')}`;
  tree.children.splice(Math.max(0,currentIndex),0,{type:'section',node_id:nodeId,section_id:'',heading:heading.trim(),children:[{type:'paragraph',node_id:`NOD_${crypto.randomUUID().replaceAll('-', '')}`,text:''}]});
  const result=await request('/api/manuscript/document/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,document:tree})});
  const created=result.document.children.find((item)=>item.node_id===nodeId);state.document=result;state.documentManuscriptId=state.manuscriptId;state.sectionId=created?.section_id||result.document.children[0]?.section_id||'';state.proposalId='';sessionStorage.setItem('hrwSectionId',state.sectionId);
  await refreshAuthoring('新章节已加入当前章节之前；填写后点击“保存新修订”。');
};
$('insertSectionAfter').onclick=async()=>{
  if(!state.document||!documentSection()){notice('请先选择稿件章节。',true);return;}
  const heading=window.prompt('新章节标题','英文题名、摘要与关键词');if(!heading?.trim())return;
  const tree=structuredClone(state.document.document);const currentIndex=tree.children.findIndex((item)=>item.section_id===state.sectionId);
  const nodeId=`NOD_${crypto.randomUUID().replaceAll('-', '')}`;
  tree.children.splice(currentIndex+1,0,{type:'section',node_id:nodeId,section_id:'',heading:heading.trim(),children:[{type:'paragraph',node_id:`NOD_${crypto.randomUUID().replaceAll('-', '')}`,text:''}]});
  const result=await request('/api/manuscript/document/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,document:tree})});
  const created=result.document.children.find((item)=>item.node_id===nodeId);state.document=result;state.documentManuscriptId=state.manuscriptId;state.sectionId=created?.section_id||result.document.children.at(-1)?.section_id||'';state.proposalId='';sessionStorage.setItem('hrwSectionId',state.sectionId);
  await refreshAuthoring('新章节已加入当前章节之后；填写后点击“保存新修订”。');
};
$('insertTable').onclick = () => {
  if (!documentSection()) { notice('请先选择稿件章节。', true); return; }
  const columnInput=window.prompt('表格列数（2—8）','4');if(columnInput===null)return;
  const columns=Math.min(8,Math.max(2,Number.parseInt(columnInput,10)||4));
  const rowInput=window.prompt('表格总行数，包含表头（2—30）','5');if(rowInput===null)return;
  const rows=Math.min(30,Math.max(2,Number.parseInt(rowInput,10)||5));
  const table=document.createElement('table');table.dataset.nodeId=`NOD_${crypto.randomUUID().replaceAll('-', '')}`;table.dataset.nodeType='table';
  const body=document.createElement('tbody');
  for(let row=0;row<rows;row++){const tr=document.createElement('tr');for(let column=0;column<columns;column++){const cell=document.createElement(row===0?'th':'td');cell.textContent=row===0?`列${column+1}`:'';tr.append(cell);}body.append(tr);}table.append(body);$('documentCanvas').append(table);table.querySelector('th')?.focus();
  notice('表格已插入当前章节；填写后点击“保存新修订”。表题和来源说明请另起正文段落。');
};
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
    state.threadId = ''; state.thread = null; state.view = null; state.libraryWork = null; state.libraryWorkId = ''; state.manuscriptId=''; state.sectionId=''; sessionStorage.removeItem('hrwManuscriptId');sessionStorage.removeItem('hrwSectionId');
    await loadSnapshot(); setMode('agent'); notice('已切换项目；对话和研究对象按项目隔离。');
  } catch (error) { notice(error.message, true); }
};
$('newProject').onclick = async () => {
  const title = window.prompt('新项目名称', '新的历史研究项目'); if (!title?.trim()) return;
  try {
    await request('/api/project/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    state.threadId = ''; state.thread = null; state.view = null; state.libraryWork = null; state.libraryWorkId = ''; state.manuscriptId=''; state.sectionId=''; sessionStorage.removeItem('hrwManuscriptId');sessionStorage.removeItem('hrwSectionId');
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
$('libraryShelf').onchange = () => renderWorkList();
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
$('planningMode').onchange = (event) => {
  state.planningMode = event.target.value;
  sessionStorage.setItem('hrwPlanningMode', state.planningMode);
  notice(state.planningMode === 'independent_planning'
    ? '独立构思：本次运行不会把研究者意图基线、共同研究设计或旧线程对话发给模型。'
    : '按计划执行：本次运行会加载共同批准计划和最近的有界线程对话；对话不是来源证据。');
};
$('sendMessage').onclick = async () => {
  const content = $('messageInput').value.trim();
  if (!state.threadId) { notice('请先创建一个研究线程。', true); return; }
  if (!content) { notice('请输入研究任务。', true); return; }
  $('sendMessage').disabled = true;
  const threadId = state.threadId;
  let polling = false;
  const progressTimer = setInterval(async () => {
    if (polling) return;
    polling = true;
    try { await pollActiveThread(threadId); }
    catch (error) { console.warn('Run progress refresh failed', error); }
    finally { polling = false; }
  }, 1000);
  try {
    notice('Agent 正在读取项目并调用工具……');
    state.thread = await request('/api/agent/message', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({thread_id:threadId, content, planning_mode:state.planningMode})});
    $('messageInput').value = ''; await refreshAgentSnapshot(); notice(latestRun()?.status === 'WAITING_FOR_APPROVAL' ? 'Agent 已暂停，等待你检查右侧提案。' : '本次运行已完成。');
  } catch (error) {
    try { await refreshAgentSnapshot(); } catch (refreshError) { console.warn('Failed run refresh failed', refreshError); }
    notice(error.message, true);
  }
  finally { clearInterval(progressTimer); $('sendMessage').disabled = false; }
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
setMode(['agent', 'article', 'library', 'skills', 'settings', 'browser', 'source'].includes(initialMode) ? initialMode : 'agent');
loadSnapshot().then(() => notice('对话工作台已就绪。')).catch((error) => notice(error.message, true));
