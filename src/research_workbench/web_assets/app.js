const state = {
  snapshot: null, capabilities: null, view: null, thread: null, threadId: '', pageIndex: 0, zoom: 1,
  libraryScan: null, libraryScanPage: 1, libraryWorks: [], libraryWork: null,
  libraryWorkId: '', libraryWorkLoading: false, libraryWorkRequestToken: 0,
  libraryView: sessionStorage.getItem('wenjinLibraryView') || 'list',
  libraryGraphQuery: '',
  contextMode: 'sources', retrievalRecord: null,
  manuscriptId: sessionStorage.getItem('hrwManuscriptId') || '',
  sectionId: sessionStorage.getItem('hrwSectionId') || '', authoringMode: 'dialogue', proposalId: '',
  document: null, documentManuscriptId: '', selection: null, writingSelection: null, browserSession: null,
  modelSettings: null, sessionToken: '', lastDocxExport: '', nativeBridge: '',
  mainDiscoveredModels: [], mainModelDiscoveryKey: '',
  projectWorkspace: null,
  domainAgents: null, domainSessionId: '', domainView: null,
  pendingAttachments: [], domainPendingAttachments: [], domainDraft: '',
  eventFreezeDraft: [],
  chronicleViewName: '',
  historiographyEntryIds: JSON.parse(sessionStorage.getItem('hrwHistoriographyEntryIds') || '{}'),
  planningMode: sessionStorage.getItem('hrwPlanningMode') || 'independent_planning',
  accessMode: sessionStorage.getItem('wenjinAgentAccessMode')==='full_project'?'full_computer':(sessionStorage.getItem('wenjinAgentAccessMode') || 'ask'),
  reasoningMode: sessionStorage.getItem('wenjinReasoningMode') || 'standard',
  reasoningEffort: sessionStorage.getItem('wenjinReasoningEffort') || 'medium',
  domainReasoningMode: sessionStorage.getItem('wenjinDomainReasoningMode') || 'standard',
  domainReasoningEffort: sessionStorage.getItem('wenjinDomainReasoningEffort') || 'medium',
  language: localStorage.getItem('wenjinLanguage') || 'zh-CN',
  settingsTab: sessionStorage.getItem('wenjinSettingsTab') || 'models',
  editorZoom:Number(localStorage.getItem('wenjinEditorZoom')||1), editorDirty:false, readingMode:false,
};
if(state.settingsTab==='plugins')state.settingsTab='models';
const $ = (id) => document.getElementById(id);
const translations={
  'zh-CN':{nav_agent:'研究对话',nav_project:'项目工作区',nav_domain:'领域 Agent',nav_library:'研究图书馆',nav_article:'文章工作台',nav_skills:'技能与插件',nav_settings:'AI 与 Agent',tagline:'人文社会科学研究工作台',settings:'AI 与 Agent',settings_lead:'主模型、辅助模型、MoA、研究人格、记忆与连接器'},
  en:{nav_agent:'Research chat',nav_project:'Project workspace',nav_domain:'Domain agents',nav_library:'Research library',nav_article:'Writing studio',nav_skills:'Skills & plugins',nav_settings:'AI & Agent',tagline:'Humanities and social science research workbench',settings:'AI & Agent',settings_lead:'Main and auxiliary models, MoA, research persona, memory, and connectors'},
};
const exactUiEnglish=new Map(Object.entries({
  '当前项目':'Current project','新建项目':'New project','研究线程':'Research threads','主模型':'Main model','发送':'Send',
  '项目工作区已就绪。':'Project workspace ready.',
  '研究上下文':'Research context','项目材料与研究记录':'Project materials and research records','项目文献':'Project sources','研究计划':'Research plan',
  '逐事件表':'Event register','图书馆':'Library','联网研究':'Web research','证据与论点':'Evidence and claims','冻结与写作':'Evidence freeze and writing',
  '研究浏览器':'Research browser','记忆候选':'Memory candidates','暂无待处理事项。':'No pending action.','运行与工具回执':'Run and tool receipts',
  '查看原页与文本':'View original page and text','标记整份文件不符':'Reject document identity','研究图书馆':'Research library',
  '全部书架':'All shelves','原始史料':'Primary sources','学术论文':'Articles','学术专著':'Monographs','个人论文与稿件':'Personal papers and drafts','读书笔记':'Reading notes',
  '工具书与目录':'Reference works and catalogs','待分类':'Unclassified','检索':'Search','图书馆还没有已批准材料。盘点不会自动入库。':'No approved library item yet. Inventory does not register files automatically.',
  '作品与版本':'Works and versions','文件指纹只标识精确文件版本':'File fingerprints identify exact file versions','当前项目文献':'Current project sources',
  '稿件与章节':'Manuscripts and sections','稿件结构与历史版本':'Manuscript structure and revision history','新建或导入稿件':'Create or import manuscript',
  '选择一个章节':'Choose a section','人工保存后才产生新修订':'A new revision is created only after an explicit save','稿件题名':'Manuscript title','正文':'Main text',
  '引文':'Citation','在此之前新增章节':'Insert section before','在此之后新增章节':'Insert section after','插入表格':'Insert table','插入注释':'Insert note',
  '阅读模式':'Reading mode','保存新修订':'Save new revision','投稿模板':'Submission template','导出 Markdown':'Export Markdown','导出 Word':'Export Word',
  '对照待审写作提案':'Compare pending writing proposal','尚未选择稿件':'No manuscript selected','研究侧栏':'Research sidebar',
  '研究对话':'Research dialogue','润色/分节':'Revision and section drafting','注释':'Notes','证据/主张':'Evidence and claims','批量阅读':'Batch reading',
  '学术史':'Historiography','多角色评审':'Multi-role review','期刊模板':'Journal templates','版本':'Versions','材料闭环':'Research material closure',
  '新建稿件讨论线程':'New manuscript discussion thread','带上下文发送':'Send with context','上下文边界':'Context boundary',
  '技能与插件库':'Skills and integrations','研究技能、内部流程和外部工具分开列出':'Research skills, internal workflows, and external tools are listed separately.',
  '研究技能':'Research skills','内部研究流程':'Internal research workflows','外部工具连接':'External integrations',
  '由研究阶段和权限自动触发，不提供直接按钮。':'Triggered by research stage and permissions; no direct button.',
  '由对应页面调用，不混入研究动作。':'Invoked from its owning workspace, not mixed into research actions.',
  '请求批准':'Ask for approval','帮我批准':'Auto-approve','完全访问':'Full access','Agent 权限':'Agent access',
  '配置模型':'Configure model','推理模式':'Reasoning mode','思考强度':'Reasoning effort','标准':'Standard','深度推理':'Deep reasoning','低':'Low','中':'Medium','高':'High','权限':'Access',
  '选择稿件章节后开始编辑。':'Choose a manuscript section to begin editing.','当前稿件、修订、章节与选区会随消息保存':'The current manuscript, revision, section, and selection are saved with the message.',
  '继续研究｜尚未达到正式写作条件':'Continue research | formal drafting is not ready','尚无人工批准的共同研究设计':'No human-approved shared research design',
  '同一个项目主 Agent':'Same project main Agent','选择研究线程':'Choose research thread','围绕当前章节或选区讨论':'Discuss the current section or selection',
  '稿件 — 修订 — 章节 — 灵感讨论默认只留在对话。':'Manuscript — revision — section — exploratory discussion remains in the thread by default.',
  '选择一部作品，查看完整书目信息、文件位置与每一次精确版本。':'Choose a work to inspect its bibliography, file locations, and exact versions.',
  '打开原页与文本复核':'Open original page and text','修复是具体文件版本的下属动作；旧项目处理记录暂以兼容方式读取。':'Repairs belong to an exact file version; legacy project records are read through the compatibility layer.',
  '模型':'Models','辅助与 MoA':'Routing and MoA','研究人格':'Persona','记忆':'Memory','连接器、MCP与微信':'Connectors, MCP & Weixin','领域包':'Domain packs','当前状态':'Status'
  ,'本轮使用':'Run context','只处理当前问题':'Current question only','沿用已批准研究计划':'Use approved research plan'
  ,'只读盘点':'Read-only inventory','从电脑选择 PDF':'Choose PDF from computer','导入、清洗并登记页面关系':'Import, process, and register pages','手动上传到图书馆':'Upload to library','从电脑选择文件夹':'Choose folder from computer','只读盘点，先不入库':'Inventory only; do not register yet','上一页':'Previous','下一页':'Next','批准所选材料原地入库':'Approve selected files in place','按建议分类并批量入库':'Classify suggestions and register in bulk'
  ,'单份 PDF（项目私有兼容导入）':'Single PDF (project-private compatibility import)','材料所在文件夹':'Folder containing materials','验收 Skill':'Intake Skill','书架（人工移动，不改变引用资格）':'Shelf (manual; does not change citation eligibility)','作品题名':'Work title','作者 / 责任者':'Author / responsible person','语言':'Language','材料类型':'Material type','版本说明':'Edition note','出版社 / 期刊名':'Publisher / journal','出版者':'Publisher','出版年':'Publication year','用户标签（逗号分隔）':'User tags (comma-separated)','移动到所选书架':'Move to selected shelf','保存人工书目':'Save verified bibliography','关联到当前项目':'Link to current project','加入当前项目文献':'Add to current project sources'
  ,'导入并按标题分节':'Import and split by headings','从电脑选择 Word 稿':'Choose Word manuscript','导入 DOCX（生成保真报告）':'Import DOCX and create fidelity report','在 Microsoft Word 中打开':'Open in Microsoft Word','导回 Word 修改稿':'Reimport edited Word file','Markdown 正文':'Markdown body','或选择 DOCX':'or choose DOCX'
  ,'物理页':'Physical pages','页码':'Page','跳转':'Go','← 返回图书馆':'← Back to library','尚未导入文献':'No source imported',
  '原 PDF 页面与文本块':'Original PDF page and text blocks','提取文本':'Extracted text','等待材料':'Waiting for source','复核人':'Reviewer',
  '修正依据':'Basis for correction','印刷页码':'Printed page','保存页码关系':'Save page mapping','模型修复建议':'Model repair suggestions',
  '正在检查视觉模型……':'Checking the vision model…','确认本页与原图一致':'Confirm page against image','跨页关系':'Cross-page relations',
  '待复核项':'Open review items','按双栏阅读顺序重排':'Reorder as two-column reading','在本页新增一块':'Add a block on this page',
  '保存整页结构修正':'Save page-structure repair','提交整页修正':'Submit page repair','确认续接':'Confirm continuation',
  '确认不续接':'Confirm no continuation','保存关系更正':'Save relation correction','当前没有待复核项。':'No open review item.',
  '当前页没有跨页关系。':'No cross-page relation on this page.'
}));
const exactUiChinese=new Map([...exactUiEnglish].map(([zh,en])=>[en,zh]));
const ariaUiEnglish=new Map(Object.entries({
  '图书馆子页面':'Library views','选择项目文献':'Choose project source','稿件题名':'Manuscript title',
  '结构化稿件编辑区':'Structured manuscript editor','AI 与 Agent 子页面':'AI and Agent views',
  '当前图书馆知识图谱':'Current library knowledge graph'
}));
const ariaUiChinese=new Map([...ariaUiEnglish].map(([zh,en])=>[en,zh]));
function translateExactUi(root=document.body){
  if(!root)return;
  const dictionary=state.language==='en'?exactUiEnglish:exactUiChinese;
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  const nodes=[];let node;
  while(node=walker.nextNode())nodes.push(node);
  for(const textNode of nodes){
    if(textNode.parentElement?.closest('.messages,#documentCanvas,pre,code,textarea,input,[contenteditable="true"]'))continue;
    const raw=textNode.nodeValue||'',trimmed=raw.trim(),translated=dictionary.get(trimmed);
    if(translated)textNode.nodeValue=raw.replace(trimmed,translated);
  }
}
function applyLanguage(){
  const strings=translations[state.language]||translations['zh-CN'];
  for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=strings[node.dataset.i18n]||node.textContent;
  $('brandTagline').textContent=strings.tagline;$('settingsHeading').textContent=strings.settings;$('settingsLead').textContent=strings.settings_lead;
  $('languageToggle').textContent=state.language==='zh-CN'?'EN':'中文';
  $('messageInput').placeholder=state.language==='en'?'For example: inspect the current source and anomalies, then save a bounded research note.':'例如：查看当前来源和异常，并把结论保存为研究札记';
  $('domainImportPath').placeholder=state.language==='en'?'Choose a .zip package or extracted folder':'选择 .zip 或已解压目录';
  $('domainAgentIdea').placeholder=state.language==='en'?'For example: I want an inscription agent that reads rubbings, segments records, verifies places, and exports a table.':'例如：我想创建一个碑刻整理 Agent。我有若干拓片和释文，希望它能识字、拆条、核地名并导出表格。';
  $('domainMessageInput').placeholder=state.language==='en'?'Ask the current domain agent directly':'直接向当前领域 Agent 提出任务';
  $('libraryQuery').placeholder=state.language==='en'?'Title, author, publisher, tag, or leading text':'题名、作者、出版社、标签或前段文本';
  $('skillQuery').placeholder=state.language==='en'?'Search skills, artifacts, or Agent integrations':'搜索技能、产物或 Agent 程序';
  $('pageJump').placeholder=state.language==='en'?'Page':'页码';
  $('reason').placeholder=state.language==='en'?'For example: checked character by character against this page':'例如：逐字核对当前原页';
  $('printedPage').placeholder=state.language==='en'?'Read from the original header or footer':'按原页页眉或页脚填写';
  for(const node of document.querySelectorAll('[data-zh][data-en]'))if(!node.classList.contains('sidebar-toggle'))node.textContent=state.language==='en'?node.dataset.en:node.dataset.zh;
  for(const node of document.querySelectorAll('.sidebar-toggle')){const collapsed=node.closest('main')?.classList.contains('right-collapsed'),label=state.language==='en'?(collapsed?'Show sidebar':'Hide sidebar'):(collapsed?'显示侧栏':'隐藏侧栏');node.textContent=collapsed?'‹':'›';node.title=label;node.setAttribute('aria-label',label);}
  const ariaDictionary=state.language==='en'?ariaUiEnglish:ariaUiChinese;
  for(const node of document.querySelectorAll('[aria-label]')){
    const translated=ariaDictionary.get(node.getAttribute('aria-label'));
    if(translated)node.setAttribute('aria-label',translated);
  }
  document.documentElement.lang=state.language;
  queueMicrotask(()=>translateExactUi());
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(friendlyError(data.error || `请求失败：${response.status}`));
  if(url==='/api/project/create'&&String(options.body||'').includes('领域 Agent｜')){state.threadId='__creating_domain_agent__';state.thread=null;}
  return data;
}

function friendlyError(message) {
  const text=String(message||'未知错误');
  if(/exhausted (?:its )?tool(?:-call)? budget|tool budget/i.test(text))return '多次纠正工具调用后仍未完成；已停止重复尝试，请检查本轮最后一条工具回执。';
  if(/unknown M4 tool|domain tool is not allowlisted/i.test(text))return '模型请求了当前未安装或未授权的工具；系统已停止该调用。';
  if(/domain subagent/i.test(text))return text.replace(/domain subagent/ig,'领域 Agent');
  if(/TOOL_RESULT|tool[_ -]?call|tool action|invalid model action|valid JSON object|malformed (?:action|parameters)|tagged invoke|dsml|internal tool transcript|模型操作格式/i.test(text)){
    return /retry|重试|shorter valid JSON/i.test(text)
      ? '模型操作格式错误，系统已自动重试一次。'
      : '模型操作格式错误；本次运行未能完成，请重新发送请求。';
  }
  return /database\s+is\s+locked|database\s+table\s+is\s+locked/i.test(text)
    ? `本地数据库正被另一项操作占用（database locked）。请等待当前写入结束后重试；若持续出现，请关闭重复打开的工作台再重试。原始错误：${text}`
    : text;
}

function publicMessageText(message) {
  const text=String(message?.content?.text||'').replace(/^\s*(?:final\s+(?:answer|response)|assistant\s+final|最终(?:回答|答复))\s*:\s*/i,'');
  if(message?.role==='assistant'&&/TOOL_RESULT|<tool_call|<invoke|<｜DSML｜|tool_calls?\s*[:=]/i.test(text)){
    return '模型返回了内部工具格式内容，未直接展示。请查看本次运行状态；系统会自动重试一次，失败后可重新发送。';
  }
  return text;
}

function publicEventTitle(eventType) {
  if(eventType==='run_started')return '开始处理';
  if(eventType==='tool_started')return '正在使用工具';
  if(eventType==='tool_completed')return '工具已返回';
  if(eventType==='approval_requested')return '等待操作批准';
  if(eventType==='approval_auto_decided')return '已按当前权限批准';
  if(eventType==='run_completed')return '处理完成';
  if(eventType==='model_action_invalid')return '模型格式校验';
  if(eventType==='model_response_empty')return '模型未返回正文';
  if(eventType==='model_request_retry')return '连接波动，正在重试';
  if(eventType==='tool_correction_requested')return '工具参数纠正';
  if(eventType==='tool_retry_blocked')return '重复失败已停止';
  if(eventType==='run_failed')return '运行失败';
  if(eventType==='domain_run_started')return '领域Agent开始处理';
  if(eventType==='domain_tool_started')return '领域Agent正在调用工具';
  if(eventType==='domain_tool_progress')return '领域工具进度';
  if(eventType==='domain_tool_completed')return '领域工具已返回';
  if(eventType==='domain_run_completed')return '领域Agent处理完成';
  if(eventType==='domain_run_failed')return '领域Agent处理失败';
  return '';
}

function publicToolName(tool){
  const labels={
    'project.status':'读取项目状态','attachment.inspect':'读取附件','domain_agent.consult':'咨询领域 Agent',
    'computer.roots':'读取文件系统位置','computer.file_search':'查找本地文件','computer.windows':'查看窗口',
    'computer.snapshot':'读取界面','computer.capture':'截取屏幕','computer.run':'运行本地程序',
    'research.search':'联网学术检索','retrieval.list':'读取检索记录','browser.start':'打开网页',
    'browser.read':'读取网页','browser.open':'网页内导航','skill.list':'查看技能','skill.read':'读取技能',
    'skill.create':'创建技能','domain_pack.create':'创建领域 Agent 工程','save_research_note':'保存研究札记'
  };
  return labels[tool]||tool;
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

function setAuthoringRefreshBusy(busy) {
  const workbench=$('articleWorkbench');
  if(!workbench)return;
  workbench.inert=busy;
  workbench.setAttribute('aria-busy',busy?'true':'false');
  if(busy)notice('正在保存人工决定并刷新写作区；完成前暂不可编辑或重新选区。');
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
  const mainRole=modelSettings.roles?.find((item)=>item.role==='main_reasoning');
  const discoveryKey=mainRole?`${mainRole.provider}|${mainRole.base_url}`:'';
  if(mainRole&&['ollama','openai_compatible'].includes(mainRole.provider)&&mainRole.base_url&&state.mainModelDiscoveryKey!==discoveryKey){
    try{const found=await request('/api/model-settings/models',localSessionOptions({role:'main_reasoning',provider:mainRole.provider,base_url:mainRole.base_url,api_key:''}));state.mainDiscoveredModels=found.models||[];state.mainModelDiscoveryKey=discoveryKey;}catch{state.mainDiscoveredModels=[];state.mainModelDiscoveryKey=discoveryKey;}
  }
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
    select.append(new Option(state.language==='en'?'No source yet':'尚无文献', ''));
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
  same_work: '同一作品的新文件', same_scan_work:'同批次同一作品',
  unchanged: '内容未变化', error: '读取失败',
};
const triageLabels = {
  likely_historical: '较可能是历史材料', uncertain: '需要人工判断', needs_visual_triage: '需要查看原页',
  word_review:'Word待人工选择', not_obviously_historical: '暂未发现历史线索', unsupported: '当前不解析', error: '读取失败',
};

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

function renderLibraryShell() {
  const library = state.snapshot?.library;
  const english=state.language==='en';
  $('libraryRoot').textContent = library ? `${english?'Index location: ':'索引位置：'}${library.library_root}` : (english?'Library not initialized':'图书馆尚未初始化');
  const counts = library?.counts || {};
  $('libraryCounts').textContent = english?`${counts.works || 0} works · ${counts.library_files || 0} file locations · ${counts.file_versions || 0} exact versions`:`${counts.works || 0} 部作品 · ${counts.library_files || 0} 个文件位置 · ${counts.file_versions || 0} 个精确版本`;
  const shelfEnglish={primary_sources:'Primary sources',academic_articles:'Articles',monographs:'Monographs',personal_manuscripts:'Personal papers and drafts',reading_notes:'Reading notes',reference_works:'Reference works and catalogs',unclassified:'Unclassified'};
  const shelfSelect=$('libraryShelf');const selectedShelf=shelfSelect.value;shelfSelect.replaceChildren(new Option(english?'All shelves':'全部书架',''));
  for(const [value,label] of Object.entries(state.snapshot.library_shelves||{})) shelfSelect.append(new Option(english?(shelfEnglish[value]||value):label,value));
  shelfSelect.value=selectedShelf;
  const skills = $('intakeSkill'); skills.replaceChildren();
  for (const skill of (library?.skills || []).filter((item)=>item.compatible_actions?.includes('library_intake'))) {
    const option = new Option(`${skill.name} · ${skill.execution}`, skill.name);
    option.title = skill.description; skills.append(option);
  }
  renderScan(); renderWorkList(); renderWorkDetail();
  setLibraryView(state.libraryView);
  if (!state.libraryWorkId && state.libraryWorks.length) {
    loadWork(state.libraryWorks[0].work_id).catch((error) => notice(error.message, true));
  }
}

function renderScan() {
  const summary = $('scanSummary'); const container = $('scanCandidates');
  summary.replaceChildren(); container.replaceChildren();
  if (!state.libraryScan) {
    summary.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'填写一个明确文件夹后，系统先生成候选清单。'}));
    $('approveCandidates').hidden = true; $('approveAllCandidates').hidden = true; return;
  }
  const scan = state.libraryScan;
  const heading = document.createElement('article'); heading.className = 'scan-receipt';
  const statusLabels={scanning:'盘点中',preview_ready:'等待选择',failed:'盘点失败',partially_approved:'部分已入库',approved:'已完成'};
  const title = document.createElement('strong');
  title.textContent = `${scan.total_count || 0} 个候选 · ${statusLabels[scan.status] || scan.status}`;
  const skill = document.createElement('small'); skill.textContent = scan.skill_name;
  const root = document.createElement('small'); root.textContent = scan.root_path;
  heading.append(title, skill, root); summary.append(heading);
  if(Number(scan.ignored_word_count||0)>0){const ignored=document.createElement('p');ignored.className='boundary-note';ignored.textContent=`另有 ${scan.ignored_word_count} 个行政、模板、写作碎片或临时 Word 已从候选列表隐藏；单独上传仍可纳入。`;summary.append(ignored);}
  if(Number(scan.word_review_count||0)>0){const review=document.createElement('p');review.className='boundary-note';review.textContent=`${scan.word_review_count} 个论文稿、研究稿或读书笔记进入 Word 待选区，默认不勾选，也不参加一键批量入库；请先比较正文和版本。`;summary.append(review);}
  if(scan.status==='scanning'){
    const progress=document.createElement('p');progress.className='boundary-note';
    progress.textContent=`后台只读盘点进行中，已检查 ${scan.processed_count || 0} 个候选。可以离开此页，刷新后仍会恢复进度。`;
    summary.append(progress);
  }else if(scan.status==='failed'){
    const failure=document.createElement('p');failure.className='boundary-note';
    failure.textContent=`盘点未完成：${scan.error || '未知错误'}。已经发现的候选仍保留在本次收据中。`;
    summary.append(failure);
  }
  const unsupported = scan.candidates.filter((item) => item.triage_state === 'unsupported');
  if (unsupported.length) {
    const formats = Object.entries(unsupported.reduce((result, item) => {
      result[item.format] = (result[item.format] || 0) + 1; return result;
    }, {})).map(([format, count]) => `${format.toUpperCase()} ${count}`).join(' · ');
    const note = document.createElement('p'); note.className = 'boundary-note';
    note.textContent = `本页 ${unsupported.length} 个当前不解析的文件已保留在盘点收据中，不在此展开：${formats}`;
    summary.append(note);
  }
  let selectable = 0;
  for (const candidate of scan.candidates.filter((item) => item.triage_state !== 'unsupported')) {
    const card = document.createElement('article'); card.className = `candidate ${candidate.triage_state}`;
    const check = document.createElement('input'); check.type = 'checkbox'; check.dataset.candidateId = candidate.candidate_id;
    check.disabled = candidate.status !== 'preview' || ['unsupported', 'error', 'unchanged'].includes(candidate.triage_state) || candidate.proposed_action === 'unchanged';
    check.checked = !check.disabled && candidate.triage_state!=='word_review'; if (!check.disabled) selectable += 1;
    const body = document.createElement('div');
    const resolved=!!candidate.resolved_work_id;
    const name = document.createElement('strong'); name.textContent = resolved?candidate.resolved_work_title:candidate.suggested_title;
    const action=resolved?(Number(candidate.resolved_file_count)>1?'已并入同一作品':'已入库'):actionLabels[candidate.proposed_action] || candidate.proposed_action;
    const shelfLabel=resolved?(candidate.resolved_shelf_label||'待分类'):(candidate.suggested_shelf_label||'待分类');
    const meta = document.createElement('small'); meta.textContent = `${action} · ${triageLabels[candidate.triage_state] || candidate.triage_state} · ${resolved?'所在书架':'建议书架'}：${shelfLabel} · ${candidate.format.toUpperCase()} · ${formatBytes(candidate.byte_count)}`;
    const bibliography = document.createElement('small'); bibliography.textContent = [resolved?candidate.resolved_work_author:candidate.suggested_author || '责任者待核', resolved?candidate.resolved_year:candidate.suggested_year || '年代待核', resolved?candidate.resolved_publisher:candidate.suggested_publisher || '出版信息待核'].map((value,index)=>value||['责任者待核','年代待核','出版信息待核'][index]).join(' · ');
    const reason = document.createElement('p'); reason.textContent = candidate.triage_reason;
    const path = document.createElement('small'); path.className = 'path'; path.textContent = candidate.path;
    const exact = document.createElement('details');
    const exactTitle = document.createElement('summary'); exactTitle.textContent = '精确盘点信息';
    const exactText = document.createElement('pre'); exactText.textContent = `${state.language==='en'?'Exact file version recorded':'已记录精确文件版本'}\n${state.language==='en'?'Physical pages':'物理页'}  ${candidate.page_count ?? (state.language==='en'?'not applicable':'不适用')}\n${state.language==='en'?'Pages inspected':'已检查页'}  ${candidate.inspected_pages}\n${state.language==='en'?'Text layer':'文本层'}  ${candidate.text_layer}\n${state.language==='en'?'File time':'文件时间'}  ${new Date(candidate.modified_ns / 1e6).toLocaleString()}${candidate.error ? `\n${state.language==='en'?'Error':'错误'}  ${candidate.error}` : ''}`;
    exact.append(exactTitle, exactText); body.append(name, meta, bibliography, reason, path, exact); card.append(check, body); container.append(card);
  }
  const pages=document.createElement('div');pages.className='row';
  const previous=document.createElement('button');previous.textContent='上一页';previous.disabled=(scan.page || 1)<=1;
  previous.onclick=()=>loadLibraryScan(scan.session_id,(scan.page || 1)-1).catch((error)=>notice(error.message,true));
  const position=document.createElement('small');position.textContent=`第 ${scan.page || 1} / ${Math.max(scan.page_count || 0,1)} 页 · 每页最多 ${scan.page_size || 50} 条`;
  const next=document.createElement('button');next.textContent='下一页';next.disabled=!scan.has_more;
  next.onclick=()=>loadLibraryScan(scan.session_id,(scan.page || 1)+1).catch((error)=>notice(error.message,true));
  pages.append(previous,position,next);summary.append(pages);
  $('approveCandidates').hidden = scan.status==='scanning' || scan.status==='failed' || selectable === 0;
  $('approveAllCandidates').hidden = scan.status==='scanning' || scan.status==='failed' || Number(scan.eligible_remaining_count || 0) === 0;
}

