const { test, expect } = require('@playwright/test');

async function dismissModelOnboarding(page) {
  const dialog = page.locator('#modelOnboarding');
  await dialog.waitFor({ state: 'visible', timeout: 2_000 }).catch(() => {});
  if (await dialog.isVisible()) await page.locator('#continueWithoutModel').click();
}

test('compact research and domain workspaces keep controls readable', async ({ page }) => {
  await page.goto('/?mode=agent');
  await dismissModelOnboarding(page);
  await expect(page.locator('#settingsMode')).toHaveAttribute('aria-label', '设置');
  await expect(page.locator('#mainRunStatus')).toBeAttached();
  const navBoxes = await page.locator('.topbar .importer > button').evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().toJSON()));
  for (let index = 1; index < navBoxes.length; index += 1) expect(navBoxes[index].left).toBeGreaterThanOrEqual(navBoxes[index - 1].right - 1);

  await page.setViewportSize({ width: 1080, height: 700 });
  await page.locator('#domainMode').click();
  await expect(page.locator('#domainModelLabel')).toHaveText('请先选择 Agent');
  await expect(page.locator('#domainConfigureModel')).toBeDisabled();
  const columns = await page.locator('#domainWorkbench').evaluate((node) => getComputedStyle(node).gridTemplateColumns);
  expect(columns.split(' ').length).toBeGreaterThanOrEqual(4);
  const actions = await page.locator('.domain-manager-actions button').evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().toJSON()));
  expect(actions[1].top).toBeGreaterThanOrEqual(actions[0].bottom - 1);
});

test('settings feedback and help are visible in place', async ({ page }) => {
  await page.goto('/?mode=settings');
  await dismissModelOnboarding(page);
  await expect(page.locator('[data-settings-tab="plugins"]')).toBeVisible();
  await expect(page.locator('[data-settings-tab="appearance"]')).toBeVisible();
  await page.locator('[data-settings-tab="appearance"]').click();
  await page.getByRole('button', { name: '保存外观设置' }).click();
  await expect(page.locator('#settingsFeedback')).toHaveText('外观设置已保存。');
  await page.locator('#helpMode').click();
  await expect(page.locator('#helpDialog')).toBeVisible();
  await expect(page.getByRole('button', { name: /完整使用手册/ })).toBeVisible();
});

test('a new research thread starts with an empty composer', async ({ page }) => {
  await page.goto('/?mode=agent');
  await dismissModelOnboarding(page);
  await page.locator('#messageInput').fill('不应带入新线程的旧草稿');
  page.once('dialog', (dialog) => dialog.accept('线程清空验收'));
  await page.locator('#newThread').click();
  await expect(page.locator('#messageInput')).toHaveValue('');
  await expect(page.locator('#attachmentChips')).toBeEmpty();
});

test('settings and help expose English labels after language switch', async ({ page }) => {
  await page.goto('/?mode=settings');
  await dismissModelOnboarding(page);
  if (await page.locator('#languageToggle').textContent() === 'EN') await page.locator('#languageToggle').click();
  await expect(page.locator('#settingsHeading')).toHaveText('Settings');
  await expect(page.locator('#settingsTabs')).toHaveAttribute('aria-label', 'Settings sections');
  await expect(page.locator('#helpMode')).toHaveAttribute('aria-label', 'Help');
  await page.locator('#helpMode').click();
  await expect(page.getByRole('button', { name: /User manual/ })).toBeVisible();
});

test('workspace sidebars stay in their own columns without stacking', async ({ page }) => {
  await page.goto('/?mode=project');
  await dismissModelOnboarding(page);
  const brand = await page.locator('.brand-copy').boundingBox();
  const topbar = await page.locator('.topbar').boundingBox();
  expect(brand.y).toBeGreaterThanOrEqual(topbar.y);
  expect(brand.y + brand.height).toBeLessThanOrEqual(topbar.y + topbar.height + 1);

  const projectMain = await page.locator('.project-dashboard-panel').boundingBox();
  const projectSide = await page.locator('.project-activity-panel').boundingBox();
  expect(projectSide.x).toBeGreaterThan(projectMain.x + projectMain.width - 1);
  expect(projectSide.y).toBe(projectMain.y);

  await page.locator('#libraryMode').click();
  const catalog = await page.locator('.catalog-panel').boundingBox();
  const detail = await page.locator('.work-detail-panel').boundingBox();
  expect(detail.x).toBeGreaterThan(catalog.x + catalog.width - 1);
  expect(detail.y).toBe(catalog.y);

  await page.locator('#settingsMode').click();
  const settings = await page.locator('#settingsWorkbench').evaluate((node) => getComputedStyle(node).gridTemplateColumns);
  expect(settings.split(' ').length).toBe(3);
});

