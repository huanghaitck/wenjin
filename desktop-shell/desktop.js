const frame = document.getElementById('workbench');
const startup = document.getElementById('startup');
const allowed = new Set(['desktop_status', 'choose_folder', 'choose_file', 'open_in_word']);
let workbenchOrigin = '';
let frameRetry = 0;
const invoke = window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;

window.startWorkbench = (url) => {
  workbenchOrigin = new URL(url).origin;
  frame.src = url;
  frameRetry = window.setInterval(() => { frame.src = url; }, 1000);
  window.setTimeout(() => {
    if (frameRetry) {
      window.clearInterval(frameRetry);
      frameRetry = 0;
      document.getElementById('status').textContent = '本地研究服务没有在一分钟内启动，请查看应用数据目录中的日志。';
      document.querySelector('.bar').style.display = 'none';
    }
  }, 60000);
};

const waitForWorkbench = async () => {
  document.getElementById('status').textContent = '桌面桥接已启动，正在等待本地研究服务……';
  if (!invoke) {
    document.getElementById('status').textContent = '桌面桥接没有加载，请重新安装工作台。';
    document.querySelector('.bar').style.display = 'none';
    return;
  }
  for (let attempt = 0; attempt < 600; attempt += 1) {
    try {
      const url = await invoke('desktop_url');
      if (url) {
        window.startWorkbench(url);
        return;
      }
    } catch (error) {
      document.getElementById('status').textContent = `桌面桥接启动失败：${String(error)}`;
      document.querySelector('.bar').style.display = 'none';
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  document.getElementById('status').textContent = '本地研究服务没有在一分钟内启动，请查看应用数据目录中的日志。';
  document.querySelector('.bar').style.display = 'none';
};

waitForWorkbench();

window.addEventListener('message', async (event) => {
  const request = event.data?.hrwDesktopRequest;
  if (!request || event.source !== frame.contentWindow || event.origin !== workbenchOrigin) return;
  if (frameRetry) {
    window.clearInterval(frameRetry);
    frameRetry = 0;
    frame.hidden = false;
    startup.hidden = true;
  }
  const response = {id: request.id};
  try {
    if (!allowed.has(request.command)) throw new Error('未允许的桌面命令');
    response.result = await invoke(request.command, request.args || {});
  } catch (error) {
    response.error = String(error);
  }
  frame.contentWindow.postMessage({hrwDesktopResponse: response}, workbenchOrigin);
});
