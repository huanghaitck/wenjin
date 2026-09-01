const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const localPython = path.join(__dirname, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = fs.existsSync(localPython) ? `"${localPython}"` : 'python';

module.exports = defineConfig({
  testDir: './tests/ui',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:8777', viewport: { width: 1440, height: 900 }, trace: 'retain-on-failure' },
  webServer: {
    command: `${python} -m research_workbench.cli desktop-serve --data-root .playwright-data --host 127.0.0.1 --port 8777 --desktop-build ci`,
    url: 'http://127.0.0.1:8777',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