const svgElement=(name)=>document.createElementNS('http://www.w3.org/2000/svg',name);
function renderInteractiveGraph(container,nodes,edges,{background='#f2eee6',onOpen=()=>{},className=''}={}){
  if(!window.cytoscape||!nodes?.length)return false;
  const relationNames=state.language==='en'?{same_author:'Same author',same_publisher:'Same publisher',same_journal:'Same journal',authored_by:'Authored by',published_by:'Published by',published_in_year:'Publication year',material_type:'Material type',tagged_as:'Tagged as',shelved_as:'Shelved as',cites:'Citation',uses_material_from:'Material use',reviews:'Review',translates:'Translation',mentions_work:'Mention'}:{same_author:'同作者',same_publisher:'同出版社',same_journal:'同期刊',authored_by:'作者',published_by:'出版者/期刊',published_in_year:'出版年',material_type:'材料类型',tagged_as:'标签',shelved_as:'书架',cites:'引用',uses_material_from:'使用其材料',reviews:'评述',translates:'翻译',mentions_work:'提及'};
  const relationPriority=['cites','uses_material_from','reviews','translates','mentions_work','authored_by','published_by','same_author','same_journal','same_publisher','published_in_year','material_type','tagged_as','shelved_as'];
  const groupedEdges=new Map();for(const edge of edges){const key=[edge.source_node_id,edge.target_node_id].sort().join('\u0000');if(!groupedEdges.has(key))groupedEdges.set(key,[]);groupedEdges.get(key).push(edge);}
  const renderedEdges=[...groupedEdges.values()].map((items,index)=>{const ordered=[...items].sort((left,right)=>relationPriority.indexOf(left.relation)-relationPriority.indexOf(right.relation)),primary=ordered[0],relations=[...new Set(items.map(item=>item.relation))];return {data:{id:`edge-${index}`,source:primary.source_node_id,target:primary.target_node_id,label:relations.map(value=>relationNames[value]||value).join(' + '),display:'',relation:primary.relation||'',relations,rawEdges:items,composite:relations.length>1},classes:relations.length>1?'composite':''};});
  const graphInstructions=state.language==='en'?'Wheel to zoom · drag background or middle-drag to pan · hover for title · double-click for details':'滚轮缩放 · 拖动空白处或中键平移 · 悬停看题名 · 双击看详情';const toolbar=document.createElement('div');toolbar.className='graph-toolbar';const graphHint=Object.assign(document.createElement('span'),{textContent:state.language==='en'?'Arranging graph…':'正在整理图谱……'});toolbar.append(graphHint);
  const stage=document.createElement('div');stage.className=`cytoscape-stage layout-pending ${className}`.trim();stage.style.background=background;container.append(stage);
  const contentGraph=className.includes('content-'),sparseLargeGraph=nodes.length>140&&renderedEdges.length<nodes.length*.7;let layoutName=contentGraph?'breadthfirst':'cose';try{if(!contentGraph&&!sparseLargeGraph&&window.cytoscape('layout','fcose'))layoutName='fcose';}catch(_error){}
  const layoutOptions=layoutName==='breadthfirst'?{name:'breadthfirst',animate:false,fit:false,directed:true,padding:60,spacingFactor:1.1,avoidOverlap:true,circle:false}:layoutName==='fcose'?{name:'fcose',quality:'default',randomize:true,animate:false,fit:false,padding:60,packComponents:true,nodeSeparation:100,nodeRepulsion:()=>18000,idealEdgeLength:()=>135,edgeElasticity:()=>.3,numIter:2600,tile:true,tilingPaddingVertical:45,tilingPaddingHorizontal:45}:{name:'cose',animate:false,fit:false,padding:60,randomize:true,nodeRepulsion:nodes.length>300?180000:200000,nodeOverlap:40,idealEdgeLength:nodes.length>300?120:135,componentSpacing:nodes.length>300?110:130,numIter:nodes.length>300?5000:4000};
  const controls=document.createElement('div');controls.className='graph-zoom-controls';const labels=document.createElement('button');labels.type='button';labels.textContent='Aa';labels.title=state.language==='en'?'Toggle persistent titles':'切换题名常显';labels.setAttribute('aria-label',labels.title);let showLabels=false;labels.onclick=()=>{showLabels=!showLabels;cy.nodes().toggleClass('labels-always',showLabels);labels.classList.toggle('selected',showLabels);};controls.append(labels);for(const [label,title,run] of [['＋',state.language==='en'?'Zoom in':'放大',()=>cy.zoom({level:Math.min(cy.maxZoom(),cy.zoom()*1.25),renderedPosition:{x:stage.clientWidth/2,y:stage.clientHeight/2}})],['－',state.language==='en'?'Zoom out':'缩小',()=>cy.zoom({level:Math.max(cy.minZoom(),cy.zoom()/1.25),renderedPosition:{x:stage.clientWidth/2,y:stage.clientHeight/2}})],['⤢',state.language==='en'?'Fit graph':'适应画布',()=>cy.fit(undefined,85)]]){const button=document.createElement('button');button.type='button';button.textContent=label;button.title=title;button.setAttribute('aria-label',title);button.onclick=run;controls.append(button);}toolbar.append(controls);container.append(toolbar,stage);
  const cy=window.cytoscape({container:stage,minZoom:.05,maxZoom:4,userZoomingEnabled:true,userPanningEnabled:true,elements:[...nodes.map((node)=>{const short=node.label.length>22?`${node.label.slice(0,21)}…`:node.label;return {data:{id:node.node_id,label:node.label,short,display:'',type:node.node_type,category:node.graph_category||node.node_type,raw:node}};}),...renderedEdges],layout:{name:'preset'},style:[
    {selector:'node',style:{label:'data(display)','font-size':10,'font-weight':600,'text-wrap':'wrap','text-max-width':120,'text-valign':'bottom','text-margin-y':6,'text-background-color':'#fffdf8','text-background-opacity':.88,'text-background-padding':2,'background-color':'#7f8790','border-color':'#5f666d','border-width':1,width:18,height:18,color:'#292621'}},
    {selector:'node[category = "primary_sources"]',style:{'background-color':'#8b5a2b','border-color':'#6f431d'}},
    {selector:'node[category = "academic_articles"]',style:{'background-color':'#3e73a8','border-color':'#28567f'}},
    {selector:'node[category = "monographs"]',style:{'background-color':'#6b4c9a','border-color':'#4d3475'}},
    {selector:'node[category = "personal_manuscripts"]',style:{'background-color':'#2f7d5d','border-color':'#1f5b42'}},
    {selector:'node[category = "reference_works"]',style:{'background-color':'#a87821','border-color':'#7e5918'}},
    {selector:'node[category = "reading_notes"]',style:{'background-color':'#b97879','border-color':'#8d5556'}},
    {selector:'node[category = "unclassified"]',style:{'background-color':'#7f8790','border-color':'#5f666d'}},
    {selector:'node[category = "person"]',style:{'background-color':'#d06b4f','border-color':'#9b4430',width:15,height:15}},{selector:'node[category = "organization"]',style:{'background-color':'#d29c39','border-color':'#9a6d1d',width:15,height:15}},{selector:'node[category = "year"]',style:{'background-color':'#7f8790',width:11,height:11}},{selector:'node[category = "material_type"]',style:{'background-color':'#8062a8',width:12,height:12}},{selector:'node[category = "tag"]',style:{'background-color':'#4d8b71',width:11,height:11}},
    {selector:'edge',style:{width:1.5,'line-color':'#aa9d8b','curve-style':'bezier',opacity:.72,label:'data(display)','font-size':9,'text-background-color':'#fffdf8','text-background-opacity':.9,'text-background-padding':2,'text-rotation':'autorotate'}},
    {selector:'edge[relation = "same_author"]',style:{'line-color':'#3e73a8'}},{selector:'edge[relation = "same_publisher"]',style:{'line-color':'#a87821'}},{selector:'edge[relation = "same_journal"]',style:{'line-color':'#2b8c8c'}},{selector:'edge[relation = "cites"]',style:{'line-color':'#b23b32','target-arrow-shape':'triangle','target-arrow-color':'#b23b32'}},{selector:'edge[relation = "uses_material_from"]',style:{'line-color':'#8b5a2b','target-arrow-shape':'triangle','target-arrow-color':'#8b5a2b'}},{selector:'edge[relation = "reviews"]',style:{'line-color':'#d47521','target-arrow-shape':'triangle','target-arrow-color':'#d47521'}},{selector:'edge[relation = "translates"]',style:{'line-color':'#2b8c8c','target-arrow-shape':'triangle','target-arrow-color':'#2b8c8c'}},{selector:'edge[relation = "mentions_work"]',style:{'line-color':'#8c8c8c','line-style':'dashed','target-arrow-shape':'triangle','target-arrow-color':'#8c8c8c'}},
    {selector:'edge[relation = "authored_by"]',style:{'line-color':'#3e73a8','target-arrow-shape':'triangle','target-arrow-color':'#3e73a8'}},{selector:'edge[relation = "published_by"]',style:{'line-color':'#a87821','target-arrow-shape':'triangle','target-arrow-color':'#a87821'}},{selector:'edge[relation = "published_in_year"]',style:{'line-color':'#7c6f64'}},{selector:'edge[relation = "material_type"]',style:{'line-color':'#6b4c9a'}},{selector:'edge[relation = "tagged_as"]',style:{'line-color':'#7f8790','line-style':'dotted'}},{selector:'edge[relation = "shelved_as"]',style:{'line-color':'#2f7d5d','line-style':'dotted'}},
    {selector:'.dimmed',style:{opacity:.1}},{selector:'.filter-hidden',style:{display:'none'}},{selector:'edge.composite',style:{width:3,'line-style':'dashed'}},{selector:'edge.edge-hovered',style:{label:'data(label)',width:3}},{selector:'.labels-always',style:{label:'data(short)'}},{selector:'.focused',style:{label:'data(short)','border-width':3,'border-color':'#b55b2a'}},{selector:'.neighbor',style:{label:'data(short)','border-width':2,'border-color':'#49788a'}},{selector:'.hovered',style:{label:'data(short)','border-width':2}}]});
  const categoryNames=state.language==='en'?{primary_sources:'Primary sources',academic_articles:'Articles',monographs:'Monographs',personal_manuscripts:'Personal papers',reading_notes:'Reading notes',reference_works:'Reference works',unclassified:'Unclassified',person:'Authors',organization:'Journals / publishers',year:'Years',material_type:'Material types',tag:'Tags / shelves',source:'Sources',page:'Pages',content:'Content',event:'Events',entity:'Entities',claim:'Claims',evidence:'Evidence'}:{primary_sources:'原始史料',academic_articles:'期刊论文',monographs:'学术专著',personal_manuscripts:'本人文章与稿件',reading_notes:'读书笔记',reference_works:'工具书',unclassified:'待分类',person:'作者',organization:'期刊/出版社',year:'年份',material_type:'材料类型',tag:'标签/书架',source:'来源',page:'页面',content:'正文',event:'事件',entity:'实体',claim:'主张',evidence:'证据'};
  const categories=[...new Set(nodes.map(node=>node.graph_category||node.node_type))].sort(),relations=[...new Set(renderedEdges.flatMap(edge=>edge.data.relations))].sort();
  const filterPanel=document.createElement('details');filterPanel.className='graph-filter-panel';const filterSummary=document.createElement('summary');filterSummary.textContent='☷';filterSummary.title=state.language==='en'?`Filter ${categories.length} node and ${relations.length} relation types`:`筛选 ${categories.length} 类节点与 ${relations.length} 类关系`;filterSummary.setAttribute('aria-label',filterSummary.title);const filterBody=document.createElement('div');filterBody.className='graph-filter-body';const filterInputs=[];
  const addFilters=(title,values,kind,names)=>{const group=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=title;group.append(legend);for(const value of values){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=true;input.dataset.filterKind=kind;input.value=value;label.append(input,document.createTextNode(names[value]||value));group.append(label);filterInputs.push(input);}filterBody.append(group);};
  addFilters(state.language==='en'?'Nodes':'节点',categories,'node',categoryNames);addFilters(state.language==='en'?'Relations':'关系',relations,'edge',relationNames);filterPanel.append(filterSummary,filterBody);toolbar.insertBefore(filterPanel,controls);
  const applyFilters=()=>{const activeNodes=new Set(filterInputs.filter(input=>input.dataset.filterKind==='node'&&input.checked).map(input=>input.value)),activeRelations=new Set(filterInputs.filter(input=>input.dataset.filterKind==='edge'&&input.checked).map(input=>input.value));cy.nodes().forEach(node=>node.toggleClass('filter-hidden',!activeNodes.has(node.data('category'))));cy.edges().forEach(edge=>{const shown=edge.data('relations').filter(value=>activeRelations.has(value)).sort((left,right)=>relationPriority.indexOf(left)-relationPriority.indexOf(right));edge.data('relation',shown[0]||'');edge.data('label',shown.map(value=>relationNames[value]||value).join(' + '));edge.toggleClass('composite',shown.length>1);edge.toggleClass('filter-hidden',edge.source().hasClass('filter-hidden')||edge.target().hasClass('filter-hidden')||!shown.length);});};for(const input of filterInputs)input.onchange=applyFilters;
  let lastTap={id:'',at:0};cy.on('tap','node',(event)=>{const node=event.target,now=Date.now();if(lastTap.id===node.id()&&now-lastTap.at<380){lastTap={id:'',at:0};onOpen(node.data('raw'));return;}lastTap={id:node.id(),at:now};cy.elements().removeClass('focused neighbor dimmed');const neighborhood=node.closedNeighborhood();cy.elements().not(neighborhood).addClass('dimmed');node.addClass('focused');node.neighborhood('node').addClass('neighbor');});
  cy.on('mouseover','node',(event)=>event.target.addClass('hovered'));cy.on('mouseout','node',(event)=>event.target.removeClass('hovered'));
  cy.on('mouseover','edge',(event)=>event.target.addClass('edge-hovered'));cy.on('mouseout','edge',(event)=>event.target.removeClass('edge-hovered'));
  cy.on('tap','edge',(event)=>{const edge=event.target,details=edge.data('rawEdges').map(item=>`${cy.getElementById(item.source_node_id).data('label')} —${relationNames[item.relation]||item.relation}→ ${cy.getElementById(item.target_node_id).data('label')}`).join('；');notice(details);});
  cy.on('tap',(event)=>{if(event.target===cy)cy.elements().removeClass('focused neighbor dimmed');});
  let middlePan=null;stage.onpointerdown=(event)=>{if(event.button!==1)return;middlePan={x:event.clientX,y:event.clientY,id:event.pointerId};stage.setPointerCapture(event.pointerId);event.preventDefault();};stage.onpointermove=(event)=>{if(!middlePan||event.pointerId!==middlePan.id)return;cy.panBy({x:event.clientX-middlePan.x,y:event.clientY-middlePan.y});middlePan={...middlePan,x:event.clientX,y:event.clientY};};stage.onpointerup=stage.onpointercancel=(event)=>{if(middlePan&&event.pointerId===middlePan.id)middlePan=null;};
  const layout=cy.elements().layout(layoutOptions);layout.one('layoutstop',()=>{if(layoutName==='cose'&&nodes.length>140){const bounds=cy.nodes().boundingBox(),center={x:(bounds.x1+bounds.x2)/2,y:(bounds.y1+bounds.y2)/2},factor=sparseLargeGraph?.55:.65;cy.nodes().positions(node=>{const point=node.position();return{x:center.x+(point.x-center.x)*factor,y:center.y+(point.y-center.y)*factor};});if(sparseLargeGraph){const isolated=cy.nodes().filter(node=>node.degree()===0),connected=cy.nodes().filter(node=>node.degree()>0),connectedBounds=connected.boundingBox(),cx=(connectedBounds.x1+connectedBounds.x2)/2,cyy=(connectedBounds.y1+connectedBounds.y2)/2,start=Math.max(connectedBounds.w,connectedBounds.h)/2+70,golden=Math.PI*(3-Math.sqrt(5));isolated.forEach((node,index)=>{const radius=start+34*Math.sqrt(index+1),angle=index*golden;node.position({x:cx+radius*Math.cos(angle),y:cyy+radius*Math.sin(angle)});});}}cy.fit(cy.elements(),85);stage.dataset.layoutReady='1';stage.classList.remove('layout-pending');graphHint.textContent=graphInstructions;});layout.run();
  new ResizeObserver(()=>cy.resize().fit(undefined,70)).observe(stage);
  return true;
}
function renderKnowledgeGraph(data){
  const graph=$('libraryGraph');graph.replaceChildren();
  const english=state.language==='en';
  const shelfEnglish={primary_sources:'Primary sources',academic_articles:'Articles',monographs:'Monographs',personal_manuscripts:'Personal papers and drafts',reading_notes:'Reading notes',reference_works:'Reference works and catalogs',unclassified:'Unclassified'};
  const byId=Object.fromEntries(data.nodes.map((node)=>[node.node_id,node]));
  const workIds={};for(const node of data.nodes)if(node.node_type==='work'&&node.work_id)workIds[node.node_id]=node.work_id;
  const guide=card(english?'How to use this graph':'怎样使用知识图谱',english?'Search by title, author, publisher, tag, or a phrase found in the bounded intake preview. Select a work node or content card to open its bibliography and exact versions. If the work is already in this project, open the project source and return to verified pages. Content previews are discovery aids, not evidence or proof that the work has been fully read.':'可按题名、作者、出版者、标签或分诊内容中的词语检索。点击作品节点或内容卡，可以打开书目和具体版本；作品已经进入当前项目时，还可以直接打开项目文献并回到核验页。内容预览只用于发现和选书，不等于全文已读，也不能直接作为证据。');
  const receipt=document.createElement('p');receipt.className='boundary-note';receipt.textContent=english?`${data.node_count} nodes · ${data.edge_count} relations · ${(data.work_cards||[]).length} work(s). Relations come from registered bibliography and human tags.`:`${data.node_count}个节点 · ${data.edge_count}条关系 · ${(data.work_cards||[]).length}部作品。关系来自已登记书目和人工标签。`;
  // The graph page is a canvas, not another catalog list.
  const literature=card(english?'Literature relations':'文献关系图谱',english?'Exact registered titles found in page-linked Markdown create traceable relations automatically: notes and references count as citations, body text as mentions, and explicit translation, review, or material-use wording receives the corresponding directed relation. Researchers may exclude a false match.':'带页码Markdown中出现已登记作品的精确题名时自动建立可回查关系：脚注、尾注和参考文献记为引用，正文记为提及，明确出现翻译、评介或材料使用措辞时记为相应有向关系。研究者仍可排除误匹配。');
  const relationLabels=english?{cites:'Cites',uses_material_from:'Uses material from',reviews:'Reviews',translates:'Translates',mentions_work:'Mentions'}:{cites:'引用',uses_material_from:'使用其材料',reviews:'评述',translates:'翻译',mentions_work:'提及'};
  for(const relation of data.literature_relations||[]){
    const node=card(`${relation.source_work_title} → ${relation.target_work_title}`,`${relationLabels[relation.relation_type]||relation.relation_type} · ${relation.status} · ${relation.printed_page||`PDF ${relation.physical_page}`}`);
    node.append(Object.assign(document.createElement('blockquote'),{textContent:relation.quote}));
    const actions=document.createElement('div');actions.className='button-row';
    actions.append(actionButton(english?'Open note/reference page':'打开脚注或参考文献页',async()=>{await loadSource(relation.source_id);const index=state.view.pages.findIndex((page)=>page.page_id===relation.page_id);if(index>=0)state.pageIndex=index;setMode('source');render();},true));
    if(relation.status==='candidate'){
      const type=document.createElement('select');for(const [value,label] of Object.entries(relationLabels))type.append(new Option(label,value));type.value='cites';
      const decide=async(approved)=>{const reviewer=window.prompt(english?'Reviewer':'决定人','human-reviewer');if(!reviewer)return;const reason=window.prompt(english?'Decision reason':'判断依据');if(!reason)return;await request('/api/library/graph/relation/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({relation_key:relation.relation_key,approved,relation_type:type.value,reviewer,reason})});await setLibraryView('graph');notice(approved?(english?'Literature relation approved.':'文献关系已批准。'):(english?'Candidate rejected.':'候选关系已拒绝。'));};
      actions.append(type,actionButton(english?'Approve relation':'批准关系',()=>decide(true),true),actionButton(english?'Reject':'拒绝',()=>decide(false)));
    }else if(relation.status==='derived'){
      actions.append(actionButton(english?'Exclude false match':'排除误匹配',async()=>{const reviewer=window.prompt(english?'Reviewer':'决定人','human-reviewer');if(!reviewer)return;const reason=window.prompt(english?'Why is this relation false?':'排除依据');if(!reason)return;await request('/api/library/graph/relation/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({relation_key:relation.relation_key,approved:false,relation_type:relation.relation_type,reviewer,reason})});await setLibraryView('graph');notice(english?'Relation excluded.':'关系已排除。');}));
    }
    node.append(actions);literature.append(node);
  }
  if(!(data.literature_relations||[]).length)literature.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No registered work title was found in the current project note/reference zones.':'当前项目的脚注、尾注和参考文献区域尚未匹配到已登记作品题名。'}));
  const literatureDetails=document.createElement('details');literatureDetails.className='literature-relations-panel';const literatureSummary=document.createElement('summary');literatureSummary.textContent=english?`Literature-relation candidates (${(data.literature_relations||[]).length})`:`文献关系候选（${(data.literature_relations||[]).length}）`;literatureDetails.append(literatureSummary,literature);
  if(!data.nodes.length&&!(data.content_graph?.nodes||[]).length){graph.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No graph node matches the current search.':'当前检索范围没有可显示的图谱节点。'}));return;}
  const legendCategoryLabels=english?{primary_sources:'Primary sources',academic_articles:'Articles',monographs:'Monographs',personal_manuscripts:'Personal papers',reading_notes:'Reading notes',reference_works:'Reference works',person:'Authors',organization:'Journals / publishers',year:'Years',material_type:'Material types',tag:'Tags / shelves',source:'Sources',page:'Pages',content:'Content blocks',event:'Approved events',entity:'Shared entities',claim:'Claims',evidence:'Verified evidence'}:{primary_sources:'原始史料',academic_articles:'期刊论文',monographs:'学术专著',personal_manuscripts:'本人文章与稿件',reading_notes:'读书笔记',reference_works:'工具书',person:'作者',organization:'期刊/出版社',year:'年份',material_type:'材料类型',tag:'标签/书架',source:'来源',page:'页面',content:'正文块',event:'已批准事件',entity:'共享实体',claim:'主张',evidence:'已核证据'};
  const legendCategoryColors={primary_sources:'#8b5a2b',academic_articles:'#3e73a8',monographs:'#6b4c9a',personal_manuscripts:'#2f7d5d',reading_notes:'#b97879',reference_works:'#a87821',person:'#d06b4f',organization:'#d29c39',year:'#7f8790',material_type:'#8062a8',tag:'#4d8b71',source:'#4f7b95',page:'#7b8da5',content:'#6d9caf',event:'#a87821',entity:'#2f7d5d',claim:'#6b4c9a',evidence:'#b23b32'};
  const legendRelationLabels=english?{same_author:'Same author',same_publisher:'Same publisher',same_journal:'Same journal',authored_by:'Authored by',published_by:'Published by',published_in_year:'Publication year',material_type:'Material type',tagged_as:'Tagged as',shelved_as:'Shelved as',cites:'Citation',uses_material_from:'Material use',reviews:'Review',translates:'Translation',mentions_work:'Mention',contains_page:'Contains page',contains_content:'Contains content',records_event:'Records event',belongs_to_case:'Case',dated:'Date',starts_at:'Start place',ends_at:'End place',investigates:'Topic',anchored_in:'Page anchor',has_evidence:'Evidence',linked_to:'Claim link'}:{same_author:'同作者',same_publisher:'同出版社',same_journal:'同期刊',authored_by:'作者',published_by:'期刊/出版社',published_in_year:'出版年',material_type:'材料类型',tagged_as:'标签',shelved_as:'书架',cites:'引用',uses_material_from:'使用其材料',reviews:'评述',translates:'翻译',mentions_work:'提及',contains_page:'包含页面',contains_content:'包含正文',records_event:'记载事件',belongs_to_case:'所属个案',dated:'时间',starts_at:'起点',ends_at:'终点',investigates:'调查对象',anchored_in:'原页锚点',has_evidence:'包含证据',linked_to:'主张关联'};
  const legendRelationColors={same_author:'#3e73a8',same_publisher:'#a87821',same_journal:'#2b8c8c',authored_by:'#3e73a8',published_by:'#a87821',published_in_year:'#7c6f64',material_type:'#6b4c9a',tagged_as:'#7f8790',shelved_as:'#2f7d5d',cites:'#b23b32',uses_material_from:'#8b5a2b',reviews:'#d47521',translates:'#2b8c8c',mentions_work:'#8c8c8c',contains_page:'#7b8da5',contains_content:'#4f7b95',records_event:'#a87821',belongs_to_case:'#2f7d5d',dated:'#7c6f64',starts_at:'#2f7d5d',ends_at:'#2f7d5d',investigates:'#8062a8',anchored_in:'#8b5a2b',has_evidence:'#b23b32',linked_to:'#6b4c9a'};
  const appendModeLegend=(target,mode,nodes,edges)=>{const legend=document.createElement('div');legend.className='graph-color-legend';legend.append(Object.assign(document.createElement('strong'),{textContent:english?({work:'Work-relation legend',entity:'Bibliographic-entity legend',content:'Project-content legend'}[mode]):({work:'作品关系图例',entity:'书目实体图例',content:'项目内容图例'}[mode])}));const categories=[...new Set(nodes.map(node=>node.graph_category||node.node_type))];for(const key of categories){const chip=document.createElement('span'),swatch=document.createElement('i');swatch.style.cssText=`display:inline-block;width:12px;height:12px;border-radius:50%;background:${legendCategoryColors[key]||'#7f8790'}`;chip.append(swatch,document.createTextNode(legendCategoryLabels[key]||key));legend.append(chip);}const relations=[...new Set(edges.map(edge=>edge.relation))];for(const key of relations){const chip=document.createElement('span'),swatch=document.createElement('i');swatch.style.cssText=`display:inline-block;width:22px;height:3px;border-radius:3px;background:${legendRelationColors[key]||'#aa9d8b'}`;chip.append(swatch,document.createTextNode(legendRelationLabels[key]||key));legend.append(chip);}target.append(legend);};
  const entityById=Object.fromEntries((data.entity_nodes||[]).map(node=>[node.node_id,node]));
  const revealLibraryDetail=()=>{state.libraryGraphAutoCollapsed=false;if($('libraryWorkbench').classList.contains('right-collapsed'))$('toggleLibraryDetail').click();};
  const openBibliographicNode=async(node,edgeSet=data.edges,nodeSet=byId)=>{if(node.work_id){await loadWork(node.work_id);revealLibraryDetail();return;}const relatedIds=new Set();for(const edge of edgeSet)if(edge.source_node_id===node.node_id)relatedIds.add(edge.target_node_id);else if(edge.target_node_id===node.node_id)relatedIds.add(edge.source_node_id);const panel=$('workDetail');panel.replaceChildren(card(`${node.node_type} · ${node.label}`,english?'Related registered works':'相关已登记书目'));for(const id of relatedIds){const related=nodeSet[id];if(related?.work_id)panel.append(actionButton(`↗ ${related.label}`,()=>loadWork(related.work_id),true));}revealLibraryDetail();};
  const compactContentLabels=english?{source:'Source',page:'Page',content:'Markdown content',event:'Approved event',entity:'Shared entity',claim:'Claim',evidence:'Verified evidence'}:{source:'来源',page:'页面',content:'Markdown内容',event:'已批准事件',entity:'共享实体',claim:'主张',evidence:'已核证据'};
  const openCompactContentNode=async(item)=>{const panel=$('workDetail');panel.replaceChildren(card(`${compactContentLabels[item.node_type]||item.node_type} · ${item.label}`,`${item.excerpt||''}\n${item.printed_page||item.physical_page||''}`));if(item.source_id)panel.append(actionButton(english?'Open source location':'打开所在史料位置',async()=>{await loadSource(item.source_id);if(item.page_id){const index=state.view.pages.findIndex((page)=>page.page_id===item.page_id);if(index>=0)state.pageIndex=index;}setMode('source');render();},true));revealLibraryDetail();};
  const graphModes=document.createElement('div');graphModes.className='button-row graph-mode-switch';const workMode=actionButton(english?'Work relations':'作品关系',()=>{},true),entityMode=actionButton(english?'Bibliographic entities':'书目实体',()=>{}),contentMode=actionButton(english?'Project content entities':'项目内容实体',()=>{});graphModes.append(workMode,entityMode,contentMode);const graphHost=document.createElement('section');graphHost.className='bibliographic-graph-host';graph.append(graphModes,graphHost);
  const drawMode=(mode)=>{graphHost.replaceChildren();workMode.classList.toggle('primary-inline',mode==='work');entityMode.classList.toggle('primary-inline',mode==='entity');contentMode.classList.toggle('primary-inline',mode==='content');const content=mode==='content',entity=mode==='entity',shownNodes=content?(data.content_graph?.nodes||[]):(entity?(data.entity_nodes||[]):data.nodes),shownEdges=content?(data.content_graph?.edges||[]):(entity?(data.entity_edges||[]):data.edges),lookup=entity?entityById:byId;appendModeLegend(graphHost,mode,shownNodes,shownEdges);return renderInteractiveGraph(graphHost,shownNodes,shownEdges,{background:content?'#e5edf0':(entity?'#e8edf0':'#f1ece3'),className:content?'content-cytoscape-stage':'',onOpen:(node)=>(content?openCompactContentNode(node):openBibliographicNode(node,shownEdges,lookup)).catch((error)=>notice(error.message,true))});};workMode.onclick=()=>drawMode('work');entityMode.onclick=()=>drawMode('entity');contentMode.onclick=()=>drawMode('content');
  drawMode('work');return;
  {
  const typeOrder=['work','person','year','organization','material_type','tag','source','page','content','event','entity','claim','evidence'];
  const typeLabels=english?{work:'Works',person:'Authors',year:'Years',organization:'Publishers',material_type:'Material types',tag:'Shelves / tags',source:'Sources',page:'Pages',content:'Markdown content',event:'Events',entity:'Shared entities',claim:'Claims',evidence:'Evidence'}:{work:'作品',person:'作者',year:'年代',organization:'出版者',material_type:'材料类型',tag:'书架/标签',source:'来源',page:'页面',content:'Markdown内容',event:'事件',entity:'共享实体',claim:'主张',evidence:'证据'};
  const grouped={};for(const node of data.nodes)(grouped[node.node_type]||=[]).push(node);
  const types=typeOrder.filter((type)=>grouped[type]?.length).concat(Object.keys(grouped).filter((type)=>!typeOrder.includes(type)));
  const width=Math.max(900,types.length*210),maxRows=Math.max(...types.map((type)=>grouped[type].length));
  const height=Math.max(500,maxRows*62+90),positions={};
  types.forEach((type,column)=>grouped[type].forEach((node,row)=>{positions[node.node_id]={x:35+column*(width-70)/Math.max(types.length-1,1),y:65+row*62};}));
  const legend=document.createElement('div');legend.className='graph-legend';for(const type of types)legend.append(Object.assign(document.createElement('span'),{textContent:`${typeLabels[type]||type} ${grouped[type].length}`}));graphHost.append(legend);
  const svg=svgElement('svg');svg.classList.add('graph-stage');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',state.language==='en'?'Current library knowledge graph':'当前图书馆知识图谱');
  const edgeElements=[];for(const edge of data.edges){const start=positions[edge.source_node_id],end=positions[edge.target_node_id];if(!start||!end)continue;const line=svgElement('line');line.classList.add('graph-edge',`relation-${edge.relation}`);line.dataset.source=edge.source_node_id;line.dataset.target=edge.target_node_id;line.setAttribute('x1',start.x+75);line.setAttribute('y1',start.y+16);line.setAttribute('x2',end.x+75);line.setAttribute('y2',end.y+16);const title=svgElement('title');title.textContent=edge.relation;line.append(title);svg.append(line);edgeElements.push(line);}
  const nodeElements=[];const focusNode=(nodeId)=>{const related=new Set([nodeId]);for(const edge of data.edges)if(edge.source_node_id===nodeId)related.add(edge.target_node_id);else if(edge.target_node_id===nodeId)related.add(edge.source_node_id);for(const item of nodeElements){const active=related.has(item.dataset.nodeId);item.classList.toggle('graph-dimmed',!active);item.classList.toggle('graph-active',item.dataset.nodeId===nodeId);}for(const edge of edgeElements)edge.classList.toggle('graph-dimmed',edge.dataset.source!==nodeId&&edge.dataset.target!==nodeId);};
  const showNodeDetail=async(node)=>{if(workIds[node.node_id]){await loadWork(workIds[node.node_id]);}else{const relatedIds=new Set();for(const edge of data.edges)if(edge.source_node_id===node.node_id)relatedIds.add(edge.target_node_id);else if(edge.target_node_id===node.node_id)relatedIds.add(edge.source_node_id);const panel=$('workDetail');panel.replaceChildren(card(`${typeLabels[node.node_type]||node.node_type} · ${node.label}`,english?'This entity is connected to the following registered works.':'该实体在以下已登记书目中出现。'));for(const id of relatedIds){const related=byId[id];if(related?.node_type==='work'&&related.work_id)panel.append(actionButton(`↗ ${related.label}`,()=>loadWork(related.work_id),true));}}if($('libraryWorkbench').classList.contains('right-collapsed'))$('toggleLibraryDetail').click();};
  for(const node of data.nodes){const point=positions[node.node_id];if(!point)continue;const item=svgElement('g');item.classList.add('graph-item',`graph-${node.node_type}`);item.dataset.nodeId=node.node_id;item.setAttribute('transform',`translate(${point.x} ${point.y})`);item.setAttribute('tabindex','0');item.setAttribute('role','button');const rect=svgElement('rect');rect.setAttribute('width','150');rect.setAttribute('height','32');rect.setAttribute('rx','7');const text=svgElement('text');text.setAttribute('x','8');text.setAttribute('y','20');text.textContent=node.label.length>18?`${node.label.slice(0,17)}…`:node.label;const title=svgElement('title');title.textContent=`${typeLabels[node.node_type]||node.node_type}: ${node.label}`;item.append(rect,text,title);item.onclick=()=>focusNode(node.node_id);item.ondblclick=()=>showNodeDetail(node).catch((error)=>notice(error.message,true));item.onkeydown=(event)=>{if(event.key==='Enter'){event.preventDefault();showNodeDetail(node);}};svg.append(item);nodeElements.push(item);}
  graphHost.append(svg);
  }
  return;
  const cards=document.createElement('section');cards.className='graph-work-cards';
  for(const work of data.work_cards||[]){
    const edition=[work.edition?.edition_label,work.edition?.publisher,work.edition?.publication_year].filter(Boolean).join(' · ');
    const projectState=work.project_source?(english?`In current project · ${work.project_source.processing_state} · ${work.project_source.use_state}`:`已进入当前项目 · ${work.project_source.processing_state} · ${work.project_source.use_state}`):(work.project_link_count?(english?`Used by ${work.project_link_count} other project(s)`:`已被${work.project_link_count}个其他项目使用`):(english?'Library only; review a version before adding it to a project':'目前只在图书馆；核对版本后可加入项目'));
    const node=card(work.title,`${work.author||(english?'Author not verified':'作者待核')}\n${edition||(english?'Edition details not verified':'版本信息待核')}\n${english?(shelfEnglish[work.shelf]||work.shelf_label):work.shelf_label} · ${(work.format||'').toUpperCase()} · ${work.page_count??(english?'pages unknown':'页数待核')}\n${projectState}`);
    const preview=document.createElement('p');preview.className='graph-content-preview';preview.textContent=work.content_excerpt||(english?'No searchable intake preview is available for this exact version.':'当前精确版本没有可显示的分诊内容预览。');node.append(preview);
    const boundary=document.createElement('small');boundary.textContent=english?`Preview from up to ${work.preview_pages||0} inspected page(s); use it to decide what to read, not as a citation.`:`预览来自最多${work.preview_pages||0}个已检查页面，只用于判断是否值得阅读，不能直接引用。`;node.append(boundary);
    const actions=document.createElement('div');actions.className='button-row';actions.append(actionButton(english?'Open bibliography and versions':'打开书目与版本',()=>loadWork(work.work_id).then(()=>notice(english?'Work details opened on the right.':'已在右侧打开作品详情。')).catch((error)=>notice(error.message,true)),true));
    if(work.project_source?.source_id)actions.append(actionButton(english?'Open project source pages':'打开项目文献原页',async()=>{await loadSource(work.project_source.source_id);setMode('source');render();notice(english?'Opened the project source at its current page.':'已打开当前项目文献及原页。');},true));
    node.append(actions);cards.append(node);
  }
  graph.append(cards);
  const content=data.content_graph||{nodes:[],edges:[],type_counts:{}};
  const contentSection=card(english?'Project content graph':'项目内容图谱',english?'Built from the current page-linked Markdown blocks, approved events, verified evidence, and their claims. Machine-parsed blocks remain searchable content nodes with visible status; approved research relations retain their page anchors.':'依据当前带页码的Markdown文本块、已批准事件、已核证据及其主张构建。机器解析块仍可作为带状态的检索节点；正式研究关系保留原页锚点。');
  const contentCounts=document.createElement('p');contentCounts.className='boundary-note';contentCounts.textContent=english?`${content.node_count||0} nodes · ${content.edge_count||0} relations · ${Object.entries(content.type_counts||{}).map(([type,count])=>`${type} ${count}`).join(' · ')}`:`${content.node_count||0}个节点 · ${content.edge_count||0}条关系 · ${Object.entries(content.type_counts||{}).map(([type,count])=>`${type} ${count}`).join(' · ')}`;contentSection.append(contentCounts);
  graph.append(contentSection);
  const openContentNode=async(item)=>{const panel=$('workDetail');panel.replaceChildren(card(`${contentTypeLabels[item.node_type]||item.node_type} · ${item.label}`,`${item.excerpt||''}\n${item.printed_page||item.physical_page||''}`));if(item.source_id)panel.append(actionButton(english?'Open source location':'打开所在史料位置',async()=>{await loadSource(item.source_id);if(item.page_id){const index=state.view.pages.findIndex((page)=>page.page_id===item.page_id);if(index>=0)state.pageIndex=index;}setMode('source');render();},true));if($('libraryWorkbench').classList.contains('right-collapsed'))$('toggleLibraryDetail').click();};
  renderInteractiveGraph(contentSection,content.nodes||[],content.edges||[],{background:'#e5edf0',className:'content-cytoscape-stage',onOpen:(item)=>openContentNode(item).catch((error)=>notice(error.message,true))});
  const contentCards=document.createElement('section');contentCards.className='content-graph-cards';
  const contentTypeLabels=english?{source:'Source',page:'Page',content:'Markdown content',event:'Approved event',entity:'Shared entity',claim:'Claim',evidence:'Verified evidence'}:{source:'来源',page:'页面',content:'Markdown内容',event:'已批准事件',entity:'共享实体',claim:'主张',evidence:'已核证据'};
  for(const item of content.nodes||[]){
    if(item.node_type==='page')continue;
    const page=[item.printed_page?(english?`Printed page ${item.printed_page}`:`印刷页 ${item.printed_page}`):'',item.physical_page?(english?`Physical page ${item.physical_page}`:`物理页 ${item.physical_page}`):''].filter(Boolean).join(' / ');
    const node=card(`${contentTypeLabels[item.node_type]||item.node_type} · ${item.label}`,`${item.status||''}${page?` · ${page}`:''}`);
    if(item.excerpt&&item.excerpt!==item.label)node.append(Object.assign(document.createElement('p'),{className:'graph-content-preview',textContent:item.excerpt}));
    if(item.source_id){const open=actionButton(english?'Open anchored source page':'打开锚定原页',async()=>{await loadSource(item.source_id);if(item.page_id){const index=state.view.pages.findIndex((pageItem)=>pageItem.page_id===item.page_id);if(index>=0)state.pageIndex=index;}setMode('source');render();notice(english?'Opened the source and anchored page.':'已打开来源及锚定原页。');},true);node.append(open);}
    contentCards.append(node);
  }
  if(!content.nodes?.length)contentCards.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No processed Markdown content or approved research relation matches this search.':'当前检索没有匹配的清洗Markdown内容或已批准研究关系。'}));
  contentSection.append(contentCards);
  const contentRelations=document.createElement('details');const contentSummary=document.createElement('summary');contentSummary.textContent=english?'Show content-graph relations':'查看内容图谱关系';const relationBody=document.createElement('section');relationBody.className='graph-relations';const contentById=Object.fromEntries((content.nodes||[]).map((item)=>[item.node_id,item]));for(const edge of content.edges||[]){relationBody.append(Object.assign(document.createElement('p'),{textContent:`${contentById[edge.source_node_id]?.label||edge.source_node_id} —${edge.relation}→ ${contentById[edge.target_node_id]?.label||edge.target_node_id}`}));}contentRelations.append(contentSummary,relationBody);contentSection.append(contentRelations);
  const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=english?'Show all relations as text':'查看全部关系文本';const relations=document.createElement('section');relations.className='graph-relations';for(const edge of data.edges){const row=document.createElement('p');row.textContent=`${byId[edge.source_node_id]?.label||edge.source_node_id}  —${edge.relation}→  ${byId[edge.target_node_id]?.label||edge.target_node_id}`;relations.append(row);}details.append(summary,relations);graph.append(details);
}

function renderSourceChronicle(data){
  const container=$('sourceChronicle');container.replaceChildren();
  const filters=document.createElement('section');filters.className='context-form chronicle-filters';
  const query=document.createElement('input');query.placeholder='检索原文、内容提要、个案或来源';query.value=data.filters?.query||'';
  const year=document.createElement('input');year.placeholder='年份，例如 1875';year.value=data.filters?.year||'';
  const caseId=document.createElement('input');caseId.placeholder='比较个案（可留空）';caseId.value=data.filters?.case_id||'';
  const projectId=state.snapshot?.project?.project_id||'default',storageKey=`wenjinChronicles:${projectId}`;
  const saved=JSON.parse(localStorage.getItem(storageKey)||'{}');const views=document.createElement('select');views.append(new Option('选择已保存长编',''));for(const name of Object.keys(saved).sort())views.append(new Option(name,name));views.value=state.chronicleViewName;
  const load=async()=>{const params=new URLSearchParams({query:query.value.trim(),year:year.value.trim(),case_id:caseId.value.trim(),limit:'300'});const result=await request(`/api/source-chronicle?${params}`);renderSourceChronicle(result);notice(`史料长编显示 ${result.returned_count} / ${result.total_count} 条已批准记录。`);};
  views.onchange=async()=>{const value=saved[views.value];if(!value)return;state.chronicleViewName=views.value;query.value=value.query||'';year.value=value.year||'';caseId.value=value.case_id||'';await load();};
  filters.append(views,query,year,caseId,actionButton('保存为新长编',async()=>{const name=window.prompt('长编名称',state.chronicleViewName||'新的史料长编');if(!name?.trim())return;saved[name.trim()]={query:query.value.trim(),year:year.value.trim(),case_id:caseId.value.trim()};localStorage.setItem(storageKey,JSON.stringify(saved));state.chronicleViewName=name.trim();renderSourceChronicle(data);notice(`已保存长编“${name.trim()}”。`);},true),actionButton('删除当前长编',()=>{if(!state.chronicleViewName)return;delete saved[state.chronicleViewName];localStorage.setItem(storageKey,JSON.stringify(saved));state.chronicleViewName='';renderSourceChronicle(data);}),actionButton('筛选长编',load,true),actionButton('清除筛选',async()=>{query.value='';year.value='';caseId.value='';await load();}),actionButton('导出 Markdown',async()=>{const result=await request('/api/source-chronicle/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:state.chronicleViewName||'史料长编',query:query.value.trim(),year:year.value.trim(),case_id:caseId.value.trim()})});notice(`已导出 ${result.row_count} 条史料：${result.native_path||result.project_path}`);},true));
  container.append(filters);
  container.append(card('长编范围',`${data.returned_count} / ${data.total_count} 条。只收入已经人工批准、能够回到具体来源版本和页码的逐事件记录；它不表示相关史料已经穷尽。`));
  if(!data.entries.length){container.append(card('当前没有可显示的记录','可先在“研究上下文—逐事件表”建立并核准史料条目。'));return;}
  for(const entry of data.entries){
    const pages=(entry.printed_pages?.length?entry.printed_pages:entry.physical_pages)||[];
    const node=card(`${entry.event_date||'日期待考'} · ${entry.case_id}`,`${entry.summary||'本条尚无内容提要'}\n${entry.source_title} · 页码 ${pages.join('、')||'待核'}`);
    if(entry.original_text){const original=document.createElement('blockquote');original.textContent=entry.original_text;node.append(original);}
    if(entry.translation)node.append(Object.assign(document.createElement('p'),{textContent:`译文：${entry.translation}`}));
    node.append(Object.assign(document.createElement('small'),{textContent:`${entry.source_id} · ${entry.source_version_id} · ${entry.qualification}`}));
    node.append(actionButton('打开对应原页',async()=>{await loadSource(entry.source_id);const pageId=entry.page_ids?.[0];const index=state.view.pages.findIndex((page)=>page.page_id===pageId);if(index>=0)state.pageIndex=index;setMode('source');render();notice('已打开本条史料对应的原页与文本块。');},true));
    container.append(node);
  }
}

function renderLibraryAssets(kind){
  const container=$('libraryAssetView');container.replaceChildren();
  const english=state.language==='en';
  const labels=english?{tables:'Data tables',maps:'Maps',images:'Images'}:{tables:'数据图表',maps:'地图',images:'图片'};
  const items=state.snapshot?.library_assets?.[kind]||[];
  container.append(card(labels[kind],english?`${items.length} registered current file(s). Files remain under the same work, edition, and exact-version model.`:`${items.length}个已登记的当前文件；仍沿用作品、版本和精确文件版本关系。`));
  const grid=document.createElement('section');grid.className=`library-asset-grid asset-${kind}`;
  for(const item of items){const node=card(item.canonical_title,`${(item.format||'').toUpperCase()} · ${formatBytes(item.byte_count||0)}\n${item.path}`);if(kind==='images'){const href=`/api/library/file?id=${encodeURIComponent(item.file_id)}`;const image=document.createElement('img');image.className='library-image-preview';image.src=href;image.alt=item.canonical_title;image.title=english?'Double-click to open the full image':'双击打开大图';image.ondblclick=()=>openImagePreview(href,image.alt);node.prepend(image);}const actions=document.createElement('div');actions.className='button-row';actions.append(actionButton(english?'Open work and versions':'打开作品与版本',()=>loadWork(item.work_id),true));if(nativeAvailable()&&item.available){const open=()=>nativeInvoke('open_path',{path:item.path}).catch((error)=>notice(error.message,true));actions.append(actionButton(english?'Open file':'打开文件',open));if(kind!=='images'){node.title=english?'Double-click to open file':'双击打开文件';node.ondblclick=open;}}node.append(actions);grid.append(node);}
  if(!items.length)grid.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?`No ${labels[kind].toLowerCase()} have been registered yet.`:`图书馆中尚未登记${labels[kind]}。可从聊天上传、手动上传或目录盘点入库。`}));
  container.append(grid);
}

async function setLibraryView(view){
  if(!['list','chronicle','graph','tables','maps','images','intake'].includes(view))view='list';
  state.libraryView=view;sessionStorage.setItem('wenjinLibraryView',view);
  const workbench=$('libraryWorkbench');workbench.classList.remove('mode-list','mode-chronicle','mode-graph','mode-tables','mode-maps','mode-images','mode-intake');workbench.classList.add(`mode-${view}`);
  if(view==='graph'&&!workbench.classList.contains('right-collapsed')){state.libraryGraphAutoCollapsed=true;$('toggleLibraryDetail').click();}
  else if(view!=='graph'&&state.libraryGraphAutoCollapsed&&workbench.classList.contains('right-collapsed')){state.libraryGraphAutoCollapsed=false;$('toggleLibraryDetail').click();}
  $('workList').hidden=view!=='list';$('sourceChronicle').hidden=view!=='chronicle';$('libraryGraph').hidden=view!=='graph';$('libraryAssetView').hidden=!['tables','maps','images'].includes(view);
  $('toggleLibraryDetail').hidden=['chronicle','intake'].includes(view);
  for(const button of $('libraryViews').querySelectorAll('[data-library-view]'))button.classList.toggle('selected',button.dataset.libraryView===view);
  if(view==='chronicle'){
    try{const data=await request('/api/source-chronicle?limit=300');renderSourceChronicle(data);notice(`史料长编已载入 ${data.returned_count} 条已批准记录。`);}catch(error){notice(error.message,true);}return;
  }
  if(['tables','maps','images'].includes(view)){renderLibraryAssets(view);return;}
  if(view!=='graph')return;
  try{const graphQuery=state.libraryGraphQuery;const graphLimit=graphQuery?80:500;const data=await request(`/api/library/graph?query=${encodeURIComponent(graphQuery)}&limit=${graphLimit}`);renderKnowledgeGraph(data);notice(state.language==='en'?`Knowledge graph shows ${data.node_count||0} work(s) in the current scope.`:`知识图谱显示当前范围内的${data.node_count||0}部作品。`);}catch(error){notice(error.message,true);}
}

let libraryScanPollTimer=0;
async function loadLibraryScan(sessionId='',page=1) {
  if(libraryScanPollTimer){clearTimeout(libraryScanPollTimer);libraryScanPollTimer=0;}
  const query=new URLSearchParams({page:String(page),page_size:'50'});
  if(sessionId)query.set('id',sessionId);
  try{
    state.libraryScan=await request(`/api/library/scan?${query}`);
  }catch(error){
    if(!sessionId&&/unknown scan session/i.test(error.message))return;
    throw error;
  }
  state.libraryScanPage=state.libraryScan.page || 1;
  sessionStorage.setItem('hrwLibraryScanId',state.libraryScan.session_id);
  sessionStorage.setItem('hrwLibraryScanPage',String(state.libraryScanPage));
  renderScan();
  if(state.libraryScan.status==='scanning'){
    libraryScanPollTimer=setTimeout(()=>loadLibraryScan(state.libraryScan.session_id,state.libraryScanPage).catch((error)=>notice(error.message,true)),750);
  }
}

async function restoreLibraryScan() {
  const sessionId=sessionStorage.getItem('hrwLibraryScanId') || '';
  const page=Number(sessionStorage.getItem('hrwLibraryScanPage') || 1);
  try{await loadLibraryScan(sessionId,page);}catch(error){
    sessionStorage.removeItem('hrwLibraryScanId');sessionStorage.removeItem('hrwLibraryScanPage');
    if(sessionId)try{await loadLibraryScan('',1);}catch(latestError){return;}
  }
}

function renderWorkList() {
  const list = $('workList'); list.replaceChildren();
  const english=state.language==='en',shelfLabels={primary_sources:'Primary sources',academic_articles:'Articles',monographs:'Monographs',personal_manuscripts:'Personal papers and drafts',reading_notes:'Reading notes',reference_works:'Reference works and catalogs',unclassified:'Unclassified'};
  const visible=state.libraryWorks.filter((work)=>!$('libraryShelf').value||work.shelf===$('libraryShelf').value);
  if (!visible.length) {
    list.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'图书馆还没有已批准材料。盘点不会自动入库。'})); return;
  }
  for (const work of visible) {
    const button = document.createElement('button'); button.className = 'work-row';
    button.classList.toggle('selected', work.work_id === state.libraryWorkId);
    const title = document.createElement('strong'); title.textContent = work.canonical_title;
    const author = document.createElement('span'); author.textContent = work.author || (english?'Author not verified':'作者待核');
    const meta = document.createElement('small'); meta.textContent = `${english?(shelfLabels[work.shelf]||work.shelf_label):work.shelf_label} · ${work.material_type} · ${work.file_count} ${english?'location(s)':'个位置'} · ${work.version_count} ${english?'version(s)':'个版本'}`;
    const tags = document.createElement('small'); tags.textContent = work.tags.filter((item)=>item.origin==='user'&&!item.name.startsWith('shelf:')).map((item) => item.name).join(' · ');
    button.append(title, author, meta);if(tags.textContent)button.append(tags);
    button.onclick = () => loadWork(work.work_id).catch((error) => notice(error.message, true)); list.append(button);
  }
}

async function loadWork(workId) {
  const token=++state.libraryWorkRequestToken;
  state.libraryWorkId = workId;
  state.libraryWork = null;state.libraryWorkLoading=true;
  renderWorkList(); renderWorkDetail();
  try{
    const detail=await request(`/api/library/work?id=${encodeURIComponent(workId)}`);
    if(token!==state.libraryWorkRequestToken||state.libraryWorkId!==workId)return;
    state.libraryWork=detail;
  }finally{
    if(token===state.libraryWorkRequestToken){state.libraryWorkLoading=false;renderWorkList();renderWorkDetail();}
  }
}

function assertCurrentLibraryWork(expectedWorkId) {
  if(state.libraryWorkLoading||state.libraryWorkId!==expectedWorkId||state.libraryWork?.work_id!==expectedWorkId){
    throw new Error('作品详情仍在切换，请等待当前作品加载完成后再保存。');
  }
}

function detailField(labelText, value, name) {
  const label = document.createElement('label'); label.textContent = labelText;
  const input = document.createElement('input'); input.value = value || ''; input.dataset.field = name;
  label.append(input); return label;
}

function renderWorkDetail() {
  const container = $('workDetail'); container.replaceChildren();
  const work = state.libraryWork;
  if(state.libraryWorkLoading){
    container.append(Object.assign(document.createElement('p'),{className:'empty',textContent:'正在加载所选作品，请稍候……'}));return;
  }
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
    detailField('出版社 / 期刊名', edition.publisher, 'publisher'),
    detailField('出版年', edition.publication_year, 'publication_year'),
    detailField('ISBN', edition.isbn, 'isbn'),
    detailField('用户标签（逗号分隔）', work.tags.filter((item) => item.origin === 'user'&&!item.name.startsWith('shelf:')).map((item) => item.name).join(', '), 'tags'),
  );
  const actions = document.createElement('div'); actions.className = 'detail-actions';
  const move=document.createElement('button');move.textContent='移动到所选书架';
  move.onclick=async()=>{try{assertCurrentLibraryWork(work.work_id);state.libraryWork=await request('/api/library/work/shelf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_id:work.work_id,shelf:shelf.value})});await refreshLibrary();notice('书架已更新；原文件位置和研究资格均未改变。');}catch(error){notice(error.message,true);}};
  const save = document.createElement('button'); save.className = 'primary-inline'; save.textContent = '保存人工书目';
  save.onclick = async () => {
    try {
      assertCurrentLibraryWork(work.work_id);
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
      assertCurrentLibraryWork(work.work_id);
      state.libraryWork = await request('/api/library/link', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({work_id:work.work_id})});
      renderWorkDetail(); notice('作品已关联到当前研究项目，原文件仍保持原位。');
    } catch (error) { notice(error.message, true); }
  };
  actions.append(move, save, link); form.append(actions); container.append(form);

  if(work.project_source?.source_id){
    container.append(actionButton(state.language==='en'?'Open this project source':'打开该文献的项目原页',async()=>{
      await loadSource(work.project_source.source_id);setMode('source');render();
    },true));
  }

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
    const add = document.createElement('button'); add.textContent = state.language==='en'?'Adopt and process':'采用并自动清洗';
    add.disabled = file.file_state !== 'matches_registered_version' || !/\.(pdf|docx)$/i.test(file.path);
    add.onclick = () => addLibraryFile(work.work_id, file.file_id).catch((error) => notice(error.message, true));
    heading.append(title, status, open, add); section.append(heading);
    for (const version of file.versions) {
      const card = document.createElement('article'); card.className = `version-card ${version.is_current ? 'current' : ''}`;
      const label = document.createElement('strong'); label.textContent = version.is_current ? '当前精确版本' : '历史版本记录';
      const availability = version.bytes_available ? '当前路径字节可打开' : '仅保留记录，旧字节未归档';
      const values = document.createElement('pre'); values.textContent = `${state.language==='en'?'Version':'版本'}  ${version.version_id}\n${state.language==='en'?'Size':'大小'}  ${formatBytes(version.byte_count)}\n${state.language==='en'?'File time':'文件时间'}  ${new Date(version.modified_ns / 1e6).toLocaleString()}\n${state.language==='en'?'Discovered':'发现时间'}  ${new Date(version.discovered_at).toLocaleString()}\n${state.language==='en'?'Format / pages':'格式 / 页数'}  ${version.format.toUpperCase()} / ${version.page_count ?? (state.language==='en'?'not applicable':'不适用')}\n${state.language==='en'?'Text layer':'文本层'}  ${version.text_layer}\n${state.language==='en'?'Triage':'分诊'}  ${triageLabels[version.triage_state] || version.triage_state}\n${state.language==='en'?'Qualification':'资格'}  ${version.qualification}\nSkill  ${version.skill_name}\n${state.language==='en'?'File available':'文件可用性'}  ${availability}`;
      card.append(label, values); section.append(card);
    }
    container.append(section);
  }
}

async function refreshLibrary() {
  state.snapshot = await request('/api/snapshot');
  state.libraryWorks = state.snapshot.library_works || [];
  renderLibraryShell();
  if (state.libraryWorkId) await loadWork(state.libraryWorkId);
}

async function activateWorkspaceProject(projectId, destination='project') {
  await request('/api/project/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:projectId})});
  state.threadId='';state.thread=null;state.view=null;state.libraryWork=null;state.libraryWorkId='';state.manuscriptId='';state.sectionId='';state.projectWorkspace=null;state.domainAgents=null;state.domainSessionId='';state.domainView=null;
  sessionStorage.removeItem('hrwManuscriptId');sessionStorage.removeItem('hrwSectionId');
  await loadSnapshot();setMode(destination);if(destination==='project')await loadProjectWorkspace();
}

function projectAction(action) {
  if(action==='library_intake'){setMode('library');setLibraryView('intake');return;}
  if(action==='repair_sources'){setMode('agent');state.contextMode='sources';renderContext();return;}
  if(action==='research_design'){setMode('agent');state.contextMode='design';renderContext();return;}
  if(action==='events_or_evidence'){setMode('agent');state.contextMode='events';renderContext();return;}
  if(action==='approve_freeze'){setMode('agent');state.contextMode='writing';renderContext();return;}
  if(['create_manuscript','decide_writing','review_export'].includes(action)){setMode('article');renderAuthoring();}
}

function renderProjectWorkspace() {
  const english=state.language==='en';
  const data=state.projectWorkspace;
  const list=$('projectWorkspaceList');list.replaceChildren();
  const projects=[];
  for(const project of state.snapshot?.workspace?.projects||[]){
    const existing=projects.findIndex((item)=>item.project_id===project.project_id);
    if(existing<0)projects.push(project);
    else if(project.available&&!projects[existing].available)projects[existing]=project;
  }
  for(const project of projects){
    const button=document.createElement('button');button.classList.toggle('selected',project.project_id===state.snapshot.project.project_id);
    button.append(Object.assign(document.createElement('strong'),{textContent:project.title}),Object.assign(document.createElement('small'),{textContent:project.available?`${project.source_count} ${english?'source(s)':'项文献'}`:(english?'Project folder unavailable':'项目目录不可用')}));
    button.disabled=!project.available;button.onclick=()=>activateWorkspaceProject(project.project_id).catch((error)=>notice(error.message,true));list.append(button);
  }
  const createLocal=$('projectWorkspaceCreate');createLocal.textContent=english?'New project in Wenjin workspace':'在问津工作区新建项目';
  const extra=document.createElement('div');extra.className='button-row';
  if(nativeAvailable()){
    extra.append(actionButton(english?'New project in a local folder':'在本地文件夹新建项目',async()=>{const parent=await nativeInvoke('choose_folder');if(!parent)return;const title=window.prompt(english?'Project title':'项目名称');if(!title?.trim())return;await request('/api/project/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,parent_path:parent})});await loadSnapshot();await loadProjectWorkspace();notice(english?'Local project created and selected.':'本地项目已建立并选中。');},true));
    extra.append(actionButton(english?'Open an existing Wenjin project':'打开已有问津项目',async()=>{const path=await nativeInvoke('choose_folder');if(!path)return;await request('/api/project/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_root:path})});await loadSnapshot();await loadProjectWorkspace();notice(english?'Existing project registered and selected.':'已有项目已登记并选中。');}));
  }
  list.append(extra);
  for(const id of ['projectWorkspaceOverview','projectWorkspaceObjects','projectWorkspaceSources','projectWorkspaceNext','projectWorkspaceActivity'])$(id).replaceChildren();
  if(!data){$('projectWorkspaceOverview').append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'Loading project workspace…':'正在读取项目工作区……'}));return;}
  const phaseLabels=english?{setup:'Project setup',materials:'Material processing',design:'Research design',research:'Reading and structured research',evidence:'Evidence and freeze',writing:'Writing',revision:'Revision decision',review:'Review and export'}:{setup:'建立项目',materials:'材料处理',design:'研究设计',research:'阅读与结构化研究',evidence:'证据与冻结',writing:'文章写作',revision:'返修决定',review:'评审与导出'};
  const overview=document.createElement('section');overview.className='project-overview';overview.append(Object.assign(document.createElement('h1'),{textContent:data.project.title}),Object.assign(document.createElement('span'),{className:'project-phase',textContent:phaseLabels[data.phase]||data.phase}),Object.assign(document.createElement('p'),{textContent:english?`Project data: ${data.project.project_root}`:`项目位置：${data.project.project_root}`}));
  if(data.research_design.shared)overview.append(Object.assign(document.createElement('p'),{textContent:`${english?'Approved shared design':'已批准共同计划'}：${data.research_design.shared.title}`}));
  $('projectWorkspaceOverview').append(overview);
  const objectDefinitions=[
    [english?'Sources':'项目文献','sources','library_intake'],[english?'Approved events':'获批事件','approved_events','events_or_evidence'],[english?'Verified evidence':'已核证据','verified_evidence','events_or_evidence'],[english?'Approved freezes':'批准冻结','approved_freezes','approve_freeze'],[english?'Reading jobs':'阅读任务','reading_jobs','events_or_evidence'],[english?'Approved historiography':'批准学术史','approved_historiography','events_or_evidence'],[english?'Manuscripts':'稿件','manuscripts','create_manuscript'],[english?'Reviews':'评审','reviews','review_export'],[english?'Waiting approvals':'等待批准','waiting_approvals','repair_sources']
  ];
  for(const [label,key,action] of objectDefinitions){const node=card(label,String(data.counts[key]??0));node.onclick=()=>projectAction(action);node.tabIndex=0;$('projectWorkspaceObjects').append(node);}
  const sourceBox=card(english?'Project sources':'项目文献',english?'Open a source to inspect page processing, verification, and outstanding anomalies.':'打开文献可查看页面处理、核验状态和待处理异常。');const sourceList=document.createElement('section');sourceList.className='project-source-list';
  for(const source of data.sources){const row=document.createElement('div');row.className='project-source-row';const text=document.createElement('div');text.append(Object.assign(document.createElement('strong'),{textContent:source.title}),document.createElement('br'),Object.assign(document.createElement('small'),{textContent:`${source.processing_state} · ${source.use_state} · ${source.verified_pages||0}/${source.page_count||0} ${english?'verified pages':'已核页'} · ${source.open_anomalies||0} ${english?'open issue(s)':'项待处理'}`}));row.append(text,actionButton(english?'Open pages':'打开原页',async()=>{await loadSource(source.source_id);setMode('source');render();},true));sourceList.append(row);}if(!data.sources.length)sourceList.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No source has been added to this project.':'当前项目还没有文献。'}));sourceBox.append(sourceList);$('projectWorkspaceSources').append(sourceBox);
  const actionLabels=english?{library_intake:'Add or inventory sources',repair_sources:'Resolve source-page issues',research_design:'Establish or approve the research design',events_or_evidence:'Build events or evidence from source pages',approve_freeze:'Review and approve an evidence freeze',create_manuscript:'Create a manuscript',decide_writing:'Decide pending writing proposals',review_export:'Review and export the current manuscript'}:{library_intake:'导入或盘点材料',repair_sources:'处理文献页面问题',research_design:'建立或批准研究计划',events_or_evidence:'从原页建立事件或证据',approve_freeze:'核对并批准证据冻结',create_manuscript:'建立稿件',decide_writing:'处理待审写作提案',review_export:'评审并导出当前稿件'};
  const next=card(english?'Recommended next steps':'建议的下一步',english?'Generated from current project state; these are navigation suggestions, not research conclusions.':'依据当前项目状态生成，只是操作导航，不是研究结论。');const actionList=document.createElement('section');actionList.className='project-next-actions';for(const item of data.next_actions)actionList.append(actionButton(`${actionLabels[item.action]||item.action}${item.count?` (${item.count})`:''}`,()=>projectAction(item.action),true));if(!data.next_actions.length)actionList.append(Object.assign(document.createElement('p'),{textContent:english?'No urgent project action detected.':'当前没有紧急项目操作。'}));next.append(actionList);$('projectWorkspaceNext').append(next);
  if(data.readiness.blockers?.length||data.readiness.warnings?.length)$('projectWorkspaceNext').append(card(english?'Research readiness':'研究准备情况',[...(data.readiness.blockers||[]),...(data.readiness.warnings||[])].join('\n')));
  const activity=card(english?'Recent project activity':'最近项目活动','');const activityList=document.createElement('section');activityList.className='project-activity-list';const activityLabels=english?{project_initialized:'Project created',source_registered:'Source added',pdf_ingested:'PDF processed',block_verified:'Text block verified',page_verified:'Page verified',research_design_approved:'Research design approved',research_event_approved:'Event approved',evidence_freeze_approved:'Evidence freeze approved'}:{project_initialized:'项目建立',source_registered:'文献加入',pdf_ingested:'PDF处理',block_verified:'文本段核验',page_verified:'页面核验',research_design_approved:'研究计划批准',research_event_approved:'事件批准',evidence_freeze_approved:'证据冻结批准'};for(const item of data.recent_activity){const row=document.createElement('div');row.className='project-activity-item';row.append(Object.assign(document.createElement('strong'),{textContent:activityLabels[item.event_type]||(english?'Project record updated':'项目记录更新')}),document.createElement('br'),Object.assign(document.createElement('small'),{textContent:`${item.entity_type} · ${new Date(item.created_at).toLocaleString()}`}));activityList.append(row);}activity.append(activityList);$('projectWorkspaceActivity').append(activity);
}

async function loadProjectWorkspace(){state.projectWorkspace=await request('/api/project/workspace');renderProjectWorkspace();}

function renderDomainAttachmentChips(){
  const box=$('domainAttachmentChips');if(!box)return;box.replaceChildren();
  for(const item of state.domainPendingAttachments){const chip=document.createElement('span');chip.className='attachment-chip';chip.append(document.createTextNode(`${item.original_name} · ${formatBytes(item.byte_count)}`),actionButton('×',()=>{state.domainPendingAttachments=state.domainPendingAttachments.filter((value)=>value.attachment_id!==item.attachment_id);renderDomainAttachmentChips();}));box.append(chip);}
}

function openImagePreview(href,alt=''){
  $('imagePreviewLarge').src=href;$('imagePreviewLarge').alt=alt;$('openImageOriginal').href=href;
  if(!$('imagePreviewDialog').open)$('imagePreviewDialog').showModal();
}

function syncReasoningControls(modeLabelId,modeId,effortLabelId,effortId,controls,modeKey,effortKey){
  const modeLabels={standard:state.language==='en'?'Standard':'标准',deep:state.language==='en'?'Deep reasoning':'深度推理'};
  const effortLabels={low:state.language==='en'?'Low':'低',medium:state.language==='en'?'Medium':'中',high:state.language==='en'?'High':'高',max:state.language==='en'?'Max':'最大'};
  const modes=controls?.modes||[],efforts=controls?.efforts||[],mode=$(modeId),effort=$(effortId);
  mode.replaceChildren(...modes.map((value)=>new Option(modeLabels[value]||value,value)));
  effort.replaceChildren(...efforts.map((value)=>new Option(effortLabels[value]||value,value)));
  state[modeKey]=modes.includes(state[modeKey])?state[modeKey]:(controls?.default_mode||'standard');
  state[effortKey]=efforts.includes(state[effortKey])?state[effortKey]:(controls?.default_effort||'medium');
  if(modes.length)mode.value=state[modeKey];
  if(efforts.length)effort.value=state[effortKey];
  $(modeLabelId).hidden=modes.length<2;
  $(effortLabelId).hidden=efforts.length<2;
}

function renderDomainWorkspace(){
  const english=state.language==='en';
  const sessions=state.domainAgents?.sessions||[];
  const list=$('domainAgentList');list.replaceChildren();
  for(const session of sessions){
    const row=document.createElement('div');row.className='domain-agent-row';
    const button=document.createElement('button');button.classList.toggle('selected',session.session_id===state.domainSessionId);
    button.append(Object.assign(document.createElement('strong'),{textContent:session.display_name||session.title}),Object.assign(document.createElement('small'),{textContent:`${session.agent_tools?.length||0} ${english?'tools':'项工具'} · ${english?'isolated memory':'隔离记忆'}`}));
    button.onclick=()=>loadDomainSession(session.session_id).catch((error)=>notice(error.message,true));
    const remove=actionButton(english?'Uninstall':'卸载',async()=>{if(!window.confirm(english?`Uninstall ${session.display_name||session.plugin_name}? The installed copy and its saved model credentials will be removed. Original ZIPs, source projects, local databases, and project history will remain.`:`卸载 ${session.display_name||session.plugin_name}？将移除问津中的安装副本及其单独保存的模型凭据；原ZIP、来源工程、本地数据库和项目历史不会删除。`))return;try{await request('/api/plugins/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:session.plugin_name})});state.domainSessionId='';state.domainView=null;await loadSnapshot();await loadDomainAgents();notice(english?'Domain Agent uninstalled. Project history and external data were preserved.':'领域 Agent 已卸载；项目历史和外部数据均保留。');}catch(error){notice(error.message,true);}});
    remove.className='domain-agent-remove';row.append(button,remove);list.append(row);
  }
  if(!sessions.length)list.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No ready domain agent is installed. Import one or start the guided creator.':'尚未安装可运行的领域 Agent。可以导入，或使用引导创建。'}));
  const view=state.domainView;
  $('domainAgentTitle').textContent=view?.session?.title||(english?'Choose a domain agent':'选择一个领域 Agent');
  $('domainAgentState').textContent=view?`${view.session.plugin_name} · ${english?'independent thread and memory':'独立线程与记忆'}`:(english?'Select, import, or create an agent.':'请选择、导入或创建一个 Agent。');
  const selectedSession=sessions.find((item)=>item.session_id===state.domainSessionId);
  const domainRole=selectedSession?.model_settings?.roles?.find((item)=>item.id==='domain_reasoning');
  $('domainModelLabel').textContent=domainRole?.provider==='inherit'?`${english?'Inherits':'继承默认'} · ${domainRole?.effective_model||'—'}`:`${domainRole?.effective_provider||'—'} · ${domainRole?.effective_model||'—'}`;
  const roleBox=$('domainModelRoles');roleBox.replaceChildren();
  for(const configured of selectedSession?.model_settings?.roles||[]){
    const inherited=configured.provider==='inherit',disabled=configured.effective_provider==='disabled';
    const status=inherited?`${english?'inherits':'继承'} · ${configured.effective_model||'—'}`:(disabled?(english?'disabled':'未启用'):(configured.effective_model||'—'));
    const button=actionButton(`${english?(configured.label_en||configured.label||configured.id):(configured.label||configured.id)} · ${status}`,()=>openDomainModelRole(configured.id));
    button.classList.toggle('required-missing',Boolean(configured.required&&disabled));roleBox.append(button);
  }
  syncReasoningControls('domainReasoningModeLabel','domainReasoningMode','domainReasoningEffortLabel','domainReasoningEffort',domainRole?.reasoning_controls,'domainReasoningMode','domainReasoningEffort');
  const messages=$('domainMessages');messages.replaceChildren();
  for(const message of view?.messages||[]){
    const node=document.createElement('article');node.className=`message ${message.role}`;
    node.append(Object.assign(document.createElement('small'),{textContent:message.role==='user'?(english?'User':'用户'):(view.session.title||'Domain Agent')}),Object.assign(document.createElement('p'),{textContent:message.content?.text||''}));
    const refs=message.content?.attached_refs||[];
    if(refs.length){const media=document.createElement('div');media.className='domain-message-attachments';for(const item of refs){const href=`/api/thread/attachment/file?id=${encodeURIComponent(item.attachment_id)}`;if((item.media_type||'').startsWith('image/')){const image=document.createElement('img');image.src=href;image.alt=item.original_name||'attachment';image.title=english?'Double-click to open the full image':'双击打开大图';image.ondblclick=()=>openImagePreview(href,image.alt);media.append(image);}else{const link=document.createElement('a');link.className='domain-attachment-link';link.href=href;link.target='_blank';link.textContent=`📎 ${item.original_name||item.attachment_id}`;media.append(link);}}node.append(media);}
    appendQueuedDirectionMenu(node,message,'domain');messages.append(node);
  }
  if(!view)messages.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'Choose a specialist to begin.':'选择一个领域 Agent 后开始。'}));
  const activity=$('domainActivity');activity.replaceChildren();
  const run=view?.runs?.[0];
  if(run){activity.append(card(english?'Current run':'本轮运行',`${run.status} · ${run.model_snapshot.provider} / ${run.model_snapshot.model}${run.model_snapshot.reasoning_mode?` · ${run.model_snapshot.reasoning_mode}/${run.model_snapshot.reasoning_effort}`:''}${run.error?`\n${run.error}`:''}`));for(const call of run.tool_calls||[]){const node=document.createElement('article');node.className='domain-tool-call';node.append(Object.assign(document.createElement('strong'),{textContent:call.tool_name}),Object.assign(document.createElement('small'),{textContent:`${call.status} · ${new Date(call.created_at).toLocaleString()}`}));activity.append(node);}}
  else activity.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'Tool activity will appear here.':'工具过程将在这里显示。'}));
  const artifacts=$('domainArtifacts');artifacts.replaceChildren();
  const values=view?.artifacts||[];
  const appendArtifacts=(target,items)=>{for(const item of items){const node=document.createElement('article');node.className='domain-artifact';const open=()=>nativeInvoke('open_path',{path:item.native_path||item.project_path}).catch((error)=>notice(error.message,true));node.append(Object.assign(document.createElement('strong'),{textContent:item.title}),Object.assign(document.createElement('small'),{textContent:`${item.status} · ${item.project_path}`}));if(nativeAvailable()){node.title=english?'Double-click to open':'双击打开产物';node.ondblclick=open;node.append(actionButton(english?'Open artifact':'打开产物',open,true));}target.append(node);}};
  if(values.length){const recent=document.createElement('section');recent.className='domain-artifact-list';appendArtifacts(recent,values.slice(0,2));artifacts.append(recent);if(values.length>2){const old=document.createElement('details');old.className='domain-artifact-group';const summary=document.createElement('summary');summary.textContent=`${english?'Older artifacts':'较早产物'} (${values.length-2})`;const body=document.createElement('div');body.className='domain-artifact-list';appendArtifacts(body,values.slice(2));old.append(summary,body);artifacts.append(old);}}
  else artifacts.append(Object.assign(document.createElement('p'),{className:'empty',textContent:english?'No candidate artifact yet.':'尚无候选产物。'}));
  renderDomainAttachmentChips();
  $('domainMessageInput').value=state.domainDraft;
  setRunButton($('sendDomainMessage'),run,Boolean(view)&&hasAssignedMainModel());
  updateRunComposerHint('domain',run);
}

function openDomainModelRole(roleId){
  const english=state.language==='en',session=(state.domainAgents?.sessions||[]).find((item)=>item.session_id===state.domainSessionId);
  const settings=session?.model_settings,role=settings?.roles?.find((item)=>item.id===roleId),panel=$('domainModelPanel');
  if(!session||!role)return;
  if($('domainWorkbench').classList.contains('right-collapsed'))$('toggleDomainActivity').click();
  panel.hidden=false;panel.replaceChildren();
  const heading=document.createElement('div');heading.className='button-row';heading.append(Object.assign(document.createElement('strong'),{textContent:english?(role.label_en||role.label||role.id):(role.label||role.id)}),actionButton('×',()=>{panel.hidden=true;panel.replaceChildren();}));panel.append(heading);
  panel.append(Object.assign(document.createElement('small'),{textContent:role.provider==='inherit'?(english?`Currently inherits ${role.effective_model||'no usable model'}`:`当前继承 ${role.effective_model||'尚无可用模型'}`):(english?'Only this domain agent uses this override.':'此处覆盖只影响当前领域 Agent。')}));
  const preset=document.createElement('select');preset.append(new Option(english?'Choose provider preset':'选择服务商预设',''));
  for(const item of settings.provider_presets||[])preset.append(new Option(item.label,item.id));preset.value=role.preset_id||'';
  const provider=document.createElement('select');for(const [value,zh,en] of [['inherit','继承问津角色','Inherit Wenjin role'],['disabled','未启用','Disabled'],['ollama','Ollama','Ollama'],['openai_compatible','OpenAI 兼容接口','OpenAI-compatible API']])provider.append(new Option(english?en:zh,value));provider.value=role.provider||'inherit';
  const model=document.createElement('input');model.value=role.model||'';model.placeholder=role.effective_model||'model';
  const baseUrl=document.createElement('input');baseUrl.value=role.base_url||'';baseUrl.placeholder=role.effective_base_url||'Base URL';
  const apiKey=document.createElement('input');apiKey.type='password';apiKey.autocomplete='new-password';apiKey.placeholder=role.has_secret?(english?'Saved securely; leave blank to keep it':'已安全保存；留空表示不更换'):(english?'API key for this domain agent':'当前领域 Agent 的 API Key');
  const timeout=document.createElement('input');timeout.type='number';timeout.min='5';timeout.max='600';timeout.value=role.timeout_seconds||90;
  const wrap=(label,input)=>{const node=document.createElement('label');node.append(document.createTextNode(label),input);return node;};
  panel.append(wrap(english?'Provider preset':'服务商预设',preset),wrap(english?'Routing':'路由方式',provider),wrap(english?'Model':'模型',model),wrap('Base URL',baseUrl),wrap('API Key',apiKey),wrap(english?'Timeout (seconds)':'超时（秒）',timeout));
  const syncDisabled=()=>{const inherited=['inherit','disabled'].includes(provider.value);model.disabled=baseUrl.disabled=apiKey.disabled=inherited;preset.disabled=inherited;};syncDisabled();provider.onchange=syncDisabled;
  preset.onchange=()=>{const item=(settings.provider_presets||[]).find((value)=>value.id===preset.value);if(!item)return;provider.value=item.provider;baseUrl.value=item.base_url||'';syncDisabled();};
  const actions=document.createElement('div');actions.className='button-row';
  actions.append(actionButton(english?'Refresh models':'刷新模型列表',async()=>{try{const result=await request('/api/domain-model-settings/models',localSessionOptions({plugin_name:session.plugin_name,role_id:role.id,provider:provider.value,base_url:baseUrl.value,api_key:apiKey.value}));const choice=window.prompt(english?'Available models; enter one':'可用模型；请输入要使用的名称',(result.models||[]).join('\n'));if(choice?.trim())model.value=choice.trim();notice(english?'Domain model list loaded.':'领域模型列表已读取。');}catch(error){notice(error.message,true);}}),actionButton(english?'Save for this agent':'保存到当前 Agent',async()=>{try{const result=await request('/api/domain-model-settings/save',localSessionOptions({plugin_name:session.plugin_name,role_id:role.id,provider:provider.value,model:model.value,base_url:baseUrl.value,api_key:apiKey.value,timeout_seconds:Number(timeout.value),preset_id:preset.value||'custom'}));session.model_settings=result;panel.hidden=true;renderDomainWorkspace();notice(english?'This domain model role was saved.':'当前领域 Agent 的模型岗位已保存。');}catch(error){notice(error.message,true);}},true));panel.append(actions);
}

function domainRunNotice(){
  const run=state.domainView?.runs?.[0];
  if(!run)return state.language==='en'?'Domain agent is preparing the run…':'领域 Agent 正在建立本轮运行……';
  const call=run.tool_calls?.at(-1);
  if(call?.status==='RUNNING')return `${call.tool_name} ${state.language==='en'?'is running…':'正在运行……'}`;
  if(call?.status==='COMPLETED')return `${call.tool_name} ${state.language==='en'?'returned; the agent is checking its receipt…':'已返回，Agent 正在核对回执……'}`;
  if(call?.status==='FAILED')return `${call.tool_name} ${state.language==='en'?'failed; the agent is correcting the call…':'未通过，Agent 正在根据参数契约纠正……'}`;
  return state.language==='en'?'Domain agent is reasoning…':'领域 Agent 正在思考并准备调用工具……';
}

async function loadDomainSession(sessionId){state.domainSessionId=sessionId;state.domainView=await request(`/api/domain-agent?id=${encodeURIComponent(sessionId)}`);renderDomainWorkspace();}

async function loadDomainAgents(){
  state.domainAgents=await request('/api/domain-agents');
  if(!state.domainSessionId&&state.domainAgents.sessions?.length)state.domainSessionId=state.domainAgents.sessions[0].session_id;
  if(state.domainSessionId)state.domainView=await request(`/api/domain-agent?id=${encodeURIComponent(state.domainSessionId)}`);
  renderDomainWorkspace();
}

function renderAgentShell() {
  const sharedDesign=state.snapshot?.research_design?.shared_design;
  if(!sharedDesign&&state.planningMode==='guided_execution')state.planningMode='independent_planning';
  $('planningOptions').hidden=!sharedDesign;
  $('planningMode').querySelector('[value="guided_execution"]').disabled=!sharedDesign;
  $('planningMode').value = state.planningMode;
  const projectSelect = $('projectSelect'); projectSelect.replaceChildren();
  for (const project of (state.snapshot?.workspace?.projects || [])) {
    const option = new Option(`${project.title} · ${project.source_count} ${state.language==='en'?'source(s)':'项文献'}`, project.project_id);
    option.selected = project.project_id === state.snapshot?.project?.project_id;
    option.disabled = !project.available; projectSelect.append(option);
  }
  const models = $('modelProfile'); models.replaceChildren();
  let assignedAvailable = false;
  for (const profile of (state.snapshot?.model_profiles || [])) {
    const option = new Option(`${profile.provider} · ${profile.model}`, profile.profile_id);
    option.selected = profile.assigned; option.disabled = profile.status !== 'available'; models.append(option);
    if (profile.assigned && profile.status === 'available') assignedAvailable = true;
  }
  const mainRole=state.modelSettings?.roles?.find((item)=>item.role==='main_reasoning');
  for(const modelName of state.mainDiscoveredModels){if([...models.options].some((option)=>option.textContent.endsWith(` · ${modelName}`)))continue;const option=new Option(`${mainRole?.provider||'model'} · ${modelName}`,`model:${modelName}`);option.selected=modelName===mainRole?.model;models.append(option);}
  const assignedProfile=(state.snapshot?.model_profiles||[]).find((profile)=>profile.assigned&&profile.status==='available');
  syncReasoningControls('reasoningModeLabel','reasoningMode','reasoningEffortLabel','reasoningEffort',assignedProfile?.reasoning_controls,'reasoningMode','reasoningEffort');
  if(!models.options.length)models.append(new Option(state.language==='en'?'No main model configured':'尚未配置主模型',''));
  $('sendMessage').disabled = !assignedAvailable;
  $('sendMessage').title = assignedAvailable ? '' : '当前主模型不可用，请先到项目设置保存并测试一个可用模型。';
  const list = $('threadList'); list.replaceChildren();
  const threads = state.snapshot?.threads || [];
  if (!threads.length) list.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'还没有研究线程。'}));
  for (const thread of threads) {
    const button = document.createElement('button');
    const title = document.createElement('strong'); title.textContent = thread.title;
    const meta = document.createElement('small'); meta.textContent = `${thread.message_count} ${state.language==='en'?'message(s)':'条消息'} · ${thread.latest_run_status || (state.language==='en'?'not run yet':'尚未运行')}`;
    button.append(title, meta); button.classList.toggle('selected', thread.thread_id === state.threadId);
    button.onclick = () => loadThread(thread.thread_id).catch((error) => notice(error.message, true));
    list.append(button);
  }
  if (!state.threadId && threads.length) loadThread(threads[0].thread_id).catch((error) => notice(error.message, true));
  else renderThread();
  renderContext();
}

function hasAssignedMainModel(){
  return Boolean((state.snapshot?.model_profiles||[]).some((profile)=>profile.assigned&&profile.status==='available'&&profile.provider!=='mock'));
}

function renderAttachmentChips(){
  const box=$('attachmentChips');if(!box)return;box.replaceChildren();
  for(const item of state.pendingAttachments){const chip=document.createElement('span');chip.className='attachment-chip';chip.append(document.createTextNode(`${item.original_name} · ${formatBytes(item.byte_count)}`),actionButton('×',()=>{state.pendingAttachments=state.pendingAttachments.filter((value)=>value.attachment_id!==item.attachment_id);renderAttachmentChips();}));box.append(chip);}
}

function showModelOnboarding(){
  const dialog=$('modelOnboarding');
  if(!dialog||hasAssignedMainModel()||sessionStorage.getItem('wenjinModelOnboardingDismissed')==='1')return;
  const english=state.language==='en';
  $('modelOnboardingTitle').textContent=english?'Connect a main model first':'先连接一个主模型';
  $('modelOnboardingText').textContent=english?'Research chat needs a real model. Connect local Ollama or an OpenAI-compatible API such as DeepSeek. Wenjin does not substitute a Mock model.':'研究对话需要真实模型。可以连接本机 Ollama，或填写 DeepSeek 等 OpenAI 兼容接口；问津不会用 Mock 冒充模型。';
  $('configureMainModel').textContent=english?'Configure main model':'设置主模型';
  $('continueWithoutModel').textContent=english?'Not now; use library and project tools':'暂不设置，只使用图书馆和项目功能';
  if(!dialog.open)dialog.showModal();
}

async function loadThread(threadId) {
  state.threadId = threadId;
  state.thread = await request(`/api/thread?id=${encodeURIComponent(threadId)}`);
  renderAgentShell();
}

function latestRun() { return state.thread?.runs?.[0]; }

function setRunButton(button,run,modelAvailable=true){
  const english=state.language==='en';
  if(run?.status==='RUNNING'){button.textContent='■';button.title=english?'Stop at the next safe boundary':'在下一个安全边界停止';button.disabled=false;return;}
  button.textContent=english?'Send':'发送';button.title=modelAvailable?'':(english?'Configure an available main model first':'请先配置可用主模型');button.disabled=!modelAvailable;
}

function updateRunComposerHint(kind,run){
  const box=$(kind==='main'?'messageInput':'domainMessageInput');if(!box)return;
  box.placeholder=run?.status==='RUNNING'
    ?(state.language==='en'?'Type a direction update and press Enter; Shift+Enter for a new line':'输入方向调整并按 Enter 送入当前运行；Shift+Enter 换行')
    :(kind==='main'?(state.language==='en'?'Ask the research agent':'例如：查看当前来源和异常，并把结论保存为研究札记'):(state.language==='en'?'Ask the current domain agent directly':'直接向当前领域 Agent 提出任务'));
}

async function steerRunningRun(runKind,content){
  const payload={run_kind:runKind,action:'steer',content};
  if(runKind==='main')payload.thread_id=state.threadId;else payload.session_id=state.domainSessionId;
  await request('/api/run/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  notice(state.language==='en'?'Direction update queued for the next safe boundary.':'方向调整已排入本轮运行，将在下一个安全边界生效。');
}

async function stopRunningRun(runKind){
  const payload={run_kind:runKind,action:'stop'};
  if(runKind==='main')payload.thread_id=state.threadId;else payload.session_id=state.domainSessionId;
  await request('/api/run/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  notice(state.language==='en'?'Stop requested; current safe work will be preserved.':'已请求停止；当前已完成的安全步骤和回执会保留。');
}

async function reviseQueuedDirection(message,runKind,remove=false){
  const controlId=message.content?.run_control_id;if(!controlId)return;
  let content='';
  if(!remove){content=window.prompt(state.language==='en'?'Edit direction update':'编辑方向调整',message.content?.text||'')?.trim()||'';if(!content)return;}
  await request('/api/run/control/revise',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({control_id:controlId,content,delete:remove})});
  if(runKind==='main')await pollActiveThread(state.threadId);else await loadDomainSession(state.domainSessionId);
  notice(remove?(state.language==='en'?'Queued direction update deleted.':'已删除尚未生效的方向调整。'):(state.language==='en'?'Queued direction update edited.':'已修改尚未生效的方向调整。'));
}

function appendQueuedDirectionMenu(node,message,runKind){
  if(message.run_control_status!=='pending'||!message.content?.run_control_id)return;
  const bar=document.createElement('div');bar.className='queued-direction';bar.append(Object.assign(document.createElement('span'),{textContent:state.language==='en'?'Direction update · queued':'调整方向 · 已排队'}));
  const menu=document.createElement('details');const summary=document.createElement('summary');summary.textContent='…';menu.append(summary,actionButton(state.language==='en'?'Edit':'编辑',()=>reviseQueuedDirection(message,runKind)),actionButton(state.language==='en'?'Delete':'删除',()=>reviseQueuedDirection(message,runKind,true)));bar.append(menu);node.append(bar);
}
function iconAction(symbol,label,handler){const button=actionButton(symbol,handler);button.title=label;button.setAttribute('aria-label',label);return button;}

function messageContent(text, markdown=false){
  const box=document.createElement('div');box.className='message-content';
  const plain=(value)=>{const fragment=document.createDocumentFragment();for(const part of value.split(/(https?:\/\/[^\s<>()，。；：！？、]+)/g)){if(/^https?:\/\//i.test(part)){const link=document.createElement('a');link.href=part;link.target='_blank';link.rel='noreferrer';link.textContent=part;fragment.append(link);}else fragment.append(document.createTextNode(part));}return fragment;};
  const inline=(value)=>{const fragment=document.createDocumentFragment();for(const part of value.split(/(`[^`]+`|\*\*[^*]+\*\*)/)){if(part.startsWith('**')&&part.endsWith('**'))fragment.append(Object.assign(document.createElement('strong'),{textContent:part.slice(2,-2)}));else if(part.startsWith('`')&&part.endsWith('`'))fragment.append(Object.assign(document.createElement('code'),{textContent:part.slice(1,-1)}));else fragment.append(plain(part));}return fragment;};
  if(!markdown){const p=document.createElement('p');p.append(plain(text));box.append(p);return box;}
  let list=null;
  for(const raw of text.split('\n')){const line=raw.trimEnd();if(!line.trim()){list=null;continue;}const heading=line.match(/^(#{2,4})\s+(.+)$/);const bullet=line.match(/^[-*]\s+(.+)$/);if(heading){list=null;const node=document.createElement(heading[1].length===2?'h3':'h4');node.append(inline(heading[2]));box.append(node);}else if(bullet){if(!list){list=document.createElement('ul');box.append(list);}const item=document.createElement('li');item.append(inline(bullet[1]));list.append(item);}else{list=null;const node=document.createElement('p');node.append(inline(line));box.append(node);}}
  return box;
}

function renderThread() {
  $('threadTitle').textContent = state.thread?.thread?.title || (state.language==='en'?'Start a research thread':'新建一个研究线程');
  const run = latestRun();
  const historyCount=run?.model_snapshot?.history_message_ids?.length||0;
  const toolFailureCount = run?.tool_calls?.filter((call) => call.status === 'FAILED').length || 0;
  const savedArtifactCount=run?.artifact_receipt?.saved_artifact_count||0;
  const outcome = run?.status === 'FAILED' && run.error
    ? `${savedArtifactCount?` · 研究产物已保存（${savedArtifactCount}项），最终回复失败`:''} · 原因：${friendlyError(run.error)}`
    : run?.status === 'COMPLETED' && toolFailureCount
      ? ` · 本轮记录 ${toolFailureCount} 次工具错误`
      : '';
  $('runState').textContent = run ? `${run.status} · ${run.model_snapshot.provider} / ${run.model_snapshot.model} · ${run.model_snapshot.planning_mode === 'independent_planning' ? (state.language==='en'?'current question':'当前问题') : (state.language==='en'?`shared plan · ${historyCount} related message(s)${run.model_snapshot.history_truncated?' (truncated)':''}`:`沿用研究计划 · ${historyCount}条相关对话${run.model_snapshot.history_truncated?'（已裁剪）':''}`)}${outcome}` : (state.language==='en'?'Conversation and run state are stored in the local project.':'对话与运行状态会保存在本地项目中');
  setRunButton($('sendMessage'),run,hasAssignedMainModel());
  updateRunComposerHint('main',run);
  const messages = $('messages'); messages.replaceChildren();
  for (const message of (state.thread?.messages || [])) {
    const card = document.createElement('article'); card.className = `message ${message.role}`;
    const role = document.createElement('small'); role.textContent = message.role === 'user' ? (state.language==='en'?'User':'用户') : 'Research Agent';
    const text = messageContent(publicMessageText(message),message.role==='assistant');
    card.append(role, text);
    const actions=document.createElement('div');actions.className='message-actions';
    actions.append(iconAction('⧉',state.language==='en'?'Copy':'复制',()=>navigator.clipboard.writeText(publicMessageText(message))),iconAction('❞',state.language==='en'?'Quote':'引用',()=>{$('messageInput').value+=`${$('messageInput').value?'\n\n':''}> ${publicMessageText(message).replaceAll('\n','\n> ')}`;$('messageInput').focus();}),iconAction('⑂',state.language==='en'?'Branch chat':'分支聊天',async()=>{const title=window.prompt(state.language==='en'?'Branch title':'分支对话名称',`${state.thread.thread.title} · ${state.language==='en'?'branch':'分支'}`);if(!title?.trim())return;const thread=await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,parent_thread_id:state.threadId})});state.threadId=thread.thread_id;await refreshAgentSnapshot();notice(state.language==='en'?'Branched chat created.':'已从当前对话建立分支。');}));
    card.append(actions);
    if (message.context_binding) {
      const context = document.createElement('small'); context.className = 'message-context';
      const binding = message.context_binding;
      const parts=[];
      if(binding.manuscript_id)parts.push(`${state.language==='en'?'Manuscript':'稿件'} ${binding.manuscript_id}`,`${state.language==='en'?'Revision':'修订'} ${binding.revision_id||'—'}`,`${state.language==='en'?'Section':'章节'} ${binding.section_id||'—'}`);
      if(binding.selection_hash)parts.push(state.language==='en'?'selection saved':'选区已保存');
      if(binding.attached_refs?.length)parts.push(`${state.language==='en'?'Attachments':'附件'} ${binding.attached_refs.map((item)=>item.original_name||item.attachment_id).join('、')}`);
      context.textContent=parts.join(' · ');
      if(parts.length)card.append(context);
    }
    appendQueuedDirectionMenu(card,message,'main');
    messages.append(card);
  }
  if(run?.events?.length){
    const process=document.createElement('details');process.className='message process';process.open=true;
    const summary=document.createElement('summary');summary.textContent=state.language==='en'?`Run activity · ${run.status}`:`运行过程 · ${run.status}`;process.append(summary);
    for(const event of run.events.slice(-12)){
      if(!['run_started','tool_started','tool_completed','tool_correction_requested','tool_retry_blocked','approval_requested','approval_auto_decided','model_action_invalid','model_request_retry','run_failed','run_completed','domain_run_started','domain_tool_started','domain_tool_progress','domain_tool_completed','domain_run_completed','domain_run_failed'].includes(event.event_type))continue;
      const row=document.createElement('div');row.className='inline-run-event';const tool=event.payload?.tool?` · ${publicToolName(event.payload.tool)}`:'';const detail=event.event_type==='domain_tool_progress'&&event.payload?.message?` · ${event.payload.message}`:'';row.textContent=`${publicEventTitle(event.event_type)}${tool}${detail} · ${new Date(event.created_at).toLocaleTimeString()}`;process.append(row);
    }
    process.append(Object.assign(document.createElement('small'),{textContent:state.language==='en'?'Operational status and tool receipts only; hidden chain-of-thought is never shown.':'这里只显示操作状态、工具与审批回执，不显示模型隐藏思维链。'}));messages.append(process);
  }
  if (!state.thread) messages.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'创建线程后，即可围绕当前项目、来源和页面开展研究。'}));
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

function visibleJournalTemplates(authoring) {
  const language=state.language==='en'?'en':'zh-CN';
  return (authoring?.journal_templates||[]).filter((item)=>{
    const declared=item.requirements?.language;
    return !declared||declared===language||item.origin==='user';
  });
}

function selectedHistoriography(authoring) {
  if(Array.isArray(state.historiographyEntryIds))state.historiographyEntryIds={};
  const approved=new Set((authoring.historiography||[]).filter((item)=>String(item.status).toLowerCase()==='approved').map((item)=>item.entry_id));
  const ids=(state.historiographyEntryIds[state.sectionId]||[]).filter((value)=>approved.has(value));
  state.historiographyEntryIds[state.sectionId]=ids;
  sessionStorage.setItem('hrwHistoriographyEntryIds',JSON.stringify(state.historiographyEntryIds));
  return (authoring.historiography||[]).filter((item)=>ids.includes(item.entry_id));
}

function explicitResearchRefs(authoring, evidenceItems=[]) {
  return [
    ...selectedHistoriography(authoring).map((item)=>({kind:'historiography_entry',entry_id:item.entry_id,source_refs:item.source_refs||[]})),
    ...historiographyPageRefs(authoring).map((value)=>{const [source_id,page_id]=value.split('@');return {kind:'source_page',source_id,page_id};}),
    ...evidenceItems.map((item)=>({kind:'source_page',evidence_id:item.evidence_id,page_id:item.page_id||'',source_version_id:item.source_version_id||''})),
  ];
}

function historiographyPageRefs(authoring) {
  const sourceIds=new Set(selectedHistoriography(authoring).flatMap((item)=>item.source_refs||[]).map(String));
  return [...new Set((authoring.reading_jobs||[]).flatMap((job)=>job.notes||[])
    .filter((note)=>sourceIds.has(String(note.source_id)))
    .flatMap((note)=>(note.page_refs||[]).map((ref)=>`${note.source_id}@${ref.page_id||''}`))
    .filter((value)=>!value.endsWith('@')))];
}

function renderMaterialClosure(container, section, authoring) {
  const english=state.language==='en';
  const jobs=authoring.reading_jobs||[], notes=jobs.flatMap((job)=>job.notes||[]);
  const hist=authoring.historiography||[], approved=hist.filter((item)=>String(item.status).toLowerCase()==='approved');
  const selected=selectedHistoriography(authoring);
  const sectionText=section?.content||'';
  const cited=selected.filter((item)=>sectionText.includes(item.entry_id)||item.source_refs?.some((ref)=>sectionText.includes(String(ref))));
  const refs=new Set(selected.flatMap((item)=>item.source_refs||[]).map(String));
  const verified=(state.snapshot.sources||[]).filter((item)=>refs.has(item.source_id)&&item.citation_verification_status==='HUMAN_VERIFIED').length;
  container.append(card(english?'Research material closure':'材料闭环',english
    ? `Reading notes: ${notes.length} (${jobs.filter((job)=>job.status==='completed').length}/${jobs.length} jobs completed)\nHistoriography: ${hist.length-approved.length} candidates / ${approved.length} approved; ${selected.length} selected for this section\nIn-text use: ${cited.length}/${selected.length} selected entries or sources cited\nBibliography verification: ${verified}/${refs.size} selected sources human-verified`
    : `已读研究：${notes.length} 份札记（${jobs.filter((job)=>job.status==='completed').length}/${jobs.length} 个任务完成）\n学术史：${hist.length-approved.length} 条候选 / ${approved.length} 条批准；本节选 ${selected.length} 条\n正文引用：${cited.length}/${selected.length} 条已出现来源或条目标识\n书目核验：${verified}/${refs.size} 个所选来源已人工核验`));
}

function renderResearchDesign(container) {
  const design = state.snapshot.research_design || {versions:[]};
  const baseline = design.researcher_baseline;
  const shared = design.shared_design;
  const summary = document.createElement('section'); summary.className = 'context-form';
  summary.append(
    card('研究者意图基线（仅供研究者保存与比较）', baseline
      ? `${baseline.title} · ${baseline.design_id}。这是研究者已外化、可修订的研究认知轨迹，不是心理画像或来源证据。`
      : '尚未批准。可从旧对话恢复研究方向，但须区分原话、复原和推断待确认。'),
    card('共同批准研究设计（执行时加载）', shared
      ? `${shared.title} · ${shared.design_id}。这是人机讨论后由研究者批准的可执行版本。`
      : '尚未批准。研究者意图不会自动变成共同研究设计。'),
  );
  container.append(summary);

  const form = document.createElement('section'); form.className = 'context-form';
  const role = document.createElement('select'); role.id = 'designRole';
  role.append(new Option('研究者意图基线（研究者自存）','researcher_baseline'), new Option('共同研究设计','shared_design'));
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
    if (!state.snapshot.sources.length) container.append(card(state.language==='en'?'No project source yet':'项目还没有文献', state.language==='en'?'Add a work from the library or import a PDF from the top bar.':'从图书馆加入书籍，或在顶部导入 PDF。'));
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
    const authForm = document.createElement('section'); authForm.className = 'context-form';
    const database = document.createElement('select'); database.id = 'authenticatedDatabase';
    for (const name of ['CNKI','读秀','国家哲学社会科学文献中心','学校发现系统','其他已登录数据库']) database.append(new Option(name,name));
    const databaseLabel = document.createElement('label'); databaseLabel.textContent = '已登录数据库'; databaseLabel.append(database);
    authForm.append(databaseLabel, formField('检索式（保存为任务包）', 'authenticatedQuery'), formField('自定义入口网址（可留空）', 'authenticatedStartUrl'));
    authForm.append(actionButton('建立可见检索任务', async () => {
      state.retrievalRecord = await request('/api/research/authenticated-task', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({database:database.value, query:$('authenticatedQuery').value, start_url:$('authenticatedStartUrl').value})});
      await refreshResearch('已建立检索任务；请在可见浏览器中登录、检索，并把题录送回收件箱。');
      state.retrievalRecord = await request(`/api/research/record?id=${encodeURIComponent(state.retrievalRecord.record_id)}`); renderContext();
    }, true)); container.append(authForm);
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
    if (state.retrievalRecord?.provider === 'authenticated_browser') {
      const capture = document.createElement('section'); capture.className = 'context-form';
      const open = document.createElement('a'); open.href = state.retrievalRecord.request_url; open.target = '_blank'; open.textContent = '打开数据库（用户可见会话）'; capture.append(open);
      const help = document.createElement('p'); help.textContent = '每行一条：题名｜作者｜年份｜刊名｜详情页网址。验证码、授权和下载确认请在浏览器中亲自处理。'; capture.append(help);
      const textarea = document.createElement('textarea'); textarea.placeholder = '题名｜作者｜年份｜刊名｜https://...'; capture.append(textarea);
      capture.append(actionButton('批量送入检索收件箱', async () => {
        const items = textarea.value.split(/\r?\n/).filter(line => line.trim()).map(line => { const [title,authors,year,container,url] = line.split('｜'); return {title,authors,year,container,url}; });
        state.retrievalRecord = await request('/api/research/authenticated-results', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({record_id:state.retrievalRecord.record_id, items})}); renderContext(); notice('题录已进入收件箱，资格仍为 DISCOVERED。');
      }, true)); container.append(capture);
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
      formField('冻结包标题', 'eventFreezeTitle', '逐事件比较正式证据包'),
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
        await refreshResearch('逐事件冻结包已创建，仍需用户人工批准。');
      }, true),
    );
    renderEventDraft(); container.append(eventForm);

    const form = document.createElement('section'); form.className = 'context-form'; form.append(formField('冻结包标题', 'freezeTitle', '试写证据包'));
    for (const claim of claims) { const label = document.createElement('label'); const check = document.createElement('input'); check.type='checkbox'; check.value=claim.claim_id; check.disabled=!claim.evidence.length; label.append(check, document.createTextNode(claim.text)); form.append(label); }
    form.append(actionButton('创建待批准冻结包', async () => {
      const claim_ids = [...form.querySelectorAll('input[type=checkbox]:checked')].map((item)=>item.value);
      await request('/api/freeze/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('freezeTitle').value, claim_ids})}); await refreshResearch('冻结包已创建，等待用户批准。');
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
    const memoryTargets=state.snapshot.memory_adapter?.targets||{};
    for (const item of research.memory_candidates || []) { const node = card(item.category, `${item.content}\n来源：${item.source_refs.join('、')} · ${item.status}`); if(item.status==='candidate') node.append(actionButton('批准留在本项目候选区', async()=>{await request('/api/memory/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:item.candidate_id,approved:true})}); await refreshResearch('候选已批准留在本项目；仍未同步到任何外部长期记忆库。');},true)); if(item.status==='approved_local'){for(const [target,label] of [['historical','提升到史学记忆收件箱'],['engineering','提升到工程记忆收件箱']]){const button=actionButton(label,async()=>{await request('/api/memory/promote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:item.candidate_id,target})});await loadSnapshot();notice(`${label}已完成；外部记忆中仍为 draft，等待进一步审核。`);},true);button.disabled=!memoryTargets[target]?.writable;node.append(button);}} container.append(node); }
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
  canvas.style.fontSize=`${16*state.editorZoom}px`;state.editorDirty=false;
  const section = documentSection();
  if (!section) {
    canvas.append(Object.assign(document.createElement('p'), {className:'empty', textContent:state.language==='en'?'Choose a manuscript section to begin editing.':'选择稿件章节后开始编辑。'}));
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
      text: (() => {
        const clone=node.cloneNode(true);
        clone.querySelectorAll('.note-marker').forEach((marker)=>marker.remove());
        return clone.innerText.trim().replaceAll('\\n', '\n');
      })(),
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
  if (!startElement || startElement !== endElement) return state.selection || {text:'',nodeId:'',offset:0};
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
  if(state.writingSelection?.base_version_id&&state.writingSelection.base_version_id!==section?.current_version_id) state.writingSelection=null;
  sessionStorage.setItem('hrwManuscriptId', state.manuscriptId);
  sessionStorage.setItem('hrwSectionId', state.sectionId);
  const list = $('manuscriptList'); list.replaceChildren();
  for (const item of manuscripts) {
    const node = document.createElement('article'); node.className = 'manuscript-row';
    node.append(Object.assign(document.createElement('h3'), {textContent:item.title}));
    for (const part of item.sections) {
      const button = document.createElement('button'); button.textContent = `${part.section_order}. ${part.heading}`;
      button.classList.toggle('selected', part.section_id === state.sectionId);
      button.onclick = () => { state.manuscriptId=item.manuscript_id; state.sectionId=part.section_id; state.proposalId=''; state.writingSelection=null; sessionStorage.setItem('hrwManuscriptId',state.manuscriptId);sessionStorage.setItem('hrwSectionId',state.sectionId);renderAuthoring(); };
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
  else state.proposalId = '';
  $('sectionProposal').value = proposal?.proposed_content || '';
  const templateSelect=$('exportTemplate'); const previous=templateSelect.value||localStorage.getItem('hrw.exportTemplate'); templateSelect.replaceChildren();
  for(const template of visibleJournalTemplates(state.snapshot.authoring)) templateSelect.append(new Option(journalTemplateLabel(template),template.template_id));
  templateSelect.value=previous||(state.language==='en'?'builtin-english-history-chicago-nb':'builtin-history-research');
  if(!templateSelect.value) templateSelect.value=state.language==='en'?'builtin-english-history-chicago-nb':'builtin-history-research';
  templateSelect.onchange=()=>localStorage.setItem('hrw.exportTemplate',templateSelect.value);
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
    const formalDraftReady=readiness.formal_draft_ready ?? readiness.status==='READY';
    const detail=formalDraftReady
      ? [`依据 ${readiness.design_title}，当前可使用人工批准的冻结证据开展正式分节写作。`,
         '这不是投稿就绪结论；还须对当前稿件、期刊模板、引注、作者信息和导出警告逐项检查。',
         ...(readiness.warnings||[])].join('\n')
      : [...(readiness.blockers||[]),...(readiness.warnings||[])].join('\n');
    const gate=card(formalDraftReady?'正式写作条件已满足｜投稿仍待检查':'继续研究｜尚未达到正式写作条件',detail);
    gate.classList.add(formalDraftReady?'gate-ready':'gate-blocked');
    container.append(gate);
  }
  renderMaterialClosure(container,section,authoring);
  if (state.authoringMode === 'dialogue') {
    const threads = state.snapshot.threads || [];
    const form = document.createElement('section'); form.className = 'context-form';
    const select = document.createElement('select'); select.id = 'manuscriptThread';
    select.append(new Option(state.language==='en'?'Choose research thread':'选择研究线程', ''));
    for (const thread of threads) select.append(new Option(thread.title, thread.thread_id));
    select.value = state.threadId || '';
    const label = document.createElement('label'); label.textContent = state.language==='en'?'Same project main Agent':'同一个项目主 Agent'; label.append(select);
    form.append(label, formField(state.language==='en'?'Discuss the current section or selection':'围绕当前章节或选区讨论', 'manuscriptMessage', '', true));
    form.append(actionButton('新建稿件讨论线程', async()=>{
      const created = await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`稿件讨论｜${selectedManuscript()?.title || '未命名稿件'}`})});
      state.threadId=created.thread_id; await refreshAuthoring('已建立项目级稿件讨论线程。');
    }));
    form.append(actionButton('带上下文发送', async()=>{
      if (!select.value) throw new Error('请先在研究对话中新建或选择一个线程。');
      const selection = currentSelectionContext();
      const context = {manuscript_id:state.manuscriptId, revision_id:state.document?.current_revision_id || '', section_id:state.sectionId, node_id:selection.nodeId, selection_text:selection.text, attached_refs:explicitResearchRefs(authoring)};
      state.threadId = select.value;
      state.thread = await request('/api/agent/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({thread_id:select.value,content:$('manuscriptMessage').value,context})});
      await refreshAuthoring('消息已保存，并固定到当前稿件修订与选区；不会自动写入正文。');
    }, true)); container.append(form);
    container.append(card(state.language==='en'?'Context boundary':'上下文边界', state.language==='en'?`Manuscript ${state.manuscriptId || '—'}\nRevision ${state.document?.current_revision_id || '—'}\nSection ${state.sectionId || '—'}\nExploratory discussion remains in the thread by default.`:`稿件 ${state.manuscriptId || '—'}\n修订 ${state.document?.current_revision_id || '—'}\n章节 ${state.sectionId || '—'}\n灵感讨论默认只留在对话。`));
  } else if (state.authoringMode === 'notes') {
    const selection=state.selection||{text:'',nodeId:'',offset:0};
    container.append(card('当前注释位置', selection.nodeId ? `选区：“${selection.text || '光标位置'}”\n段落 ${selection.nodeId} · 字符位置 ${selection.offset}` : '先在正文同一段落中选中文字，再点击“插入注释”。'));
    const form=document.createElement('section'); form.className='context-form';
    const template=document.createElement('select'); template.id='noteTemplate';
    for(const item of visibleJournalTemplates(authoring)) template.append(new Option(journalTemplateLabel(item),item.template_id));
    template.value=$('exportTemplate').value||(state.language==='en'?'builtin-english-history-chicago-nb':'builtin-history-research');
    template.onchange=()=>{$('exportTemplate').value=template.value;};
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
    for (const revision of state.document.revisions || []) container.append(card(revision.revision_id, `${revision.source_format} · ${revision.status} · ${new Date(revision.created_at).toLocaleString()}`));
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
    const externalSource=document.createElement('select');externalSource.id='styleProfileExternalSource';externalSource.append(new Option('选择已核全文的外部论文',''));
    for(const item of state.snapshot.sources||[]) if(item.citation_verification_status==='HUMAN_VERIFIED') externalSource.append(new Option(item.title,item.source_id));
    const externalSourceLabel=document.createElement('label');externalSourceLabel.textContent='外部作者论文（必须已核书目与全文）';externalSourceLabel.append(externalSource);profileForm.append(externalSourceLabel);
    container.append(card('文风样本与研究来源分开','研究来源用于支持论断，不能充作文风样本。文风画像仅收录同一作者、已核全文的独立论文：最低 3 篇，建议 5 篇；单篇论文或一部专著只能作为一次观察，不能宣称“已经学会”。工作台只保存高层特征，不自动抓取或模仿具体作者。'));
    profileForm.append(actionButton('用当前整篇已核稿件建立候选画像',async()=>{
      await request('/api/style-profile/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,name:$('styleProfileName').value,owner_label:$('styleProfileOwner').value,scope:$('styleProfileScope').value})});
      await refreshAuthoring('已生成 OBSERVED_ONCE 文风候选；只保存高层特征和版本指纹，不保存第二份全文。');
    }));
    profileForm.append(actionButton('用外部已核全文论文建立候选画像',async()=>{
      if(!externalSource.value)throw new Error('请选择一篇已核全文的外部论文。');
      await request('/api/style-profile/create-external',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:externalSource.value,name:$('styleProfileName').value,owner_label:$('styleProfileOwner').value,scope:$('styleProfileScope').value})});
      await refreshAuthoring('已建立外部论文文风候选；研究来源与文风来源保持分离。');
    }));container.append(profileForm);
    for(const profile of authoring.style_profiles||[]){
      const features=profile.features||{};
      const sampleCount=(profile.samples||[]).length;
      const node=card(`${profile.name} · ${profile.status}`,`${profile.owner_label} · ${profile.scope}\n${sampleCount} 篇同一作者已核全文样本：最低 3 篇，建议 5 篇；不足时仅为候选观察，不能宣称已经学会。\n中位段长 ${features.median_paragraph_chars||0} 字 · 中位句长 ${features.median_sentence_chars||0} 字 · 材料坐标开篇 ${Math.round((features.factual_opening_ratio||0)*100)}%\n仅保存高层特征与样本指纹；不自动模仿作者。`);
      if(profile.status!=='REJECTED') node.append(actionButton('把当前整篇稿件加入此画像',async()=>{await request('/api/style-profile/add-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profile.profile_id,manuscript_id:state.manuscriptId})});await refreshAuthoring('新样本已加入；原有批准状态已回退，须按新的聚合画像重新决定。');}));
      if(profile.status!=='REJECTED'&&(profile.samples||[]).every((sample)=>sample.sample_role==='external_verified_article')) node.append(actionButton('把选中的外部论文加入此画像',async()=>{if(!externalSource.value)throw new Error('请选择一篇已核全文的外部论文。');await request('/api/style-profile/add-external-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profile.profile_id,source_id:externalSource.value})});await refreshAuthoring('外部论文样本已加入；满三篇仍须人工决定，建议补足五篇。');}));
      if(['OBSERVED_ONCE','RECURRING','AUTHOR_APPROVED'].includes(profile.status)){
        const decide=async(approved)=>{const reviewer=window.prompt('决定人');if(!reviewer?.trim())return;const reason=window.prompt('批准或拒绝依据');if(!reason?.trim())return;const result=await request('/api/style-profile/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profile.profile_id,approved,reviewer,reason})});await refreshAuthoring(!approved?'文风候选已拒绝，不会再次套用。':result.status==='STABLE_PROFILE'?'文风画像已满足最低 3 篇并获批准，可在写作时选择。':'已记录作者批准，但样本不足 3 篇，仍不会进入写作选择。');};
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
    operation.append(new Option('保真润色','polish'), new Option('证据保真扩写','expand'), new Option('依据已批准正文生成摘要/投稿信息','metadata_draft'), new Option('史学去模板化（证据保真）','historical_humanize'), new Option('基于冻结证据分节写作','section_draft'));
    const operationLabel=document.createElement('label'); operationLabel.textContent='操作'; operationLabel.append(operation);
    const selectionOnly=document.createElement('input');selectionOnly.type='checkbox';selectionOnly.id='writingSelectionOnly';
    const selectionOnlyLabel=document.createElement('label');selectionOnlyLabel.append(selectionOnly,document.createTextNode('仅返修当前选区（保留整节其余内容）'));
    const selectedPassage=state.writingSelection;
    const selectionStatus=document.createElement('small');selectionStatus.id='writingSelectionStatus';
    selectionStatus.textContent=selectedPassage?`当前选区 ${selectedPassage.text.length} 字符 · ${(selectedPassage.node_ids||[]).length} 个连续段落`:'尚未在正文中选择可定位的连续文字。';
    const skill=document.createElement('select');skill.id='writingSkill';
    if(humanizerSkill) skill.append(new Option(`historical-humanizer-zh · ${humanizerSkill.sha256.slice(0,12)}…`,humanizerSkill.name));
    else skill.append(new Option('未发现史学语言技能',''));
    const skillLabel=document.createElement('label');skillLabel.textContent='史学语言技能版本';skillLabel.append(skill);
    const styleProfile=document.createElement('select');styleProfile.id='writingStyleProfile';styleProfile.append(new Option('不套用个人文风画像',''));
    for(const item of authoring.style_profiles||[]) if(item.status==='STABLE_PROFILE'&&(item.samples||[]).length>=3) styleProfile.append(new Option(`${item.name} · ${item.status} · ${(item.samples||[]).length} 篇`,item.profile_id));
    const styleProfileLabel=document.createElement('label');styleProfileLabel.textContent='至少 3 篇同作者已核全文的稳定文风画像';styleProfileLabel.append(styleProfile);
    const freeze=document.createElement('select'); freeze.id='writingFreeze'; freeze.append(new Option('不使用冻结包',''));
    for (const item of state.snapshot.research?.freezes || []) if(item.status==='approved') freeze.append(new Option(item.title,item.freeze_id));
    const freezeLabel=document.createElement('label'); freezeLabel.textContent='批准的证据冻结包'; freezeLabel.append(freeze);
    const evidenceScope=document.createElement('select');evidenceScope.id='writingEvidenceScope';evidenceScope.multiple=true;evidenceScope.size=7;evidenceScope.disabled=true;
    const evidenceScopeLabel=document.createElement('label');evidenceScopeLabel.textContent='本节允许使用的冻结证据（可多选）';evidenceScopeLabel.append(evidenceScope);
    const historiographyScope=document.createElement('fieldset');historiographyScope.className='historiography-scope';
    const historiographyLegend=document.createElement('legend');historiographyLegend.textContent='本节选用学术史';historiographyScope.append(historiographyLegend);
    for(const item of authoring.historiography||[]){
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.value=item.entry_id;
      const approved=String(item.status).toLowerCase()==='approved';check.disabled=!approved;check.checked=approved&&selectedHistoriography(authoring).some((value)=>value.entry_id===item.entry_id);
      check.onchange=()=>{const current=new Set(state.historiographyEntryIds[state.sectionId]||[]);check.checked?current.add(item.entry_id):current.delete(item.entry_id);state.historiographyEntryIds[state.sectionId]=[...current];sessionStorage.setItem('hrwHistoriographyEntryIds',JSON.stringify(state.historiographyEntryIds));};
      label.append(check,document.createTextNode(`${item.work_title} · ${approved?'已批准':'候选，需批准后方可选'}`));historiographyScope.append(label);
    }
    if(!(authoring.historiography||[]).length)historiographyScope.append(Object.assign(document.createElement('p'),{className:'empty',textContent:'尚无学术史条目。'}));
    const selectionSupplementAllowed=()=>operation.value==='polish'&&selectionOnly.checked&&Boolean(state.writingSelection?.text);
    const populateEvidenceScope=()=>{evidenceScope.replaceChildren();const selectedFreeze=(state.snapshot.research?.freezes||[]).find((item)=>item.freeze_id===freeze.value);const shownEvidence=new Set();for(const claim of selectedFreeze?.payload?.claims||[])for(const item of claim.evidence||[]){if(shownEvidence.has(item.evidence_id))continue;shownEvidence.add(item.evidence_id);evidenceScope.append(new Option(`${item.relation} · 物理页 ${(item.physical_pages||[item.physical_page]).join('–')} · ${item.quote.slice(0,48)}`,item.evidence_id));}const evidenceAllowed=operation.value==='section_draft'||selectionSupplementAllowed();evidenceScope.disabled=!evidenceAllowed||!selectedFreeze;evidenceScopeLabel.firstChild.textContent=selectionSupplementAllowed()?'当前选区允许补充的冻结证据（可多选）':'本节允许使用的冻结证据（可多选）';skill.disabled=operation.value!=='historical_humanize';styleProfile.disabled=operation.value!=='historical_humanize';};
    freeze.onchange=populateEvidenceScope;operation.onchange=populateEvidenceScope;selectionOnly.onchange=populateEvidenceScope;
    form.append(operationLabel, selectionOnlyLabel, selectionStatus, skillLabel, styleProfileLabel, formField('修改或写作要求','writingInstruction','让材料和行动者先于概念，不改变事实、引文与限定',true), freezeLabel, evidenceScopeLabel, historiographyScope);populateEvidenceScope();
    const generate=actionButton('生成待审提案', async()=>{
      const useSelectionSupplement=selectionSupplementAllowed();
      const useFreeze=operation.value==='section_draft'||useSelectionSupplement;
      const evidence_ids=useFreeze?[...evidenceScope.selectedOptions].map((option)=>option.value):[];
      const selectedFreeze=(state.snapshot.research?.freezes||[]).find((item)=>item.freeze_id===freeze.value);
      const evidenceItems=(selectedFreeze?.payload?.claims||[]).flatMap((claim)=>claim.evidence||[]).filter((item)=>evidence_ids.includes(item.evidence_id));
      const historiography_entry_ids=useSelectionSupplement?[]:selectedHistoriography(authoring).map((item)=>item.entry_id);
      if(operation.value==='section_draft'&&!evidence_ids.length) throw new Error('请为本节至少选择一条已冻结证据。');
      if(useSelectionSupplement&&freeze.value&&!evidence_ids.length) throw new Error('请为当前选区补充至少选择一条已冻结证据。');
      let selection=null;
      if(selectionOnly.checked){
        if(operation.value!=='polish')throw new Error('仅返修选区目前只用于保真润色。');
        selection=state.writingSelection;
        if(!selection?.text)throw new Error('请先在正文中选择同一或连续段落的文字。');
        selection={...selection,sha256:await sha256Text(selection.text)};
      }
      const pending=(section.proposals||[]).filter((item)=>item.status==='pending');
      if(pending.length) throw new Error(`本节尚有 ${pending.length} 份待审提案；请先批准或拒绝，再生成新提案。`);
      generate.disabled=true; notice('写作模型正在生成待审提案，请勿重复提交。');
      try {
        const result=await request('/api/writing/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section_id:section.section_id,operation:operation.value,instruction:$('writingInstruction').value,freeze_id:useFreeze?freeze.value:'',evidence_ids,historiography_entry_ids,historiography_page_refs:useSelectionSupplement?[]:historiographyPageRefs(authoring),attached_refs:explicitResearchRefs(authoring,evidenceItems),skill_name:skill.value,style_profile_id:styleProfile.value,selection_only:selectionOnly.checked,base_version_id:section.current_version_id,selection})});
        state.proposalId=result.proposal_id; await refreshAuthoring(result.validation.valid?'写作提案已生成，等待逐项核对。':'提案违反证据契约，已阻断批准。');
        const drawer=document.querySelector('details.proposal-drawer'); drawer.open=true; drawer.scrollIntoView({block:'center'});
      } finally { generate.disabled=false; }
    },true); form.append(generate); container.append(form);
    if (proposal) {
      const problems=[];
      if(proposal.validation.missing_markers?.length) problems.push('缺失受保护内容：'+proposal.validation.missing_markers.join('、'));
      if(proposal.validation.altered_quotes?.length) problems.push('发现未获准或被改写的直接引文：'+proposal.validation.altered_quotes.join('；'));
      if(proposal.validation.invalid_evidence_ids?.length) problems.push('无效证据编号：'+proposal.validation.invalid_evidence_ids.join('、'));
      if(proposal.validation.invalid_new_evidence_ids?.length) problems.push('选区新增了未选择的冻结证据编号：'+proposal.validation.invalid_new_evidence_ids.join('、'));
      if(proposal.validation.malformed_new_evidence_markers?.length) problems.push('选区新增了格式错误的证据标识：'+proposal.validation.malformed_new_evidence_markers.join('、'));
      if(proposal.validation.new_citation_markers?.length) problems.push('选区补证不能同时新增学术史引证：'+proposal.validation.new_citation_markers.join('、'));
      if(proposal.validation.selection_missing_protected_counts?.length) problems.push('选区删改了既有数字、脚注或来源标识：'+proposal.validation.selection_missing_protected_counts.join('、'));
      if(proposal.validation.supplemental_evidence_valid===false) problems.push('选区补充内容没有使用获准的冻结证据，或超出了证据合同。');
      if(proposal.validation.missing_historiography_entry_ids?.length) problems.push('所选学术史未进入正文：'+proposal.validation.missing_historiography_entry_ids.join('、'));
      if(proposal.validation.no_change) problems.push('模型原样返回，未形成实际修改');
      if(proposal.validation.selection_internal_process) problems.push('选区替换文字含内部工作语言，已阻断批准');
      if(proposal.validation.selection_missing_markers?.length) problems.push('选区替换遗漏受保护内容：'+proposal.validation.selection_missing_markers.join('、'));
      if(proposal.validation.selection_kind==='table'&&!proposal.validation.table_structure_valid) problems.push('表格返修结果不是完整有效的 Markdown 表格');
      if(proposal.validation.guard_status==='BLOCKED_PROTECTED_CHANGE') problems.push('精确保护项发生变化，禁止批准');
      if(proposal.operation==='section_draft'&&!proposal.validation.evidence_linked) problems.push('正文没有绑定冻结证据编号');
      if(proposal.validation.character_budget_status==='OUT_OF_RANGE') {
        const label=proposal.validation.character_budget_enforcement==='STRICT'?'字符预算未通过':'字符预算提示';
        problems.push(`${label}：实际 ${proposal.validation.actual_character_count}，要求 ${proposal.validation.requested_character_budget?.min}—${proposal.validation.requested_character_budget?.max}`);
      }
      const visibleWarnings=(proposal.validation.prose_risk_warnings||[]).filter((item)=>item!=='internal_process'||!proposal.proposed_content.includes('[EVID:'));
      const warningLabels={internal_process:'内部工作语言',defensive_cluster:'否定式限定过密',process_exposition:'研究过程说明外露'};
      if(visibleWarnings.length) problems.push('语言风险提示：'+visibleWarnings.map((item)=>warningLabels[item]||item).join('、'));
      const contractChecked=proposal.operation!=='section_draft'||Object.hasOwn(proposal.validation,'evidence_linked');
      const detail=!contractChecked?'旧提案未经过当前证据契约检查，不可直接批准。':(proposal.validation.valid?`证据契约检查通过；仍须人工核对解释。${problems.length?'\n'+problems.join('\n'):''}`:problems.join('\n'));
      const node=card(`${proposal.operation} · ${proposal.status}`, detail);
      node.append(Object.assign(document.createElement('small'),{textContent:`${proposal.validation.selection_only?'选区返修并已回填完整章节 · ':''}提案 ${proposal.proposed_content.length} 字符 · 基础版本 ${proposal.base_version_id} · ${new Date(proposal.created_at).toLocaleString()}`}));
      if(proposal.operation==='historical_humanize') node.append(Object.assign(document.createElement('p'),{textContent:`精确保护：${proposal.validation.guard_status}；事实、归因、因果、范围和限定仍须逐段人工复核。\n段落决定：${(proposal.validation.paragraph_decisions||[]).map((item)=>`${item.paragraph}:${item.decision}`).join(' · ')||'待核'}`}));
      if(proposal.validation.decision_reason) node.append(Object.assign(document.createElement('p'),{textContent:`人工决定：${proposal.validation.decision_reason}`}));
      if(proposal.status==='pending') {
        node.append(formField('决定人','writingReviewer',''),formField('批准或拒绝依据','writingDecisionReason','',true));
        const row=document.createElement('div'); row.className='row';
        const decide=async(approved)=>{const reviewer=$('writingReviewer').value.trim(),reason=$('writingDecisionReason').value.trim();if(!reviewer||!reason)throw new Error('请填写决定人和批准或拒绝依据。');setAuthoringRefreshBusy(true);try{await request('/api/writing/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:proposal.proposal_id,approved,reviewer,reason,edited_content:approved?$('sectionProposal').value:undefined})});state.proposalId='';await refreshAuthoring(approved?'已保存为新的批准章节版本，旧版本仍保留。':'提案已拒绝并记录理由，当前章节未改变。');}finally{setAuthoringRefreshBusy(false);}};
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
    form.append(actionButton('建立有界阅读任务',async()=>{const source_ids=[...form.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);await request('/api/reading/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('readingTitle').value,question:$('readingQuestion').value,mode:mode.value,source_ids,stop_condition:$('readingStop').value})});await refreshAuthoring('阅读任务已建立；尚未读取材料，也未生成札记。请交给 Agent 分批读取。');},true));container.append(form);
    for(const job of authoring.reading_jobs||[]){const node=card(job.title,`${job.mode} · ${job.status} · ${job.notes.length} 份札记`);node.append(Object.assign(document.createElement('p'),{textContent:`问题：${job.question}；停止条件：${job.stop_condition}`}));for(const note of job.notes){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`${note.source_id} · ${note.qualification}`;const pre=document.createElement('pre');pre.textContent=note.content;details.append(summary,pre);node.append(details);}container.append(node);}
  } else if (state.authoringMode === 'historiography') {
    const form=document.createElement('section');form.className='context-form';
    for(const [label,id,area] of [['著作/论文','histWork',false],['核心立场','histPosition',true],['贡献','histContribution',true],['限制','histLimitation',true],['与当前问题关系','histRelevance',true],['来源引用（逗号分隔）','histRefs',false]]) form.append(formField(label,id,'',area));
    form.append(actionButton('保存学术史候选条目',async()=>{await request('/api/historiography/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_title:$('histWork').value,position:$('histPosition').value,contribution:$('histContribution').value,limitation:$('histLimitation').value,relevance:$('histRelevance').value,source_refs:$('histRefs').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean)})});await refreshAuthoring('学术史候选条目已保存，等待研究判断。');},true));container.append(form);
    for(const item of authoring.historiography||[]){
      const approved=String(item.status).toLowerCase()==='approved';const candidate=String(item.status).toLowerCase()==='candidate';
      const node=card(item.work_title,`${approved?'已批准，可供章节选择':candidate?'候选，需人工批准后方可用于写作':item.status} · 来源 ${item.source_refs.join('、')}`);
      node.append(Object.assign(document.createElement('p'),{textContent:`立场：${item.position}\n贡献：${item.contribution}\n限制：${item.limitation}\n关系：${item.relevance}`}));
      if(candidate){const decide=async(approved)=>{const reviewer=window.prompt('决定人');if(!reviewer?.trim())return;const reason=window.prompt('批准或拒绝依据');if(!reason?.trim())return;await request('/api/historiography/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entry_id:item.entry_id,approved,reviewer,reason})});await refreshAuthoring(approved?'学术史条目已批准，可在具体章节中选择。':'学术史候选已拒绝，不会进入写作上下文。');};const row=document.createElement('div');row.className='row';row.append(actionButton('核对来源后批准',()=>decide(true),true),actionButton('拒绝',()=>decide(false)));node.append(row);}
      container.append(node);
    }
  } else if (state.authoringMode === 'review') {
    const manuscript=selectedManuscript();
    if(!manuscript){container.append(card('尚未选择稿件','先创建或导入稿件。'));return;}
    const models=authoring.review_models||{};
    container.append(card('评审独立性边界',`主评审：${models.primary?.available?`${models.primary.provider} / ${models.primary.model}`:'未配置'}。三个角色使用彼此隔离的提示与输出，但同一模型仍可能共享盲点。${models.secondary?.available?`\n交叉评审：${models.secondary.provider} / ${models.secondary.model}`:'\n可在项目设置中另配交叉评审模型。'}`));
    const form=document.createElement('section');form.className='context-form';
    const template=document.createElement('select');template.id='reviewTemplate';
    for(const item of visibleJournalTemplates(authoring)) template.append(new Option(journalTemplateLabel(item),item.template_id));
    template.value=$('exportTemplate').value||(state.language==='en'?'builtin-english-history-chicago-nb':'builtin-history-research');
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
    panel.append(Object.assign(document.createElement('p'), {className:'empty approval-empty', textContent:'暂无待处理事项。'}));
    return;
  }
  const english=state.language==='en';
  const noteApproval=approval.tool_name==='save_research_note'||('title' in approval.request&&'content' in approval.request);
  const card = document.createElement('article'); card.className = 'approval-card';
  const heading = document.createElement('h3'); heading.textContent = noteApproval?(english?'Save research note?':'保存研究札记？'):(english?`Approve ${approval.tool_name}?`:`批准执行 ${approval.tool_name}？`);
  const warning = document.createElement('p'); warning.textContent = noteApproval?(english?'Review or edit the proposal before it is written to the project.':'这是 Agent 的提案。请修改并确认后再写入项目。'):(english?`This action changes computer state. Permission class: ${approval.request.risk||'unspecified'}. Review every argument before approval.`:`该动作会改变电脑状态，权限等级：${approval.request.risk||'未声明'}。批准前请逐项检查参数。`);
  const titleLabel = document.createElement('label'); titleLabel.textContent = english?'Title':'标题';
  const title = document.createElement('input'); title.value = approval.request.title || ''; titleLabel.append(title);
  const contentLabel = document.createElement('label'); contentLabel.textContent = english?'Note content':'札记内容';
  const content = document.createElement('textarea'); content.value = approval.request.content || ''; contentLabel.append(content);
  const requestLabel=document.createElement('label');requestLabel.textContent=english?'Action arguments (JSON)':'动作参数（JSON）';
  const requestEditor=document.createElement('textarea');requestEditor.value=JSON.stringify(approval.request,null,2);requestLabel.append(requestEditor);
  const reviewerLabel = document.createElement('label'); reviewerLabel.textContent = english?'Decision maker':'决定人';
  const reviewer = document.createElement('input'); reviewer.value = $('reviewer').value || 'human-reviewer'; reviewerLabel.append(reviewer);
  const reasonLabel = document.createElement('label'); reasonLabel.textContent = english?'Reason':'决定依据';
  const reason = document.createElement('input'); reason.placeholder = english?'For example: arguments and visible target checked':'例如：已核对动作参数与可见目标'; reasonLabel.append(reason);
  const actions = document.createElement('div'); actions.className = 'approval-actions';
  const approve = document.createElement('button'); approve.className = 'primary-inline'; approve.textContent = english?'Approve':'批准执行';
  const reject = document.createElement('button'); reject.textContent = english?'Reject':'拒绝';
  const decide = async (approved) => {
    if (!reviewer.value.trim() || !reason.value.trim()) throw new Error('请填写决定人和决定依据。');
    let editedRequest;
    try{editedRequest=noteApproval?{title:title.value,content:content.value}:JSON.parse(requestEditor.value);}catch{throw new Error(english?'Action arguments must be valid JSON.':'动作参数必须是有效JSON。');}
    state.thread = await request('/api/approval/decide', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      approval_id:approval.approval_id, approved, reviewer:reviewer.value, reason:reason.value,
      edited_request:editedRequest,
    })});
    await refreshAgentSnapshot(); notice(approved ? (english?'The action was approved and recorded.':'动作已经人工批准并记入审计。') : (english?'The action was rejected; computer and project state were unchanged.':'动作已拒绝，没有改变电脑或项目。'));
  };
  approve.onclick = () => decide(true).catch((error) => notice(error.message, true));
  reject.onclick = () => decide(false).catch((error) => notice(error.message, true));
  actions.append(approve, reject); card.append(heading, warning,...(noteApproval?[titleLabel,contentLabel]:[requestLabel]),reviewerLabel,reasonLabel,actions); panel.append(card);
}

function renderTimeline(run) {
  const timeline = $('runTimeline'); timeline.replaceChildren();
  if (!run) { timeline.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'运行后会显示模型、工具、错误和审批时间线。'})); return; }
  for (const event of [...run.events].reverse()) {
    const eventTitle = publicEventTitle(event.event_type);
    if (!eventTitle) continue;
    const row = document.createElement('article'); row.className = 'timeline-event';
    const title = document.createElement('strong'); title.textContent = eventTitle;
    const meta = document.createElement('small'); meta.textContent = `#${event.sequence} · ${new Date(event.created_at).toLocaleString()}`;
    let detail = '';
    if(event.event_type==='model_action_invalid')detail='模型操作格式未通过；系统最多自动重试一次，内部工具内容未展示。';
    else if(event.event_type==='run_failed'&&(event.payload.artifacts_saved||run?.artifact_receipt?.artifacts_saved))detail=`研究产物已保存（${event.payload.saved_artifact_count||run.artifact_receipt.saved_artifact_count}项），最终回复失败。${friendlyError(event.payload.error||run.error||'未知错误')}`;
    else if (event.payload.tool) detail = publicToolName(event.payload.tool);
    else if (event.payload.error) detail = friendlyError(event.payload.error);
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
  const working='(˶ᵔ ᵕ ᵔ˶) ᵎᵎ';
  if (!run) return `Agent 正在建立本次运行 ${working}`;
  const event = run.events?.at(-1);
  const tool = event?.payload?.tool;
  if (event?.event_type === 'tool_started') return `正在${publicToolName(tool)} ${working}`;
  if (event?.event_type === 'tool_completed') return `${publicToolName(tool)}已完成，Agent 正在决定下一步 ${working}`;
  if (event?.event_type === 'domain_tool_started') return `领域 Agent 正在${publicToolName(tool)} ${working}`;
  if (event?.event_type === 'domain_tool_progress') return `领域Agent · ${event.payload?.message||tool}……`;
  if (event?.event_type === 'domain_tool_completed') return event.payload?.resumable?`${tool} 暂停，可按运行 ${event.payload.run_id||''} 续跑。`:`${tool} 已返回，领域Agent 正在核对回执……`;
  if (event?.event_type === 'domain_run_started') return `领域 Agent 已接手当前任务 ${working}`;
  if (event?.event_type === 'model_request_retry') return `连接有短暂波动，正在自动重试 ${working}`;
  if (event?.event_type === 'domain_run_failed') return `领域Agent 运行失败：${friendlyError(event.payload?.error||'未知错误')}`;
  if (event?.event_type === 'model_action_invalid') return '模型操作格式未通过；系统正在按限制自动重试。';
  if (event?.event_type === 'run_failed' && (event.payload.artifacts_saved||run?.artifact_receipt?.artifacts_saved)) return `研究产物已保存，最终回复失败：${friendlyError(event.payload.error || run.error || '未知错误')}`;
  if (event?.event_type === 'run_failed') return `本次运行失败：${friendlyError(event.payload.error || run.error || '未知错误')}`;
  return `Agent 正在运行 · 已记录 ${event?.sequence || 0} 个步骤 ${working}`;
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

function canonicalNodeText(node) {
  return node?.type==='table'
    ? (node.rows||[]).map((row,index)=>`| ${row.join(' | ')} |${index===0?`\n| ${row.map(()=> '---').join(' | ')} |`:''}`).join('\n')
    : `${node?.type==='subheading'?'### ':''}${node?.text||''}`;
}

function canonicalSectionText(section) {
  return (section?.children||[]).map(canonicalNodeText).join('\n\n').trim();
}

function canonicalNodeStart(nodes,index) {
  const before=(nodes||[]).slice(0,index).map(canonicalNodeText).join('\n\n');
  return before.length+(index>0?2:0);
}

function textOffsetWithin(element, container, offset) {
  const before=document.createRange();before.selectNodeContents(element);before.setEnd(container,offset);
  const fragment=before.cloneContents();fragment.querySelectorAll?.('.note-marker').forEach((marker)=>marker.remove());
  return fragment.textContent.length;
}

function completeTableSelected(range,table) {
  const fragment=range.cloneContents();fragment.querySelectorAll?.('.note-marker').forEach((marker)=>marker.remove());
  const normalize=(value)=>String(value||'').replace(/\s+/g,' ').trim();
  const cells=[...(table?.querySelectorAll?.('th,td')||[])];
  return Boolean(cells.length&&cells.every((cell)=>range.intersectsNode(cell))
    &&normalize(table.textContent)&&normalize(fragment.textContent)===normalize(table.textContent));
}

function captureWritingSelection() {
  const selection=window.getSelection(),section=documentSection(),base=selectedSection()?.content||'';
  if(!selection||selection.isCollapsed||!selection.rangeCount||!$('documentCanvas').contains(selection.anchorNode)){
    state.writingSelection=null;if($('writingSelectionStatus'))$('writingSelectionStatus').textContent='尚未在正文中选择可定位的连续文字。';return null;
  }
  const range=selection.getRangeAt(0);
  const elementFor=(node)=>(node.nodeType===Node.ELEMENT_NODE?node:node.parentElement)?.closest?.('[data-node-id]');
  const startElement=elementFor(range.startContainer),endElement=elementFor(range.endContainer);
  const nodes=section?.children||[],startIndex=nodes.findIndex((node)=>node.node_id===startElement?.dataset.nodeId);
  const endIndex=nodes.findIndex((node)=>node.node_id===endElement?.dataset.nodeId);
  if(startIndex<0||endIndex<startIndex){
    state.writingSelection=null;if($('writingSelectionStatus'))$('writingSelectionStatus').textContent='选区必须位于当前章节的连续内容中。';return null;
  }
  const canonical=canonicalSectionText(section);
  if(canonical!==base.trim()){
    state.writingSelection=null;if($('writingSelectionStatus'))$('writingSelectionStatus').textContent='正文与批准章节尚未同步，保存或同步后再选区返修。';return null;
  }
  const selectedNodes=nodes.slice(startIndex,endIndex+1),tables=selectedNodes.filter((node)=>node.type==='table');
  const baseOffset=base.length-base.trimStart().length;
  if(tables.length){
    const completeSingleTable=(selectedNodes.length===1&&tables.length===1&&startElement===endElement
      &&completeTableSelected(range,startElement));
    if(!completeSingleTable){
      state.writingSelection=null;if($('writingSelectionStatus'))$('writingSelectionStatus').textContent='表格返修必须完整选择一张表；不能选择部分单元格或与段落混选。';return null;
    }
    const start=baseOffset+canonicalNodeStart(nodes,startIndex),text=canonicalNodeText(tables[0]),end=start+text.length;
    if(base.slice(start,end)!==text){
      state.writingSelection=null;if($('writingSelectionStatus'))$('writingSelectionStatus').textContent='表格与批准章节位置不一致，保存或同步后重试。';return null;
    }
    state.writingSelection={start,end,text,node_ids:[tables[0].node_id],kind:'table',base_version_id:selectedSection()?.current_version_id||''};
    if($('writingSelectionStatus'))$('writingSelectionStatus').textContent=`当前选区：完整单表 · ${text.length} 字符`;
    return state.writingSelection;
  }
  const startPrefix=nodes[startIndex].type==='subheading'?4:0,endPrefix=nodes[endIndex].type==='subheading'?4:0;
  const start=baseOffset+canonicalNodeStart(nodes,startIndex)+startPrefix+textOffsetWithin(startElement,range.startContainer,range.startOffset);
  const end=baseOffset+canonicalNodeStart(nodes,endIndex)+endPrefix+textOffsetWithin(endElement,range.endContainer,range.endOffset);
  const text=base.slice(start,end);
  if(!text){state.writingSelection=null;return null;}
  state.writingSelection={start,end,text,node_ids:selectedNodes.map((node)=>node.node_id),kind:'text',base_version_id:selectedSection()?.current_version_id||''};
  if($('writingSelectionStatus'))$('writingSelectionStatus').textContent=`当前选区 ${text.length} 字符 · ${state.writingSelection.node_ids.length} 个连续段落`;
  return state.writingSelection;
}

async function sha256Text(value) {
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte)=>byte.toString(16).padStart(2,'0')).join('');
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
  const english=state.language==='en';
  for (const [index, page] of (state.view?.pages || []).entries()) {
    const button = document.createElement('button');
    button.textContent = page.page_type === 'docx_locator'
      ? `${english?'Segment':'片段'} ${page.physical_page}`
      : `${english?'Page':'第'} ${page.physical_page}${english?'':' 页'}${page.printed_page ? ` · ${page.printed_page}` : ''}`;
    button.classList.toggle('selected', index === state.pageIndex);
    button.classList.toggle('blocked', page.use_state === 'blocked');
    button.onclick = () => { state.pageIndex = index; clearReviewReason(); render(); };
    rail.append(button);
  }
}

function blockCard(block, pageAnomaly) {
  const english=state.language==='en';
  const card = document.createElement('article'); card.className = 'block-card';
  const anomaly = openAnomalies().find((item) => item.scope_type === 'block' && item.target_id === block.block_id);
  card.classList.toggle('blocked', Boolean(anomaly)); card.dataset.order = block.block_order;
  card.dataset.verificationState=block.verification_state||'';
  card.dataset.region = JSON.stringify(block.source_region || null);
  const meta = document.createElement('div'); meta.className = 'block-meta';
  const region = block.source_region ? Object.values(block.source_region).map((v) => Number(v).toFixed(2)).join(', ') : (english?'not located':'未定位');
  const label = document.createElement('span'); label.textContent = `${english?'Block':'块'} ${block.block_order} · ${english?'region':'区域'} ${region}`;
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
    const button = document.createElement('button'); button.textContent = english?'Submit this block':'提交这一小段';
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
    button.textContent = verified ? (english?'Block verified by a person':'此段已人工核验') : (english?'Confirm block against image':'确认此段与原图一致');
    button.disabled = verified;
    button.onclick = async () => {
      try {
        await request('/api/block/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block_id:block.block_id, ...reviewerPayload()})});
        await loadSource(state.view.source.source_id, true); notice('这一段已经与原图逐字核验，可加入证据卡。');
      } catch (error) { notice(error.message, true); }
    };
    const correct = document.createElement('button');
    correct.textContent = pageAnomaly ? (english?'Save this block repair':'保存这一小段修正') : (english?'Save block repair':'保存这段修正');
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

function blockGroup(block) {
  if(block.block_type==='footnote')return 'notes';
  if(['header','footer','page_number'].includes(block.block_type))return 'marginalia';
  return 'body';
}

function appendGroupedBlocks(container, blocks, pageIssue) {
  const labels={body:'正文与标题',notes:'脚注',marginalia:'页眉、页脚与页码'};
  const grouped={body:[],notes:[],marginalia:[]};
  for(const block of blocks)grouped[blockGroup(block)].push(block);
  for(const key of ['body','notes','marginalia']){
    if(!grouped[key].length)continue;
    const details=document.createElement('details');details.className='block-group';details.dataset.group=key;
    const hasIssue=grouped[key].some((block)=>openAnomalies().some((item)=>item.scope_type==='block'&&item.target_id===block.block_id));
    details.open=hasIssue;
    const summary=document.createElement('summary');summary.textContent=`${labels[key]} · ${grouped[key].length} 块${hasIssue?' · 含待复核项':''}`;
    const list=document.createElement('div');list.className='block-group-list';
    for(const block of grouped[key])list.append(blockCard(block,pageIssue));
    details.append(summary,list);container.append(details);
  }
}

function orderedBlockCards(container) {
  return [...container.querySelectorAll('.block-card')].sort((left,right)=>Number(left.dataset.order)-Number(right.dataset.order));
}

function renderBlocks() {
  const page = currentPage(); const container = $('blocks'); container.replaceChildren();
  if (!page) { container.append(Object.assign(document.createElement('p'), {className:'empty', textContent:'导入 PDF 后显示逐页文本。'})); return; }
  const pageIssue = pageAnomaly(page);
  const blocks = page.blocks.length ? page.blocks : [{block_id:'', block_order:1, block_type:'paragraph', effective_text:'', source_region:null}];
  const overview=document.createElement('p');overview.className='block-overview';
  overview.textContent=`本页 ${blocks.length} 个提取块，按内容类型折叠显示。原页、页码、异常与跨页关系仍在本页保持可见；需要修正时展开对应组。`;
  container.append(overview);
  appendGroupedBlocks(container,blocks,pageIssue);
  const locator = page.page_type === 'docx_locator';
  const addBlock = document.createElement('button'); addBlock.type = 'button'; addBlock.textContent = '在本页新增一块';
  addBlock.onclick = () => {const group=container.querySelector('[data-group="body"]');const list=group?.querySelector('.block-group-list')||container;group&&(group.open=true);const nextOrder=Math.max(0,...orderedBlockCards(container).map((card)=>Number(card.dataset.order)))+1;list.append(blockCard({
    block_id: '',
    block_order: nextOrder,
    block_type: 'paragraph',
    effective_text: '',
    source_region: null,
  }, pageIssue));};
  if (!locator) {
    const twoColumn = document.createElement('button');
    twoColumn.type = 'button'; twoColumn.textContent = '按双栏阅读顺序重排';
    twoColumn.onclick = () => {
      const cards = orderedBlockCards(container);
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
      ordered.forEach((item,index)=>{item.card.dataset.order=index+1;});
      const currentBlocks=ordered.map((item)=>({
        block_id:item.card.querySelector('textarea').dataset.blockId,
        block_order:Number(item.card.dataset.order),block_type:item.card.querySelector('.block-type').value,
        effective_text:item.card.querySelector('textarea').value,source_region:item.region,
        verification_state:item.card.dataset.verificationState,
      }));
      for(const group of container.querySelectorAll('.block-group'))group.remove();
      appendGroupedBlocks(container,currentBlocks,pageIssue);
      notice('已生成双栏顺序：请对照原页检查后，再提交整页修正。');
    };
    container.append(twoColumn, addBlock);
  }
  $('pageRepair').hidden = locator;
  $('pageRepair').textContent = pageIssue ? '提交整页修正' : '保存整页结构修正';
  $('pageRepair').onclick = async () => {
    try {
      const cards = orderedBlockCards(container);
      const repaired = cards.map((card,index) => ({
        order: index+1,
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
  button.hidden = !capability?.available || locator || Boolean(pending);
  button.textContent = verified ? '重新用视觉模型核对' : '让视觉模型重识别当前页';
  button.onclick = async () => {
    button.disabled = true;
    try {
      notice(`正在让 ${capability.model} 分析当前原页；结果不会自动写入正文……`);
      await request('/api/ocr/propose', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({page_id:page.page_id,reopen_verified:verified})});
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
  const english=state.language==='en';
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
      textContent:`${relation.relation_id} · ${value === true ? (english?'continuation confirmed':'已确认续接') : value === false ? (english?'no continuation confirmed':'已确认不续接') : (english?'pending':'待确认')}`,
    }));
    const form = document.createElement('div'); form.className = 'relation-form';
    const from = document.createElement('select');
    const to = document.createElement('select');
    for (const block of leftPage?.blocks || []) from.append(new Option(`${english?'Page ':`第`}${leftPage.physical_page}${english?'':'页'} B${block.block_order} · ${block.block_type}`, block.block_id));
    for (const block of rightPage?.blocks || []) to.append(new Option(`${english?'Page ':`第`}${rightPage.physical_page}${english?'':'页'} B${block.block_order} · ${block.block_type}`, block.block_id));
    from.value = relation.from_block_id; to.value = relation.to_block_id;
    const continues = document.createElement('select');
    continues.append(new Option(english?'Confirm continuation':'确认续接', 'true'), new Option(english?'Confirm no continuation':'确认不续接', 'false'));
    continues.value = value === false ? 'false' : 'true';
    const save = document.createElement('button'); save.textContent = english?'Save relation correction':'保存关系更正';
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
  for(const button of $('settingsTabs').querySelectorAll('[data-settings-tab]'))button.classList.toggle('selected',button.dataset.settingsTab===state.settingsTab);
  const appendSetting=(tab,node)=>{node.dataset.settingsSection=tab;if(tab===state.settingsTab)container.append(node);};
  const project = state.snapshot.project || {}; const caps = state.capabilities || {};
  const runtime=state.snapshot.runtime||{};
  const english=state.language==='en';
  appendSetting('runtime',card(english?'Version and project':'版本与项目', `Wenjin ${project.app_version || '—'} · Project schema ${project.schema_version || '—'}\n${english?'Client: ':'客户端：'}${runtime.mode||'browser'}${runtime.desktop_build ? ` · build ${runtime.desktop_build}` : ''} · ${english?'native bridge: ':'原生桥接：'}${state.nativeBridge?`${english?'ready':'已就绪'} ${state.nativeBridge}`:english?'unavailable':'不可用'}\n${project.title || ''} · ${project.project_id || ''}\n${english?'Project data remains local; original files stay read-only.':'项目文件保持本地，原始材料只读。'}`));
  const harness=runtime.harness||{};
  appendSetting('runtime',card(english?'Agent runtime':'Agent 运行内核',`${harness.backend||'codex-app-server'} · SDK ${harness.sdk_version||'—'}\n${english?'Bundled runtime: ':'内置运行时：'}${harness.binary_available?(english?'ready':'可用'):(english?'missing':'缺失')} · ${english?'active hosts: ':'活动主机：'}${harness.active_hosts||0}\n${english?'Projects, library, sources, evidence, writing and Domain Agents use one Codex app-server lifecycle.':'项目、图书馆、史料、证据、写作与领域 Agent 共用一套 Codex app-server 生命周期。'}`));

  const profile=state.snapshot.agent_profile||{};
  const soul=card(english?'Research persona':'研究人格（Soul）',english?'Edit collaboration preferences and prose style here. Evidence, version, privacy, and approval rules are managed separately.':'在这里编辑协作方式与写作偏好；证据、版本、隐私和审批规则由项目设置管理。');
  const soulForm=document.createElement('section');soulForm.className='context-form agent-profile-form';
  const profileFields=[['display_name',english?'Name':'名称'],['description',english?'Purpose':'定位'],['address_user',english?'Address the researcher as':'如何称呼研究者'],['disciplinary_orientation',english?'Disciplinary orientation':'学科取向'],['working_style',english?'Working style':'工作方式'],['writing_style',english?'Writing style':'写作要求'],['initiative',english?'Initiative boundary':'主动性边界'],['custom_instructions',english?'Additional instructions':'研究者补充指令']];
  for(const [key,label] of profileFields){const input=key==='display_name'||key==='address_user'?document.createElement('input'):document.createElement('textarea');input.dataset.profileField=key;input.value=profile[key]||'';const field=document.createElement('label');field.textContent=label;field.append(input);soulForm.append(field);}
  soulForm.append(actionButton(english?'Save a versioned persona':'保存为新版人格',async()=>{try{const payload={};for(const input of soulForm.querySelectorAll('[data-profile-field]'))payload[input.dataset.profileField]=input.value;const result=await request('/api/agent-profile/save',localSessionOptions(payload));state.snapshot.agent_profile=result.agent_profile;renderSettings();notice(english?'Research persona saved and will apply to new turns.':'研究人格已保存；新对话轮次会记录并使用这一版本。');}catch(error){notice(error.message,true);}},true));
  soul.append(soulForm,Object.assign(document.createElement('small'),{textContent:english?'Immutable research rules: source qualification, page anchors, evidence freezes, write approvals, version retention, and privacy boundaries are enforced by the application and cannot be overridden by the persona.':`不可由人格覆盖的研究规则：${profile.harness_constitution||''}`}));appendSetting('persona',soul);

  const presets=state.modelSettings?.provider_presets||[];
  const roles=state.modelSettings?.roles||[];
  const renderRole=(item)=>{
    const routeState=item.direct_route?(english?'Used by its named Wenjin workflow.':'由对应问津功能直接调用。'):(english?'Reserved in 0.1.2: not routed automatically; available only when selected as a MoA adviser.':'0.1.2预留：不会自动路由，只能在选为MoA参考模型时参与建议。');
    const panel=card(english?(item.label_en||item.label):item.label, `${routeState}\n${item.provider==='disabled'?(english?'Disabled':'尚未启用'):item.provider==='auto'?(english?'Automatic: follows the main model':'自动：跟随主模型'):`${item.provider} / ${item.model}`} · ${english?'credential: ':'密钥：'}${item.has_secret?(english?'saved in Windows Credential Manager':'已保存到 Windows 凭据管理器'):(english?'not stored':'未保存')}`);
    const form=document.createElement('section');form.className='context-form model-role-form';
    const provider=document.createElement('select');
    if(item.kind==='auxiliary')provider.append(new Option(english?'Automatic (main model)':'自动（跟随主模型）','auto'));
    provider.append(new Option(english?'Disabled':'未启用','disabled'),new Option('Ollama','ollama'),new Option(english?'OpenAI-compatible API':'OpenAI 兼容接口','openai_compatible'));provider.value=item.provider;
    const providerLabel=document.createElement('label');providerLabel.textContent=english?'Interface type':'接口类型';providerLabel.append(provider);
    const preset=document.createElement('select');preset.append(new Option(english?'Choose provider preset':'选择服务商预设',''));
    for(const value of presets){const label=english&&value.id==='custom'?'Custom compatible endpoint':english&&value.id==='zhipu'?'Zhipu GLM':value.label;preset.append(new Option(label,value.id));}preset.value=item.preset_id||'';
    const presetLabel=document.createElement('label');presetLabel.textContent=english?'Provider preset':'服务商预设';presetLabel.append(preset);
    const model=document.createElement('input');model.value=item.model;model.placeholder=english?'Choose a discovered model or type an ID':'选择已发现模型，或手工输入模型ID';
    const modelList=document.createElement('datalist');modelList.id=`model-list-${item.role}`;model.setAttribute('list',modelList.id);
    const modelStatus=document.createElement('small');modelStatus.textContent=english?'Model list not loaded.':'尚未读取模型列表。';
    let discoveredModels=[];
    const modelLabel=document.createElement('label');modelLabel.textContent=english?'Model':'模型';modelLabel.append(model,modelList,modelStatus);
    const baseUrl=document.createElement('input');baseUrl.value=item.base_url;baseUrl.placeholder=english?'For example, http://127.0.0.1:11434':'例如 http://127.0.0.1:11434';
    const urlLabel=document.createElement('label');urlLabel.textContent='Base URL';urlLabel.append(baseUrl);
    const apiKey=document.createElement('input');apiKey.type='password';apiKey.autocomplete='new-password';apiKey.placeholder=item.has_secret?(english?'Saved securely; leave blank to keep it':'已安全保存；留空表示不更换'):(english?'Required for remote APIs; leave blank for Ollama':'远程接口需要，Ollama 留空');
    const keyLabel=document.createElement('label');keyLabel.textContent='API Key';keyLabel.append(apiKey);
    const timeout=document.createElement('input');timeout.type='number';timeout.min='5';timeout.max='600';timeout.value=item.timeout_seconds;
    const timeoutLabel=document.createElement('label');timeoutLabel.textContent=english?'Timeout (seconds)':'超时（秒）';timeoutLabel.append(timeout);
    const contextWindow=document.createElement('input');contextWindow.type='number';contextWindow.min='0';contextWindow.value=item.context_window||0;
    const contextLabel=document.createElement('label');contextLabel.textContent=english?'Context window (tokens, 0 = auto)':'上下文窗口（token，0 为自动）';contextLabel.append(contextWindow);
    const clear=document.createElement('input');clear.type='checkbox';clear.style.minHeight='auto';
    const clearLabel=document.createElement('label');clearLabel.append(clear,document.createTextNode(english?' Clear saved credential':' 清除已经保存的密钥'));
    const refreshModels=async(showError=true)=>{
      if(!['ollama','openai_compatible'].includes(provider.value)||!baseUrl.value.trim()){discoveredModels=[];modelList.replaceChildren();modelStatus.textContent=english?'Set a provider and Base URL first.':'请先选择服务商并填写Base URL。';return;}
      try{
        modelStatus.textContent=english?'Loading models…':'正在读取模型列表…';
        const result=await request('/api/model-settings/models',localSessionOptions({role:item.role,provider:provider.value,base_url:baseUrl.value,api_key:apiKey.value}));
        discoveredModels=result.models||[];modelList.replaceChildren();for(const name of discoveredModels)modelList.append(new Option(name,name));
        modelStatus.textContent=english?`${result.count} model(s) available; manual entry remains available.`:`发现 ${result.count} 个模型；接口不支持枚举时仍可手工输入。`;
        if(!model.value&&discoveredModels.length===1)model.value=discoveredModels[0];
      }catch(error){discoveredModels=[];modelList.replaceChildren();modelStatus.textContent=error.message;if(showError)notice(error.message,true);}
    };
    preset.onchange=()=>{const found=presets.find((value)=>value.id===preset.value);if(found){provider.value=found.provider;baseUrl.value=found.base_url;refreshModels(false);}};
    provider.onchange=()=>refreshModels(false);baseUrl.onchange=()=>refreshModels(false);apiKey.onchange=()=>refreshModels(false);
    const row=document.createElement('div');row.className='row';
    row.append(actionButton(english?'Save and apply':'保存并应用',async()=>{
      try{
        if(discoveredModels.length&&!discoveredModels.includes(model.value.trim()))throw new Error(english?'Choose a model returned by the provider, or refresh after changing the endpoint.':'请选择服务商返回的模型；如已更换接口，请先刷新模型列表。');
        const result=await request('/api/model-settings/save',localSessionOptions({role:item.role,provider:provider.value,model:model.value,base_url:baseUrl.value,api_key:apiKey.value,clear_secret:clear.checked,timeout_seconds:Number(timeout.value),context_window:Number(contextWindow.value),preset_id:preset.value||'custom'}));
        state.modelSettings=result.settings;await loadSnapshot();notice(english?`${item.label_en||item.label} saved. New runs will record the selected model.`:`${item.label}已经保存；之后的新任务会记录实际模型快照。`);
      }catch(error){notice(error.message,true);}
    },true),actionButton(english?'Refresh models':'刷新模型列表',()=>refreshModels(true)),actionButton(english?'Test connection':'测试连接',async()=>{
      try{const result=await request('/api/model-settings/probe',localSessionOptions({role:item.role}));notice(result.detail,!result.available);}catch(error){notice(error.message,true);}
    }));
    form.append(presetLabel,providerLabel,modelLabel,urlLabel,keyLabel,timeoutLabel,contextLabel,clearLabel,row);panel.append(form);
    if(['ollama','openai_compatible'].includes(provider.value)&&baseUrl.value)queueMicrotask(()=>refreshModels(false));
    return panel;
  };
  const main=roles.find((item)=>item.role==='main_reasoning');if(main)appendSetting('models',renderRole(main));
  const aux=card(english?'Default auxiliary model routing':'全局默认辅助模型',english?'These defaults serve Wenjin core and any Domain Agent that chooses Inherit. Each Domain Agent may override its own model roles in the Domain Agent sidebar. MoA is optional and does not replace direct routes.':'这些设置供问津核心及选择“继承”的领域 Agent 使用。每个领域 Agent 都可以在自己的右侧栏单独覆盖模型岗位；MoA只是可选的交叉建议，不替代直接路由。');
  for(const item of roles.filter((value)=>value.role!=='main_reasoning')){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`${english?(item.label_en||item.label):item.label} · ${item.provider==='auto'?(english?'Auto':'自动'):item.model||item.provider}`;details.append(summary,renderRole(item));aux.append(details);}appendSetting('routing',aux);

  const moaState=state.modelSettings?.moa||{};const moa=card('MoA · Mixture of Agents',english?'Reference models advise independently; only the main model may act or call tools. A failed adviser does not abort the run.':'参考模型独立给出建议，只有主模型能够行动和调用工具；单个参考模型失败不会中断任务。');
  const moaEnabled=document.createElement('input');moaEnabled.type='checkbox';moaEnabled.checked=Boolean(moaState.enabled);const moaEnabledLabel=document.createElement('label');moaEnabledLabel.className='check-label';moaEnabledLabel.append(moaEnabled,document.createTextNode(english?'Enable MoA':'启用 MoA'));
  const refs=document.createElement('section');refs.className='checkbox-grid';for(const role of roles.filter((value)=>value.kind==='auxiliary')){const box=document.createElement('input');box.type='checkbox';box.value=role.role;box.checked=(moaState.reference_roles||[]).includes(role.role);const label=document.createElement('label');label.className='check-label';label.append(box,document.createTextNode(english?(role.label_en||role.label):role.label));refs.append(label);}
  const fanout=document.createElement('select');fanout.append(new Option(english?'Once per user turn':'每轮用户消息一次','user_turn'));fanout.value='user_turn';
  moa.append(moaEnabledLabel,refs,fanout,actionButton(english?'Save MoA preset':'保存 MoA 方案',async()=>{try{const reference_roles=[...refs.querySelectorAll('input:checked')].map((node)=>node.value);const result=await request('/api/model-settings/moa',localSessionOptions({enabled:moaEnabled.checked,reference_roles,fanout:fanout.value}));state.modelSettings=result.settings;renderSettings();notice(english?'MoA preset saved.':'MoA 方案已保存。');}catch(error){notice(error.message,true);}},true));appendSetting('routing',moa);

  const models = card(english?'Current configuration':'当前生效配置', english?'Every run records the models and persona that were actually used.':'每次运行都会记录实际使用的模型与研究人格版本。');
  for (const profile of state.snapshot.model_profiles || []) models.append(Object.assign(document.createElement('p'), {textContent:`${profile.assigned ? (english?'Current main model':'当前主模型') : profile.status} · ${profile.provider} / ${profile.model} · ${profile.endpoint||(english?'local rules':'本机规则')}`}));
  models.append(Object.assign(document.createElement('p'), {textContent:`${english?'Vision assistant':'视觉辅助'}：${caps.vision_ocr?.available ? `${caps.vision_ocr.provider} / ${caps.vision_ocr.model}` : (english?'not configured':'未配置')}\n${english?'Translation assistant':'翻译辅助'}：${caps.translation?.available ? `${caps.translation.provider} / ${caps.translation.model}` : (english?'not configured':'未配置')}`})); appendSetting('runtime',models);
  const memory=card(english?'Memory layers':'记忆分层',english?'Conversation state, project knowledge, reusable historical knowledge, and engineering memory remain separate.':'对话状态、项目知识、可复用史学知识与工程记忆分开保存，不把所有信息塞进同一上下文。');
  memory.append(Object.assign(document.createElement('p'),{textContent:english?'1. Thread memory: current discussion and run receipts\n2. Project knowledge: sources, claims, evidence, manuscripts\n3. Historical memory: only reviewed reusable findings\n4. Engineering memory: tools, failures, and runbooks':'1. 对话记忆：当前讨论与运行回执\n2. 项目知识：来源、主张、证据与稿件\n3. 史学长期记忆：仅提升经复核、可复用的研究判断\n4. 工程记忆：工具、故障与运行方法'}));appendSetting('memory',memory);
  const memoryAdapter=state.snapshot.memory_adapter||{targets:{}};
  const adapterCard=card(english?'Local long-term memory adapters':'本地长期记忆适配器',english?'Approved candidates can be sent to the target 90_INBOX. Full chats, OCR drafts, and source files are outside this sync.':'经批准的候选可以送入目标库 90_INBOX；聊天全文、OCR草稿和来源文件不在同步范围内。');
  const historicalPath=document.createElement('input');historicalPath.placeholder=english?'Historical research memory path':'史学长期记忆库路径';historicalPath.value=memoryAdapter.targets?.historical?.path||'';
  const engineeringPath=document.createElement('input');engineeringPath.placeholder=english?'Engineering memory path':'工程长期记忆库路径';engineeringPath.value=memoryAdapter.targets?.engineering?.path||'';
  adapterCard.append(historicalPath,engineeringPath,actionButton(english?'Save memory paths':'保存记忆库路径',async()=>{try{state.snapshot.memory_adapter=await request('/api/memory/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({historical:historicalPath.value,engineering:engineeringPath.value})});renderSettings();notice(english?'Local memory adapters saved. No candidate was written automatically.':'本地记忆适配器已保存；没有自动写入任何候选。');}catch(error){notice(error.message,true);}},true));appendSetting('memory',adapterCard);
  appendSetting('memory',card(english?'Enforced research contracts':'程序级硬契约',english?'Page anchors, source qualification, evidence status, freeze packages, version fingerprints, and validators are enforced by the application rather than model memory.':'原页锚点、来源资格、证据状态、冻结包、版本指纹和校验器由程序强制执行，不依赖模型是否记得某条 Skill。'));
  const connectors = card(english?'Research connectors':'研究连接器', english?'Public databases support bounded search. Authenticated databases may only be used within the researcher\'s lawful access.':'公开数据库可有界检索；已登录数据库只能在用户合法权限内操作。');
  for (const capability of caps.research_connectors || []) connectors.append(Object.assign(document.createElement('p'), {textContent:`${capability.provider} · ${capability.available ? (english?'available':'可用') : (english?'not configured':'未配置')} · ${capability.mode}${capability.missing?.length ? ` · ${english?'missing':'缺少'} ${capability.missing.join(english?', ':'、')}` : ''}`})); appendSetting('connectors',connectors);
  const computer=caps.computer_use||{};
  const computerRuntime=computer.runtime_origin==='bundled'?(english?'bundled runtime':'安装包内置'):computer.runtime_origin==='system'?(english?'system runtime':'系统组件'):computer.runtime_origin;
  const browserRuntime=computer.browser_origin==='system_edge'?'Microsoft Edge':computer.browser_origin==='system_chrome'?'Google Chrome':computer.browser_origin==='user_chrome'?'Google Chrome':computer.browser_origin;
  const desktopComputer=computer.desktop_pack?.ready
    ? (english?`Computer Use ${computer.desktop_pack.version}: Windows accessibility, keyboard, mouse, program launch, and command tools are connected through the permission broker.`:`Computer Use ${computer.desktop_pack.version}：Windows控件树、键盘、鼠标、程序启动和命令工具已接入权限代理。`)
    : (english?'The full-desktop Computer Use pack is not ready.':'整机 Computer Use 领域包尚未就绪。');
  appendSetting('connectors',card(english?'Browser and computer use':'浏览器与 Computer Use',`${desktopComputer}\n${computer.visible_browser_launch
    ? (english?`${computer.version||'agent-browser'} · ${computerRuntime} · ${browserRuntime}. The Agent can read and navigate within the approved domain of a visible session. Clicking controls, sign-in, CAPTCHA, payment, download, and submission stay with the user.`:`${computer.version||'agent-browser'} · ${computerRuntime} · ${browserRuntime}。Agent 可读取可见会话并在已批准域名内导航；点击控件、登录、验证码、付费、下载和提交仍由用户操作。`)
    : computer.installed
      ? (english?'The bundled automation runtime is ready, but Microsoft Edge or Google Chrome was not found.':'自动化运行时已内置，但没有找到 Microsoft Edge 或 Google Chrome。')
      : (english?'The browser automation runtime is unavailable.':'浏览器自动化运行时不可用。')}`));
  const codex=caps.codex||{};
  const codexPanel=card(english?'Two-way Codex bridge':'Codex 双向桥接',codex.installed
    ? (english?'Codex can read the current project through Wenjin MCP. Wenjin can also start a constrained Codex task after an explicit click. It reuses the local Codex login and never reads or stores credentials.':'Codex 可以通过问津 MCP 读取当前项目；问津也可以在你明确点击后启动一个受限 Codex 任务。任务沿用本机 Codex 登录，不读取或保存凭据。')
    : (english?'Codex CLI was not found. Install or repair Codex to enable the two-way bridge.':'未找到 Codex CLI。安装或修复 Codex 后才能启用双向桥接。'));
  if(codex.installed){
    const registrationName=document.createElement('input');registrationName.placeholder=english?'MCP name (leave blank to generate)':'MCP 名称（留空自动生成）';
    codexPanel.append(registrationName,actionButton(english?'Register current project with Codex':'把当前项目注册给 Codex',async()=>{try{const result=await request('/api/codex/register-mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:registrationName.value.trim()})});notice(result.status==='already_registered'?(english?`Codex already has ${result.name}`:`Codex 已登记 ${result.name}`):(english?`Registered with Codex: ${result.name}`:`已登记到 Codex：${result.name}`));}catch(error){notice(error.message,true);}},true));
    const prompt=document.createElement('textarea');prompt.placeholder=english?'A concrete task for Codex; the project directory is read-only by default':'交给 Codex 的明确任务；默认只读当前项目目录';prompt.rows=5;
    const sandbox=document.createElement('select');sandbox.append(new Option(english?'Read-only project':'只读项目','read-only'),new Option(english?'Allow project-workspace writes':'允许写入项目工作区','workspace-write'));
    const taskStatus=document.createElement('pre');taskStatus.textContent=english?'No Codex task has started.':'尚未启动 Codex 任务。';
    const poll=async(taskId)=>{try{const value=await request(`/api/codex/task?id=${encodeURIComponent(taskId)}`);taskStatus.textContent=`${value.task_id} · ${value.status}\n${value.final_message||value.error||''}`;if(['queued','running'].includes(value.status))setTimeout(()=>poll(taskId),1000);}catch(error){taskStatus.textContent=error.message;}};
    codexPanel.append(prompt,sandbox,actionButton(english?'Start Codex task':'启动 Codex 任务',async()=>{try{const value=await request('/api/codex/task/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:prompt.value,sandbox:sandbox.value})});taskStatus.textContent=`${value.task_id} · queued`;poll(value.task_id);}catch(error){notice(error.message,true);}},true),taskStatus);
  }
  appendSetting('connectors',codexPanel);
  appendSetting('connectors',card(english?'MCP and CLI':'MCP 与 CLI', `${english?'This project can be exposed as a local read-only MCP server and administered from the command line.':'当前项目可以作为本地只读 MCP 服务供其他 Agent 调用，也能通过命令行管理。'}\nwenjin mcp-server "${project.project_root||'<project>'}"\nwenjin --help\n${english?'MCP tools return qualified sources, library results, manuscript structure, and project status; they do not bypass write approvals.':'MCP 工具返回来源资格、图书馆结果、稿件结构和项目状态，不绕过写入审批。'}`));
  const weixin=card(english?'Weixin connection · Experimental':'微信连接 · 实验功能',english?'Scan with ordinary Weixin to try a private research conversation with this Wenjin installation. Version 0.1.2 replies only to inbound private text. Group chat, scheduled messages, files, payments, and CAPTCHA handling are not available.':'使用普通微信扫码后，可以试用从微信继续本机问津私聊研究对话。0.1.2只回复收到的私聊文字，暂不支持群聊、定时消息、文件、支付或验证码处理。');
  const weixinState=document.createElement('pre');weixinState.textContent=english?'Reading gateway status…':'正在读取网关状态……';
  const qrBox=document.createElement('div');qrBox.className='weixin-qr';
  const allowInput=document.createElement('input');allowInput.placeholder=english?'Allowed Weixin user IDs, comma-separated':'允许使用的微信用户ID，逗号分隔';
  const access=document.createElement('select');access.append(new Option(english?'Ask before every action':'请求批准','ask'),new Option(english?'Auto-approve routine research':'帮我批准','research_assist'),new Option(english?'Full computer access':'完全访问','full_computer'));
  let loginSession='';
  const showWeixinStatus=(value)=>{weixinState.textContent=value.configured?`${english?'Connected account':'已连接账号'}: ${value.account_id||'-'}\n${english?'Gateway':'网关'}: ${value.running?(english?'running':'运行中'):(english?'stopped':'已停止')}\n${english?'Mode':'权限'}: ${value.access_mode}${value.last_error?`\n${english?'Last error':'最近错误'}: ${value.last_error}`:''}`:(english?'No Weixin account is connected.':'尚未连接微信账号。');allowInput.value=(value.allowed_user_ids||[]).join(', ');access.value=value.access_mode||'ask';};
  const pollLogin=async()=>{if(!loginSession)return;try{const result=await request('/api/weixin/login/poll',localSessionOptions({session_id:loginSession}));weixinState.textContent=result.message||result.status;if(result.connected){qrBox.replaceChildren();showWeixinStatus(await request('/api/weixin/status'));notice(english?'Weixin is connected directly to Wenjin.':'微信已直接连接问津。');return;}if(result.requires_verify_code){const code=window.prompt(english?'Enter the verification code shown by Weixin':'请输入微信显示的验证码');if(code)await request('/api/weixin/login/poll',localSessionOptions({session_id:loginSession,verify_code:code}));}setTimeout(pollLogin,1600);}catch(error){weixinState.textContent=error.message;}};
  const actions=document.createElement('div');actions.className='button-row';
  actions.append(actionButton(english?'Generate QR code':'生成微信二维码',async()=>{try{const result=await request('/api/weixin/login/start',localSessionOptions({}));loginSession=result.session_id;const img=document.createElement('img');img.alt=english?'Weixin login QR code':'微信登录二维码';img.src=result.qrcode_data_url;const fallback=document.createElement('a');fallback.href=result.qrcode_url;fallback.target='_blank';fallback.rel='noreferrer';fallback.textContent=english?'Open login link':'打开登录链接';qrBox.replaceChildren(img,fallback);pollLogin();}catch(error){notice(error.message,true);}},true));
  actions.append(actionButton(english?'Save gateway policy':'保存网关权限',async()=>{try{const value=await request('/api/weixin/config',localSessionOptions({allowed_user_ids:allowInput.value.split(/[,，\s]+/).filter(Boolean),access_mode:access.value,enabled:true}));showWeixinStatus(value);notice(english?'Weixin gateway policy saved.':'微信网关权限已保存。');}catch(error){notice(error.message,true);}},true));
  actions.append(actionButton(english?'Disconnect':'断开微信',async()=>{if(!window.confirm(english?'Disconnect Weixin and delete the local bot token?':'断开微信并删除本机保存的机器人令牌？'))return;try{showWeixinStatus(await request('/api/weixin/disconnect',localSessionOptions({})));qrBox.replaceChildren();}catch(error){notice(error.message,true);}}));
  weixin.append(weixinState,qrBox,allowInput,access,actions);appendSetting('connectors',weixin);request('/api/weixin/status').then(showWeixinStatus).catch((error)=>{weixinState.textContent=error.message;});
  const pluginState=state.snapshot.plugins||{plugins:[]};
  const pluginInstall=card(english?'Install a Wenjin or Codex plugin':'安装问津或Codex插件',english?'Wenjin domain packs retain their declared permissions. Imported Codex Skills are registered directly; Codex MCP tools default to sensitive until reviewed. Proprietary bundled runtimes and account sessions are not copied.':'问津领域包保留清单权限；Codex Skill可直接登记，Codex MCP工具导入后默认均为敏感，需人工复核。专有 bundled runtime 和账号会话不会复制。');
  const pluginPath=document.createElement('input');pluginPath.placeholder=english?'Wenjin/Codex plugin folder or .zip package':'问津/Codex插件目录或 .zip 安装包';
  const runtimeCommand=document.createElement('input');runtimeCommand.placeholder=english?'Optional: self-contained MCP runtime path':'可选：自运行MCP程序路径';
  const pluginChooser=document.createElement('div');pluginChooser.className='button-row';
  if(nativeAvailable())pluginChooser.append(actionButton(english?'Choose ZIP':'选择ZIP',async()=>{const path=await nativeInvoke('choose_file',{kind:'plugin'});if(path)pluginPath.value=path;},true),actionButton(english?'Choose folder':'选择已解压目录',async()=>{const path=await nativeInvoke('choose_folder');if(path)pluginPath.value=path;}));
  const advancedRuntime=document.createElement('details');const advancedSummary=document.createElement('summary');advancedSummary.textContent=english?'Advanced runtime override':'高级：覆盖运行程序';
  const advancedHelp=document.createElement('p');advancedHelp.textContent=english?'Normally leave this empty. Use it only when the domain pack does not include its own MCP executable, or when testing a locally rebuilt runtime. The selected executable replaces the command declared by the pack; its actions are still governed by Ask, Auto-approve, or Full access.':'通常应保持为空。只有领域包没有自带MCP程序，或需要测试自己重新编译的运行程序时才填写。这里选择的程序会覆盖领域包清单中的默认命令；它能执行哪些动作，仍由“请求批准、帮我批准、完全访问”三档权限控制。';
  advancedRuntime.append(advancedSummary,advancedHelp,runtimeCommand);
  pluginInstall.append(pluginPath,pluginChooser,advancedRuntime,actionButton(english?'Install plugin':'安装插件',async()=>{try{const result=await request('/api/plugins/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_root:pluginPath.value,runtime_command:runtimeCommand.value})});state.snapshot.plugins=result.plugins||result;await loadSnapshot();renderSettings();notice(english?'The plugin was copied and validated. Codex MCP tools remain sensitive until reviewed.':'插件已复制并校验；Codex MCP工具在人工复核前保持敏感权限。');}catch(error){notice(error.message,true);}},true));appendSetting('plugins',pluginInstall);
  appendSetting('plugins',card(english?'What works in 0.1.2':'0.1.2实际启用什么',english?'A usable pack defines a research scope and stopping rules, supplies a Skill for the main Agent, exposes bounded MCP tools with permission classes, and may bind bundled or user-selected local data. The main Agent remains the only actor. Additional schema, processor, graph-adapter, and panel declarations are visible for development but do not yet change Wenjin screens by themselves.':'可用领域包应说明研究范围和停止条件，向主Agent提供Skill，以明确权限开放有界MCP工具，并可连接随包或用户选择的本地数据。主Agent仍是唯一行动者。额外的字段规范、处理器、图谱适配器和面板声明可供开发查看，但目前不会自行改变问津界面。'));
  const orchestration=card(english?'Domain-pack orchestration tutorial':'领域包编排教程',english?'A domain pack should begin with a real research workflow, not an empty template. The main Agent can create a scaffold only after the researcher states the following five parts.':'领域包应从一套真实研究流程出发，而不是先生成一个空壳。只有研究者说明以下五部分后，主Agent才适合创建工程。');
  const orchestrationSteps=document.createElement('ol');
  const stepTexts=english?[
    'Question and stopping rule: what scholarly operation is being extended, and when must the Agent stop?',
    'Materials and provenance: accepted file types, page identity, source hierarchy, licences, and data that must stay local.',
    'Operations and permissions: read-only tools first; mark every state-changing tool as routine, sensitive, or forbidden.',
    'Wenjin placement: decide whether each contribution belongs in the library, research context, graph, writing studio, or a genuinely necessary narrow panel.',
    'Runtime and verification: ship a self-contained MCP runtime or declare an explicit runtime, then test installation, local-data binding, permission receipts, and removal.'
  ]:[
    '问题与停止条件：领域包扩展哪一种学术操作，Agent在什么情况下必须停止？',
    '材料与来源：接受哪些文件、怎样保留原页身份、材料层级与许可证如何处理、哪些数据不得离开本机？',
    '动作与权限：先设计只读工具，再把所有写入动作标为常规、敏感或禁止。',
    '进入问津的位置：逐项决定它属于图书馆、研究上下文、知识图谱、文章工作台，还是确实需要一个窄面板。',
    '运行与验收：提供自运行MCP程序或明确运行时，随后测试安装、本地数据连接、权限回执和卸载。'
  ];
  for(const text of stepTexts)orchestrationSteps.append(Object.assign(document.createElement('li'),{textContent:text}));
  const agentGuide=document.createElement('p');agentGuide.textContent=english?'To have the main Agent create the engineering scaffold, state these five parts in Research chat and explicitly ask it to create a domain pack. File creation remains permission-gated.':'需要主Agent建立工程时，请在研究对话中写清上述五部分，并明确要求“创建领域包”；创建文件仍受当前权限档控制。';
  const sdkLink=document.createElement('a');sdkLink.href='https://github.com/huanghaitck/wenjin/blob/main/docs/WENJIN_PLUGIN_SDK.md';sdkLink.target='_blank';sdkLink.rel='noreferrer';sdkLink.textContent=english?'Open the complete Domain Pack SDK':'查看完整领域包SDK与清单示例';
  orchestration.append(orchestrationSteps,agentGuide,sdkLink);appendSetting('plugins',orchestration);
  appendSetting('plugins',card(english?'Runtime and Python':'运行时与 Python',english?'Ordinary users do not install Python for Wenjin core. Core PDF, data and SQLite operations run inside the frozen sidecar. A domain agent that needs Python, spreadsheet libraries or specialist database drivers must ship a self-contained MCP executable. Wenjin does not expose an unrestricted Python console to the Agent.':'普通用户不需要为问津核心另装Python。PDF、数据和SQLite操作运行在安装包内的冻结侧车中。领域 Agent 若需要Python、表格库或专用数据库驱动，应自带可运行的MCP程序；问津不会向Agent开放不受限制的Python控制台。'));
  for(const plugin of pluginState.plugins||[]){
    const pluginDescription=english?(plugin.description_en||plugin.description||''):(plugin.description_zh||plugin.description||'');
    const node=card(`${plugin.display_name||plugin.name} · ${plugin.version||''}`,`${pluginDescription}\n${english?'Status: ':'状态：'}${plugin.status}${plugin.package_changed?(english?' · source package changed; reinstall required':' · 源包已变化，需重新安装'):''}\n${english?'Runtime: ':'运行：'}${plugin.runtime_available?(english?'MCP command available':'MCP命令可用'):(english?'MCP command not found':'MCP命令未找到')}`);
    const contributionLabels={methods:english?'Methods':'研究方法',schemas:english?'Schemas':'字段规范',processors:english?'Processors':'资料处理器',graph_adapters:english?'Graph adapters':'知识图谱适配器',ui_panels:english?'Panels':'功能面板'};
    const contributions=Object.entries(plugin.contributions||{}).filter(([,items])=>Array.isArray(items)&&items.length);
    if(contributions.length)node.append(Object.assign(document.createElement('p'),{textContent:contributions.map(([key,items])=>`${contributionLabels[key]||key}: ${items.join(', ')}`).join('\n')}));
    for(const source of plugin.local_data_sources||[]){
      const details=document.createElement('details');details.open=!source.bound;
      const summary=document.createElement('summary');summary.textContent=`${english?'Local data':'本地数据'}：${english?(source.label_en||source.label||source.id):(source.label||source.id)} · ${source.bound?(english?'connected':'已连接'):(english?'not connected':'未连接')}`;details.append(summary);
      if(source.description||source.description_en)details.append(Object.assign(document.createElement('p'),{textContent:english?(source.description_en||source.description):(source.description||source.description_en)}));
      const pathInput=document.createElement('input');pathInput.value=source.binding?.path||'';pathInput.placeholder=source.kind==='directory'?(english?'Local data directory':'本地数据目录'):(english?'Local database or data file':'本地数据库或数据文件');
      const row=document.createElement('div');row.className='button-row';
      if(nativeAvailable())row.append(actionButton(english?'Choose locally':'选择本地数据',async()=>{const selected=source.kind==='directory'?await nativeInvoke('choose_folder'):await nativeInvoke('choose_file',{kind:'data'});if(selected)pathInput.value=selected;},true));
      row.append(actionButton(english?'Connect':'连接',async()=>{try{state.snapshot.plugins=await request('/api/plugins/bind-data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:plugin.name,source_id:source.id,local_path:pathInput.value})});renderSettings();notice(english?'The selected local data was connected to this domain pack.':'已把所选本地数据连接到该领域包。');}catch(error){notice(error.message,true);}},true));
      details.append(pathInput,row);node.append(details);
    }
    for(const pack of plugin.data_packs||[]){
      const details=document.createElement('details');
      const bundled=String(pack.distribution||'').startsWith('bundled');
      const summary=document.createElement('summary');summary.textContent=`${english?'Data pack':'数据包'}：${pack.label||pack.id} · ${bundled?(english?'bundled and ready':'已随领域包内置'):(pack.distribution||'')}`;
      details.append(summary,Object.assign(document.createElement('p'),{textContent:pack.license_summary||''}));
      if(bundled&&pack.included_path)details.append(Object.assign(document.createElement('p'),{textContent:`${english?'Bundled path':'内置路径'}：${pack.included_path}`}));
      if(!bundled)for(const download of pack.downloads||[]){const link=document.createElement('a');link.href=download.url;link.target='_blank';link.rel='noreferrer';link.textContent=`${download.role} · ${english?'Source download':'来源下载'}`;details.append(link,document.createElement('br'));}
      node.append(details);
    }
    if(plugin.kind!=='system')node.append(actionButton(english?'Remove domain pack':'移除领域包',async()=>{if(!window.confirm(`${english?'Remove':'移除'} ${plugin.display_name||plugin.name}？`))return;try{state.snapshot.plugins=await request('/api/plugins/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:plugin.name})});renderSettings();notice(english?'The installed copy was removed; its source project and local data were not changed.':'领域包副本已移除；原工程和本地数据库未被修改。');}catch(error){notice(error.message,true);}}));appendSetting('plugins',node);
  }
  if(!(pluginState.plugins||[]).length)appendSetting('plugins',card(english?'No domain pack installed':'尚未安装领域包',english?'In 0.1.2 a domain pack can add a research Skill, permission-bounded MCP tools, and local-data bindings without changing Wenjin core.':'0.1.2中的领域包可以增加研究Skill、受权限约束的MCP工具和本地数据连接，而不改变问津核心。'));
  appendSetting('runtime',card(english?'Privacy and confirmations':'隐私与确认', english?'Cookies, passwords, API keys, and unredacted network logs are not stored. Remote models receive only selected page blocks, sections, and text ranges. Evidence freezes, manuscript changes, and memory promotion are confirmed in their respective workspaces.':'不保存 Cookie、密码、API Key 或未脱敏网络日志。远程模型只接收选定的页块、章节和文字范围；证据冻结、正文修改与记忆提升分别在对应工作区确认。'));
  const backupItems=state.snapshot.backups||[];
  const backups=card(english?'Project backup and recovery':'项目备份与恢复',backupItems.length?(english?`${backupItems.length} complete SQLite backup(s) found. Recovery creates a new project and never overwrites the current project.`:`当前发现 ${backupItems.length} 份完整SQLite备份。恢复会建立新项目，不覆盖当前项目。`):(english?'No project backup exists yet. The desktop app will create a backup at startup when a complete project has changed.':'当前还没有项目备份；桌面版以后会在启动时为有变化的完整项目建立备份。'));
  const backupSelect=document.createElement('select');backupSelect.append(new Option(english?'Choose a backup to restore':'选择要恢复的备份',''));for(const item of backupItems)backupSelect.append(new Option(`${item.title} · ${new Date(item.created_at).toLocaleString()}`,item.backup_id));
  backups.append(actionButton(english?'Back up current project now':'立即备份当前项目',async()=>{try{await request('/api/backups/create',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await loadSnapshot();renderSettings();notice(english?'The current project passed an online SQLite backup and integrity check.':'当前项目已完成SQLite在线备份与完整性检查。');}catch(error){notice(error.message,true);}},true),backupSelect,actionButton(english?'Restore as a new project copy':'恢复为新的项目副本',async()=>{if(!backupSelect.value){notice(english?'Choose a backup first.':'请先选择备份。',true);return;}if(!window.confirm(english?'Create a new project copy from this backup? The current project will not be overwritten.':'将从备份建立一个新的项目副本，当前项目不会覆盖。继续吗？'))return;try{const result=await request('/api/backups/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backup_id:backupSelect.value})});await loadSnapshot();notice(english?`Restored as a new project: ${result.project.title}`:`已恢复为新项目：${result.project.title}`);}catch(error){notice(error.message,true);}}));appendSetting('runtime',backups);
}

function renderSkillCatalog() {
  const container=$('skillCatalog');if(!container||!state.snapshot)return;container.replaceChildren();
  const english=state.language==='en';
  const query=($('skillQuery')?.value||'').trim().toLowerCase();
  const labels=english?{user_action:'Research skills',harness_policy:'Internal research workflows',integration:'External integrations'}:{user_action:'研究技能',harness_policy:'内部研究流程',integration:'外部工具连接'};
  const skills=(state.snapshot.library?.skills||[]).filter((item)=>!query||`${item.name} ${item.description} ${item.agent_program?.display_name||''}`.toLowerCase().includes(query));
  for(const placement of ['user_action','harness_policy','integration']){
    const group=skills.filter((item)=>item.placement===placement);if(!group.length)continue;
    const section=document.createElement('section');section.className='skill-group';
    const heading=document.createElement('h2');heading.textContent=`${labels[placement]} · ${group.length}`;section.append(heading);
    for(const skill of group){
      const program=skill.agent_program||{};
      const displayName=english?(program.display_name_en||skill.name.replaceAll('-',' ')):(program.display_name||skill.name);
      const description=english?(program.short_description_en||skill.description_en||`Versioned ${skill.name} capability`):(program.short_description||skill.description);
      const placementCopy=placement==='user_action'?(english?'The run pins the Skill and Agent-program versions; writes remain permission-gated.':'运行时会固定技能与 Agent 程序版本；所有写入仍经过工作台门禁。'):placement==='harness_policy'?(english?'Triggered by research stage and permissions; no direct button.':'由研究阶段和权限自动触发，不提供直接按钮。'):(english?'Invoked from its owning workspace, not mixed into research actions.':'由对应页面调用，不混入研究动作。');
      const node=card(displayName,`${skill.invocation} · ${skill.sha256.slice(0,12)}…\n${description}\n${placementCopy}`);
      if(program.sha256) node.append(Object.assign(document.createElement('small'),{textContent:english?`Agent program ${program.sha256.slice(0,12)}… · ${program.allow_implicit_invocation?'may be suggested by the workflow':'explicit invocation only'}`:`Agent 程序 ${program.sha256.slice(0,12)}… · ${program.allow_implicit_invocation?'可由研究流程建议':'仅由研究者明确调用'}`}));
      if(placement==='user_action') node.append(actionButton(english?`Use ${skill.invocation} in chat`:`在对话中调用 ${skill.invocation}`,()=>{setMode('agent');$('messageInput').value=`${skill.invocation} `;$('messageInput').focus();renderSlashMenu();},true));
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
  const english=state.language==='en';
  $('sourceTitle').textContent = source?.title || (english?'No source imported':'尚未导入文献');
  $('sourceState').textContent = source ? `${source.processing_state} · ${source.use_state}` : (english?'Waiting for source':'等待材料');
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
    : '题名页与书目信息待核。';
  const locator = page?.page_type === 'docx_locator';
  $('pageRailTitle').textContent = locator ? (english?'Translation segments':'译稿片段') : (english?'Physical pages':'物理页');
  $('pageLabel').textContent = page ? (locator ? `${english?'Logical segment':'逻辑片段'} ${page.physical_page} · locator_only` : `${english?'Physical page':'物理页'} ${page.physical_page}${page.printed_page ? ` · ${english?'printed page':'印刷页'} ${page.printed_page}` : ''}`) : (english?'Original PDF page and text blocks':'原 PDF 页面与文本块');
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
async function exportReadingMarkdown(verifiedOnly){
  const sourceId=state.view?.source?.source_id;if(!sourceId){notice('请先打开一份项目文献。',true);return;}
  try{
    const result=await request('/api/source/reading-markdown',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:sourceId,verified_only:verifiedOnly})});
    notice(`已导出${verifiedOnly?'仅人工核验':'当前有效'}阅读本：${result.project_path} · ${result.block_count} 个文本块。`);
  }catch(error){notice(error.message,true);}
}
$('exportCurrentReadingMarkdown').onclick=()=>exportReadingMarkdown(false);
$('exportVerifiedReadingMarkdown').onclick=()=>exportReadingMarkdown(true);
function setMode(mode) {
  document.body.classList.toggle('library-workspace-active',mode==='library');
  $('projectWorkbench').hidden = mode !== 'project';
  $('domainWorkbench').hidden = mode !== 'domain';
  $('libraryWorkbench').hidden = mode !== 'library';
  $('libraryViews').hidden = mode !== 'library';
  $('agentWorkbench').hidden = mode !== 'agent';
  $('articleWorkbench').hidden = mode !== 'article';
  $('pdfWorkbench').hidden = mode !== 'source';
  $('browserWorkbench').hidden = mode !== 'browser';
  $('settingsWorkbench').hidden = mode !== 'settings';
  $('skillsWorkbench').hidden = mode !== 'skills';
  $('libraryMode').classList.toggle('mode-active', mode === 'library');
  $('agentMode').classList.toggle('mode-active', mode === 'agent');
  $('projectMode').classList.toggle('mode-active', mode === 'project');
  $('domainMode').classList.toggle('mode-active', mode === 'domain');
  $('articleMode').classList.toggle('mode-active', mode === 'article');
  $('settingsMode').classList.toggle('mode-active', mode === 'settings');
  $('skillsMode').classList.toggle('mode-active', mode === 'skills');
  if (mode === 'settings') renderSettings();
  if (mode === 'project') loadProjectWorkspace().catch((error)=>notice(error.message,true));
  if (mode === 'domain') state.snapshot?loadDomainAgents().catch((error)=>notice(error.message,true)):renderDomainWorkspace();
  if (mode === 'skills') renderSkillCatalog();
  if (mode === 'browser') renderBrowserControls();
  queueMicrotask(()=>translateExactUi());
}
$('libraryMode').onclick = () => setMode('library');
$('agentMode').onclick = () => setMode('agent');
$('projectMode').onclick = () => setMode('project');
$('domainMode').onclick = () => setMode('domain');
$('articleMode').onclick = () => { setMode('article'); renderAuthoring(); };
$('skillsMode').onclick = () => setMode('skills');
$('settingsMode').onclick = () => setMode('settings');
$('projectWorkspaceCreate').onclick=async()=>{const title=window.prompt(state.language==='en'?'Project title':'项目名称',state.language==='en'?'New research project':'新的研究项目');if(!title?.trim())return;try{await request('/api/project/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})});state.projectWorkspace=null;await loadSnapshot();setMode('project');notice(state.language==='en'?'Project created in the Wenjin workspace.':'项目已建立在问津工作区。');}catch(error){notice(error.message,true);}};
$('domainImportToggle').onclick=()=>{$('domainImportPanel').hidden=!$('domainImportPanel').hidden;$('domainCreatePanel').hidden=true;};
$('domainCreateToggle').onclick=async()=>{const idea=window.prompt(state.language==='en'?'What specialist agent do you want to create?':'想创建什么领域 Agent？','');if(!idea?.trim())return;try{await request('/api/project/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`领域 Agent｜${idea.trim().slice(0,24)}`})});await loadSnapshot();const created=await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`创建领域 Agent｜${idea.trim().slice(0,24)}`,parent_thread_id:''})});state.threadId=created.thread_id;await refreshAgentSnapshot();setMode('agent');$('messageInput').value=`请把我当作第一次创建智能体的新手，一步只问一个必要问题，和我一起创建一个可安装的领域 Agent。\n\n我的想法：${idea.trim()}\n\n先确认研究问题和停止条件；不要一次列出整套表单。随后再依次询问材料来源、确定性工具与数据库、权限边界、候选输出和人工终审。确认完成后再调用领域 Agent 创建工具。`;$('messageInput').focus();if(hasAssignedMainModel()){$('sendMessage').disabled=false;$('sendMessage').click();notice('已建立独立项目和创建线程，主 Agent 将逐步提问。');}else{notice('项目和引导线程已建立；连接主模型后即可继续。',true);showModelOnboarding();}}catch(error){notice(error.message,true);}};
$('domainChooseZip').onclick=async()=>{try{const path=await nativeInvoke('choose_file',{kind:'plugin'});if(path)$('domainImportPath').value=path;}catch(error){notice(error.message,true);}};
$('domainChooseFolder').onclick=async()=>{try{const path=await nativeInvoke('choose_folder');if(path)$('domainImportPath').value=path;}catch(error){notice(error.message,true);}};
$('domainInstall').onclick=async()=>{const path=$('domainImportPath').value.trim();if(!path)return notice('请选择领域 Agent ZIP 或目录。',true);$('domainInstall').disabled=true;try{state.snapshot.plugins=await request('/api/plugins/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_root:path,runtime_command:''})});$('domainImportPath').value='';$('domainImportPanel').hidden=true;await loadDomainAgents();notice('领域 Agent 已安装并通过清单与运行时校验。');}catch(error){notice(error.message,true);}finally{$('domainInstall').disabled=false;}};
$('domainStartGuide').onclick=async()=>{const idea=$('domainAgentIdea').value.trim();if(!idea)return notice('先用自己的话说说想创建什么 Agent。',true);try{const created=await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`创建领域 Agent｜${idea.slice(0,24)}`,parent_thread_id:state.threadId||''})});state.threadId=created.thread_id;await refreshAgentSnapshot();setMode('agent');$('messageInput').value=`请把我当作第一次创建智能体的新手，一步只问一个必要问题，和我一起创建一个可安装的领域 Agent。\n\n我的初步想法：${idea}\n\n请依次帮助我确认：研究问题与停止条件；需要从聊天上传还是从研究图书馆选择材料；字段和数据库；只读、常规、敏感动作的权限；候选输出和人工终审边界。不要一开始生成空壳，确认清楚后再调用领域 Agent 创建工具。`;$('messageInput').focus();notice('已建立创建讨论。主 Agent 会按步骤引导，不要求你预先理解 Skill 或 MCP。');}catch(error){notice(error.message,true);}};
$('domainConfigureModel').onclick=()=>openDomainModelRole('domain_reasoning');
$('addDomainAttachment').onclick=()=>$('domainAttachmentInput').click();
$('closeImagePreview').onclick=()=>$('imagePreviewDialog').close();
$('imagePreviewDialog').onclick=(event)=>{if(event.target===$('imagePreviewDialog'))$('imagePreviewDialog').close();};
$('domainMessageInput').oninput=()=>{state.domainDraft=$('domainMessageInput').value;};
$('domainMessageInput').onkeydown=async(event)=>{if(event.key!=='Enter'||event.shiftKey||event.isComposing)return;event.preventDefault();const run=state.domainView?.runs?.[0];if(run?.status==='RUNNING'){const content=state.domainDraft.trim();if(content){await steerRunningRun('domain',content);state.domainDraft='';$('domainMessageInput').value='';}return;}$('sendDomainMessage').click();};
$('domainAttachmentInput').onchange=async()=>{try{if(!state.threadId){const created=await request('/api/thread/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'领域 Agent 附件',parent_thread_id:''})});state.threadId=created.thread_id;await refreshAgentSnapshot();}for(const file of [...$('domainAttachmentInput').files]){notice(`正在加入并归档 ${file.name}……`);const item=await request(`/api/thread/attachment?thread_id=${encodeURIComponent(state.threadId)}&filename=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:await file.arrayBuffer()});state.domainPendingAttachments.push(item);}renderDomainAttachmentChips();}catch(error){notice(error.message,true);}finally{$('domainAttachmentInput').value='';}};
$('sendDomainMessage').onclick=async()=>{const run=state.domainView?.runs?.[0];if(run?.status==='RUNNING'){try{await stopRunningRun('domain');}catch(error){notice(error.message,true);}return;}const content=state.domainDraft.trim()||(state.domainPendingAttachments.length?'请检查本轮上传的图片或文件。':'');const plugin=state.domainView?.session?.plugin_name;if(!plugin||!content)return;$('sendDomainMessage').disabled=true;let polling=false;const timer=setInterval(async()=>{if(polling||!state.domainSessionId)return;polling=true;try{state.domainView=await request(`/api/domain-agent?id=${encodeURIComponent(state.domainSessionId)}`);renderDomainWorkspace();notice(domainRunNotice());}catch(error){console.warn('Domain run refresh failed',error);}finally{polling=false;}},1000);try{const attached_refs=state.domainPendingAttachments.map((item)=>({attachment_id:item.attachment_id,original_name:item.original_name,media_type:item.media_type,sha256:item.sha256,project_path:item.project_path,library_work_id:item.library_work_id||''}));notice(state.language==='en'?'Domain agent is reasoning and preparing tools…':'领域 Agent 正在思考并准备调用工具……');state.domainView=await request('/api/domain-agent/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plugin_name:plugin,content,main_thread_id:state.threadId,access_mode:$('domainAccessMode').value,reasoning_mode:state.domainReasoningMode,reasoning_effort:state.domainReasoningEffort,attached_refs})});state.domainDraft='';state.domainPendingAttachments=[];renderDomainWorkspace();notice(state.language==='en'?'The domain agent response, attachments, and tool receipts were saved.':'领域 Agent 的答复、附件与工具回执已保存。');}catch(error){if(state.domainSessionId)await loadDomainSession(state.domainSessionId);notice(error.message,true);}finally{clearInterval(timer);setRunButton($('sendDomainMessage'),state.domainView?.runs?.[0],Boolean(state.domainView)&&hasAssignedMainModel());}};
$('languageToggle').onclick=()=>{state.language=state.language==='zh-CN'?'en':'zh-CN';localStorage.setItem('wenjinLanguage',state.language);applyLanguage();renderAgentShell();renderProjectWorkspace();renderDomainWorkspace();renderLibraryShell();renderAuthoring();renderSkillCatalog();renderSettings();notice(state.language==='en'?'Project workspace ready.':'项目工作区已就绪。');queueMicrotask(()=>translateExactUi());};
$('configureMainModel').onclick=()=>{const main=state.modelSettings?.roles?.find((item)=>item.role==='main_reasoning');if(main?.provider==='disabled'&&main.preset_id==='deepseek')main.provider='openai_compatible';$('modelOnboarding').close();state.settingsTab='models';sessionStorage.setItem('wenjinSettingsTab','models');setMode('settings');renderSettings();};
$('continueWithoutModel').onclick=()=>{sessionStorage.setItem('wenjinModelOnboardingDismissed','1');$('modelOnboarding').close();notice(state.language==='en'?'Model-dependent features remain disabled.':'需要模型的功能仍保持停用。');};
$('settingsTabs').onclick=(event)=>{const button=event.target.closest('[data-settings-tab]');if(!button)return;state.settingsTab=button.dataset.settingsTab;sessionStorage.setItem('wenjinSettingsTab',state.settingsTab);renderSettings();};
$('libraryViews').onclick=(event)=>{const button=event.target.closest('[data-library-view]');if(!button)return;if(button.dataset.libraryView==='graph'&&state.libraryView!=='graph')state.libraryGraphQuery='';setLibraryView(button.dataset.libraryView);};
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
  try { captureDocumentSection(); state.document = await request('/api/manuscript/document/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manuscript_id:state.manuscriptId,document:state.document.document})}); state.editorDirty=false;await refreshAuthoring('结构化稿件已保存为新修订；旧修订保持不变。'); }
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
$('documentCanvas').onmouseup = () => { captureWritingSelection(); currentSelectionContext(); $('writingSelectionOnly')?.dispatchEvent(new Event('change')); };
$('documentCanvas').onkeyup = () => { captureWritingSelection(); currentSelectionContext(); $('writingSelectionOnly')?.dispatchEvent(new Event('change')); };
$('documentCanvas').oninput=()=>{state.editorDirty=true;$('manuscriptStats').textContent=`${$('manuscriptStats').textContent.replace(/ · 有未保存修改$/,'')} · 有未保存修改`;};
$('editorZoomOut').onclick=()=>{state.editorZoom=Math.max(.75,state.editorZoom-.1);localStorage.setItem('wenjinEditorZoom',state.editorZoom);$('documentCanvas').style.fontSize=`${16*state.editorZoom}px`;};
$('editorZoomIn').onclick=()=>{state.editorZoom=Math.min(1.6,state.editorZoom+.1);localStorage.setItem('wenjinEditorZoom',state.editorZoom);$('documentCanvas').style.fontSize=`${16*state.editorZoom}px`;};
$('readingMode').onclick=()=>{state.readingMode=!state.readingMode;$('documentCanvas').contentEditable=state.readingMode?'false':'true';$('articleWorkbench').classList.toggle('reading-focus',state.readingMode);$('readingMode').textContent=state.readingMode?'退出阅读':'阅读模式';};
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
    notice('已建立后台只读盘点；尚未把任何材料加入图书馆……');
    state.libraryScan = await request('/api/library/scan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_root:sourceRoot, skill_name:$('intakeSkill').value})});
    state.libraryScanPage=1;sessionStorage.setItem('hrwLibraryScanId',state.libraryScan.session_id);sessionStorage.setItem('hrwLibraryScanPage','1');
    renderScan();notice('盘点已在后台开始；进度会自动更新，刷新页面也不会丢失。');
    await loadLibraryScan(state.libraryScan.session_id,1);
  } catch (error) { notice(error.message, true); }
  finally { $('scanLibrary').disabled = false; }
};
$('chooseFolder').onclick=async()=>{try{const path=await nativeInvoke('choose_folder');if(path)$('scanRoot').value=path;}catch(error){notice(error.message,true);}};
$('libraryUploadButton').onclick=()=>$('libraryUploadInput').click();
$('libraryUploadInput').onchange=async()=>{let added=0;try{for(const file of [...$('libraryUploadInput').files]){notice(`正在归档 ${file.name}……`);await request(`/api/library/upload?filename=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:await file.arrayBuffer()});added+=1;}await loadSnapshot();state.libraryWorks=state.snapshot.library_works||[];renderWorkList();notice(`已归档 ${added} 个文件并自动整理题名页/首页书目信息；右侧可人工修正，采用到项目时再自动生成全文页级文本。相同内容不会重复登记。`);}catch(error){notice(error.message,true);}finally{$('libraryUploadInput').value='';}};
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
    await loadLibraryScan(state.libraryScan.session_id,state.libraryScanPage);
    if (result.approved[0]) state.libraryWorkId = result.approved[0].work_id;
    await refreshLibrary(); notice(`已批准 ${result.approved.length} 个候选并保存自动整理的书目信息；右侧仍可人工修正。原文件没有移动或修改。`);
  } catch (error) { notice(error.message, true); }
  finally { $('approveCandidates').disabled = false; }
};
$('searchLibrary').onclick = async () => {
  try {
    state.libraryWorks = await request(`/api/library/search?q=${encodeURIComponent($('libraryQuery').value.trim())}`);
    renderWorkList();if(state.libraryWorks.length&&!state.libraryWorks.some(item=>item.work_id===state.libraryWorkId))await loadWork(state.libraryWorks[0].work_id);if(state.libraryView==='graph'){state.libraryGraphQuery=$('libraryQuery').value.trim();await setLibraryView('graph');}notice(`找到 ${state.libraryWorks.length} 部作品。`);
  } catch (error) { notice(error.message, true); }
};
$('libraryQuery').onkeydown = (event) => { if (event.key === 'Enter') $('searchLibrary').click(); };
$('libraryShelf').onchange = () => renderWorkList();
$('newThread').onclick = async () => {
  const title = window.prompt('这个研究线程讨论什么？', '新的研究讨论');
  if (!title?.trim()) return;
  try {
    const thread = await request('/api/thread/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title,parent_thread_id:state.threadId||''})});
    state.threadId = thread.thread_id; await refreshAgentSnapshot(); notice('研究线程已创建并保存在本地项目。');
  } catch (error) { notice(error.message, true); }
};
$('modelProfile').onchange = async (event) => {
  try {
    if(event.target.value.startsWith('model:')){const role=state.modelSettings.roles.find((item)=>item.role==='main_reasoning');const result=await request('/api/model-settings/save',localSessionOptions({role:'main_reasoning',provider:role.provider,model:event.target.value.slice(6),base_url:role.base_url,api_key:'',clear_secret:false,timeout_seconds:role.timeout_seconds,context_window:role.context_window,preset_id:role.preset_id}));state.modelSettings=result.settings;}else await request('/api/model/assign', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({profile_id:event.target.value})});
    await refreshAgentSnapshot(); notice('主模型配置已更新；只影响之后的新 Run。');
  } catch (error) { notice(error.message, true); }
};
$('approveAllCandidates').onclick = async () => {
  if(!state.libraryScan || Number(state.libraryScan.eligible_remaining_count || 0) === 0)return;
  const count=Number(state.libraryScan.eligible_remaining_count || 0);
  if(!window.confirm(`将按建议书架批量登记 ${count} 个可处理候选。原文件不会移动或修改，分类以后仍可人工调整。继续吗？`))return;
  $('approveAllCandidates').disabled=true;
  try{
    const result=await request('/api/library/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:state.libraryScan.session_id})});
    await loadLibraryScan(state.libraryScan.session_id,state.libraryScanPage);
    if(result.approved[0])state.libraryWorkId=result.approved[0].work_id;
    await refreshLibrary();notice(`已按建议分类入库 ${result.approved.length} 个候选并保存题名页/首页整理结果；右侧仍可人工修正。原文件没有移动或修改。`);
  }catch(error){notice(error.message,true);}
  finally{$('approveAllCandidates').disabled=false;}
};
$('planningMode').onchange = (event) => {
  state.planningMode = event.target.value;
  sessionStorage.setItem('hrwPlanningMode', state.planningMode);
  notice(state.planningMode === 'independent_planning'
    ? '本轮只处理当前问题和你明确调用的项目材料。'
    : '本轮沿用已经批准的研究计划和少量相关对话；对话不是来源证据。');
};
$('reasoningMode').value=state.reasoningMode;
$('reasoningMode').onchange=(event)=>{state.reasoningMode=event.target.value;sessionStorage.setItem('wenjinReasoningMode',state.reasoningMode);notice(state.reasoningMode==='deep'?'之后的新任务将启用深度推理。':'之后的新任务使用标准推理。');};
$('reasoningEffort').value=state.reasoningEffort;
$('reasoningEffort').onchange=(event)=>{state.reasoningEffort=event.target.value;sessionStorage.setItem('wenjinReasoningEffort',state.reasoningEffort);notice(`之后的新任务使用${event.target.options[event.target.selectedIndex].text}思考强度。`);};
$('domainReasoningMode').onchange=(event)=>{state.domainReasoningMode=event.target.value;sessionStorage.setItem('wenjinDomainReasoningMode',state.domainReasoningMode);};
$('domainReasoningEffort').onchange=(event)=>{state.domainReasoningEffort=event.target.value;sessionStorage.setItem('wenjinDomainReasoningEffort',state.domainReasoningEffort);};
$('agentAccessMode').value=state.accessMode;
$('agentAccessMode').onchange=(event)=>{
  const selected=event.target.value;
  if(selected==='full_computer'&&!window.confirm('完全访问会在本次运行中自动批准 Computer Use、文件、程序、命令和已安装领域包暴露的动作。密码控件、凭据提取、验证码求解和付款确认仍不可用。继续吗？')){
    event.target.value=state.accessMode;return;
  }
  state.accessMode=selected;
  sessionStorage.setItem('wenjinAgentAccessMode',selected);
  notice(selected==='ask'?'Agent会在每个改变电脑状态的动作前请求批准。':selected==='research_assist'?'权限代理会自动批准常规操作，程序启动、命令执行等敏感动作仍会询问。':'本次运行可自动使用整台电脑和已安装领域包提供的工具；每个动作仍写入审计记录。');
};
$('attachFiles').onclick=()=>{if(!state.threadId){notice('请先创建一个研究线程。',true);return;}$('chatAttachmentInput').click();};
$('chatAttachmentInput').onchange=async()=>{for(const file of [...$('chatAttachmentInput').files]){try{notice(`正在加入 ${file.name}……`);const item=await request(`/api/thread/attachment?thread_id=${encodeURIComponent(state.threadId)}&filename=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:await file.arrayBuffer()});state.pendingAttachments.push(item);renderAttachmentChips();}catch(error){notice(error.message,true);}}$('chatAttachmentInput').value='';};
$('messageInput').onkeydown=async(event)=>{if(event.key!=='Enter'||event.shiftKey||event.isComposing)return;event.preventDefault();if(latestRun()?.status==='RUNNING'){const content=$('messageInput').value.trim();if(content){await steerRunningRun('main',content);$('messageInput').value='';}return;}$('sendMessage').click();};
$('sendMessage').onclick = async () => {
  const run=latestRun();
  if(run?.status==='RUNNING'){try{await stopRunningRun('main');}catch(error){notice(error.message,true);}return;}
  const content = $('messageInput').value.trim() || (state.pendingAttachments.length?'请检查本轮附加文件。':'');
  if (!state.threadId) { notice('请先创建一个研究线程。', true); return; }
  if (!content) { notice('请输入研究任务或加入文件。', true); return; }
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
    const attached_refs=state.pendingAttachments.map((item)=>({attachment_id:item.attachment_id,original_name:item.original_name,media_type:item.media_type,sha256:item.sha256,project_path:item.project_path}));
    const payload={thread_id:threadId,content,planning_mode:state.planningMode,access_mode:state.accessMode,reasoning_mode:state.reasoningMode,reasoning_effort:state.reasoningEffort};if(attached_refs.length)payload.context={attached_refs};
    state.thread = await request('/api/agent/message', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    $('messageInput').value = '';state.pendingAttachments=[];renderAttachmentChips();await refreshAgentSnapshot();
    const status=latestRun()?.status;
    notice(status==='WAITING_FOR_APPROVAL'?'Agent 已暂停，等待你检查右侧提案。':status==='STOPPED'?'运行已按要求停止；发送下一条指令时才会继续。':status==='FAILED'?liveRunNotice(latestRun()):'本次运行已完成。',status==='FAILED');
  } catch (error) {
    try { await refreshAgentSnapshot(); } catch (refreshError) { console.warn('Failed run refresh failed', refreshError); }
    notice(latestRun()?.status==='FAILED' ? liveRunNotice(latestRun()) : error.message, true);
  }
  finally { clearInterval(progressTimer); setRunButton($('sendMessage'),latestRun(),hasAssignedMainModel()); }
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
$('controlledBrowser').onclick = async () => {
  const url=$('browserAddress').value.trim(); let domain='';
  try { domain=new URL(url).hostname; } catch { notice('请输入完整的网址。',true); return; }
  try {
    notice('正在启动可见的受控研究浏览器……');
    state.browserSession=await request('/api/browser/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_url:url,allowed_domain:domain})});
    const launched=await request('/api/browser/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:state.browserSession.session_id})});
    await refreshResearch(state.browserSession.reused ? '已复用该数据库的持久浏览会话；无需重复建立登录窗口。' : '受控浏览器已打开；请在可见窗口处理登录、验证码、滑块和下载。');
    state.browserSession=launched; renderBrowserControls();
  } catch(error) { notice(error.message,true); }
};
$('externalBrowser').onclick = () => { const url=$('browserAddress').value.trim(); try { new URL(url); window.open(url,'_blank','noopener'); } catch { notice('请输入完整的网址。',true); } };

function configureRightPanel(workbenchId,handleId,panelId,toggleId,cssVariable,storageKey,minWidth,maxWidth){
  const root=$(workbenchId),handle=$(handleId),panel=$(panelId),toggle=$(toggleId);
  const saved=Number(localStorage.getItem(`${storageKey}Width`)||0);if(saved)root.style.setProperty(cssVariable,`${Math.min(maxWidth,Math.max(minWidth,saved))}px`);
  toggle.classList.add('sidebar-toggle');
  const update=()=>{const collapsed=localStorage.getItem(`${storageKey}Collapsed`)==='1';root.classList.toggle('right-collapsed',collapsed);toggle.dataset.zh=collapsed?'显示侧栏':'隐藏侧栏';toggle.dataset.en=collapsed?'Show sidebar':'Hide sidebar';const label=state.language==='en'?toggle.dataset.en:toggle.dataset.zh;toggle.textContent=collapsed?'‹':'›';toggle.title=label;toggle.setAttribute('aria-label',label);};
  toggle.onclick=()=>{localStorage.setItem(`${storageKey}Collapsed`,root.classList.contains('right-collapsed')?'0':'1');update();};
  handle.onpointerdown=(event)=>{event.preventDefault();const startX=event.clientX,startWidth=panel.getBoundingClientRect().width;let proposed=startWidth;handle.classList.add('dragging');const move=(current)=>{proposed=startWidth+startX-current.clientX;const width=Math.min(maxWidth,Math.max(minWidth,proposed));root.style.setProperty(cssVariable,`${width}px`);localStorage.setItem(`${storageKey}Width`,String(Math.round(width)));};const stop=()=>{if(proposed<=minWidth+30)localStorage.setItem(`${storageKey}Collapsed`,'1');update();handle.classList.remove('dragging');document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',stop);};document.addEventListener('pointermove',move);document.addEventListener('pointerup',stop);};
  update();
}

configureRightPanel('agentWorkbench','contextResizeHandle','contextContent','toggleContextPanel','--context-width','wenjinContext',280,720);
configureRightPanel('libraryWorkbench','libraryDetailResizeHandle','libraryDetailPanel','toggleLibraryDetail','--library-detail-width','wenjinLibraryDetail',280,760);
configureRightPanel('projectWorkbench','projectActivityResizeHandle','projectActivityPanel','toggleProjectActivity','--project-activity-width','wenjinProjectActivity',260,620);
configureRightPanel('domainWorkbench','domainActivityResizeHandle','domainActivityPanel','toggleDomainActivity','--domain-activity-width','wenjinDomainActivity',260,620);
configureRightPanel('articleWorkbench','authoringControlResizeHandle','authoringControlPanel','toggleAuthoringControl','--authoring-control-width','wenjinAuthoringControl',300,720);

const initialMode = new URLSearchParams(window.location.search).get('mode');
applyLanguage();
const languageObserver=new MutationObserver((mutations)=>{
  for(const mutation of mutations)for(const added of mutation.addedNodes){
    if(added.nodeType===Node.TEXT_NODE)translateExactUi(added.parentElement);
    else if(added.nodeType===Node.ELEMENT_NODE)translateExactUi(added);
  }
});
languageObserver.observe(document.body,{childList:true,subtree:true});
setMode(['agent', 'project', 'domain', 'article', 'library', 'skills', 'settings', 'browser', 'source'].includes(initialMode) ? initialMode : 'project');
loadSnapshot().then(async()=>{
  if(!$('projectWorkbench').hidden)await loadProjectWorkspace();
  if(!$('domainWorkbench').hidden)await loadDomainAgents();
  await restoreLibraryScan();
  showModelOnboarding();
  notice(state.language==='en'?'Project workspace ready.':'项目工作区已就绪。');
}).catch((error) => notice(error.message, true));
