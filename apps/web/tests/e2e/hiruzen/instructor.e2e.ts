import { expect, test } from '@playwright/test';

for (const enabled of [false, true]) {
  test(`instructor preview access ${enabled}`, async ({ page }) => {
    await page.route('**/v1/practice/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/instructor/access')) {
        await route.fulfill({ status: enabled ? 200 : 403, json: { enabled } });
      } else if (path.endsWith('/preview')) {
        await route.fulfill({ json: {
          id: 'set', content_version_id: 'immutable-version', model_version: 'fixture',
          prompt_version: 'p1', validator_version: 'v1', ai_generated: true,
          official_assessment: false, evidence_sources: [],
          exercises: [{ id: 'exercise', ordinal: 0, revision: 'revision', question: {
            type: 'true_false', prompt: 'A greeting', answer: true,
            rationale: 'Teacher-only explanation', evidence_citation_ids: [],
          } }],
        } });
      } else {
        await route.fulfill({ json: path.endsWith('/books') ? { items: [] } : [] });
      }
    });
    await page.goto('/?app=hiruzen');
    const button = page.getByRole('button', { name: '教师预览 / Instructor preview' });
    if (!enabled) {
      await expect(button).toHaveCount(0);
      await expect(page.getByText('Teacher-only explanation')).toHaveCount(0);
      return;
    }
    await button.click();
    await page.getByLabel('练习编号 / Practice set ID').fill('set');
    await page.getByRole('button', { name: '查看 / View' }).click();
    await expect(page.getByText('解析 / Rationale: Teacher-only explanation')).toBeVisible();
    await expect(page.getByText('AI 生成，非正式考核 / AI-generated, not official')).toBeVisible();
    await expect(page.getByRole('button', { name: /publish|approve|发布|批准/i })).toHaveCount(0);
  });
}