test('hiding a left sidebar keeps the main conversation and right context visible', async ({ page }) => {
  await page.goto('/?mode=agent');
  await dismissModelOnboarding(page);
  await page.locator('#primarySidebarToggle').click();
  await expect(page.locator('#agentWorkbench')).toHaveClass(/left-collapsed/);
  const conversation = await page.locator('.conversation-panel').boundingBox();
  const context = await page.locator('.activity-panel').boundingBox();
  expect(conversation.width).toBeGreaterThan(500);
  expect(context.width).toBeGreaterThan(250);
  expect(context.x).toBeGreaterThan(conversation.x + conversation.width - 1);
});

test('skills library uses the full workspace instead of the settings sidebar grid', async ({ page }) => {
  await page.goto('/?mode=skills');
  await dismissModelOnboarding(page);
  const root = await page.locator('#skillsWorkbench').boundingBox();
  const content = await page.locator('#skillsWorkbench > .settings-main').boundingBox();
  expect(content.width).toBeGreaterThan(root.width * 0.8);
  expect(content.x).toBe(root.x);
});

test('project naming and auxiliary model settings use Wenjin dialogs', async ({ page }) => {
  await page.goto('/?mode=project');
  await dismissModelOnboarding(page);
  await page.locator('#projectWorkspaceCreate').click();
  await expect(page.locator('#projectCreateDialog')).toBeVisible();
  await expect(page.locator('#projectCreateTitle')).toHaveValue('新的历史研究项目');
  await expect(page.locator('#projectCreateDialog input[value="workspace"]')).toBeChecked();
  await page.locator('#cancelProjectCreate').click();

  await page.locator('#settingsMode').click();
  await expect(page.locator('.aux-role-row').first()).toBeVisible();
  await page.locator('.aux-role-row').first().click();
  await expect(page.locator('#modelRoleDialog')).toBeVisible();
  await expect(page.locator('#modelRoleDialogBody .model-role-form')).toBeVisible();
  await page.locator('#closeModelRoleDialog').click();
  await expect(page.locator('#modelRoleDialog')).toBeHidden();
});

test('skill rows open a detailed skill view', async ({ page }) => {
  await page.goto('/?mode=skills');
  await dismissModelOnboarding(page);
  await expect(page.locator('.skill-list-row').first()).toBeVisible();
  await page.locator('.skill-list-row').first().click();
  await expect(page.locator('#skillDetailDialog')).toBeVisible();
  await expect(page.locator('#skillDetailBody .skill-detail-meta')).toBeVisible();
  await page.locator('#closeSkillDetailDialog').click();
});

test('side controls sit with the panel they control and the left panel resizes', async ({ page }) => {
  await page.goto('/?mode=project');
  await dismissModelOnboarding(page);
  await expect(page.locator('#secondarySidebarToggle')).toBeVisible();
  await expect(page.locator('#projectActivityPanel #toggleProjectActivity')).toBeHidden();
  await expect(page.locator('#projectListPanel #toggleProjectActivity')).toHaveCount(0);
  await page.locator('#secondarySidebarToggle').click();
  await expect(page.locator('#projectActivityPanel')).toBeHidden();
  await expect(page.locator('#secondarySidebarToggle')).toBeVisible();
  await page.locator('#secondarySidebarToggle').click();
  await expect(page.locator('#projectActivityPanel')).toBeVisible();

  await page.locator('#agentMode').click();
  const before = await page.locator('#threadPanel').boundingBox();
  const handle = await page.locator('#agentLeftResizeHandle').boundingBox();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + 40);
  await page.mouse.down();
  await page.mouse.move(handle.x + 90, handle.y + 40);
  await page.mouse.up();
  const after = await page.locator('#threadPanel').boundingBox();
  expect(after.width).toBeGreaterThan(before.width + 50);
  await expect(page.locator('.activity-panel #toggleContextPanel')).toBeHidden();
  await expect(page.locator('#secondarySidebarToggle')).toBeVisible();
});
