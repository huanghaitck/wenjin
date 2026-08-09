const state = { snapshot: null, capabilities: null, view: null, pageIndex: 0, zoom: 1 };
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
