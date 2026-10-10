import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const bookId = '11111111-1111-4111-8111-111111111111';
const courseId = '22222222-2222-4222-8222-222222222222';
const planId = '33333333-3333-4333-8333-333333333333';
const moduleId = '44444444-4444-4444-8444-444444444444';
const generationId = '55555555-5555-4555-8555-555555555555';
const setId = '66666666-6666-4666-8666-666666666666';
const exerciseId = '77777777-7777-4777-8777-777777777777';
const nextExerciseId = '88888888-8888-4888-8888-888888888888';
const versionId = '99999999-9999-4999-8999-999999999999';

test('catalog → generate → hint → release → tutor → resume', async ({ page }) => {
  let attempts = 0;
  let released = false;
  let generationPolled = false;
  let chatBody: Record<string, unknown> | undefined;
  let chatCorrelationId: string | undefined;
  let reportBody: Record<string, unknown> | undefined;
  await page.route('**/v1/practice/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    let body: unknown;
    if (pathname.endsWith('/categories')) body = [
      { id: 'c1', stable_key: 'education:primary', display_name: '小学', category_type: 'education_level', parent_id: null, book_count: 1 },
      { id: 'c2', stable_key: 'publisher:fltrp', display_name: '外研社', category_type: 'publisher', parent_id: null, book_count: 1 },
    ];
    else if (pathname.endsWith('/books')) body = { items: [{ id: bookId, title: '小学英语外研社版 三年级上册', education_level: 'primary', subject: '英语', grade: '三年级', publisher: '外研社', series: '英语', edition: null, term: '上册', language: 'zh', cover_uri: null, lifecycle_status: 'published' }], next_cursor: null };
    else if (pathname.endsWith('/courses')) body = [{ course_id: courseId, course_run_id: 'run', code: 'EN3', name: '小学英语', content_version_id: versionId }];
    else if (pathname.endsWith('/study-plan')) body = { id: planId, book_id: bookId, course_id: courseId, content_version_id: versionId, name: '默认学习计划', modules: [{ id: moduleId, ordinal: 0, title: 'Module 1', objectives: [] }] };
    else if (pathname.endsWith(`/books/${bookId}`)) body = { id: bookId, title: '小学英语外研社版 三年级上册', education_level: 'primary', subject: '英语', grade: '三年级', publisher: '外研社', series: '英语', edition: null, term: '上册', language: 'zh', cover_uri: null, lifecycle_status: 'published', courses: [{ course_id: courseId, code: 'EN3', name: '小学英语', content_version_id: versionId }] };
    else if (pathname.endsWith('/generations') && method === 'POST') body = { id: generationId, status: 'queued', practice_set_id: null };
    else if (pathname.endsWith(`/generations/${generationId}`)) { generationPolled = true; body = { id: generationId, status: 'ready', practice_set_id: setId }; }
    else if (pathname.endsWith(`/sets/${setId}`)) body = { id: setId, book_id: bookId, course_id: courseId, content_version_id: versionId, study_plan_id: planId, exercises: [
      { id: exerciseId, ordinal: 0, prompt: 'What is the English word for 苹果?', type: 'multiple_choice', difficulty: 'standard', language: 'zh', evidence_citation_ids: ['chunk-1'], options: [{ id: 'A', text: 'Apple' }, { id: 'B', text: 'Pear' }] },
      { id: nextExerciseId, ordinal: 1, prompt: 'Is apple a fruit?', type: 'true_false', difficulty: 'standard', language: 'zh', evidence_citation_ids: ['chunk-2'] },
    ] };
    else if (pathname.endsWith('/attempts') && method === 'POST') { attempts++; body = { id: 'attempt-1', exercise_id: exerciseId, attempt_number: attempts, outcome: 'incorrect', correct: false, score: 0, hint: '请再看教材', released_answer: null }; }
    else if (pathname.endsWith('/give-up') && method === 'POST') { released = true; body = { id: 'attempt-2', exercise_id: exerciseId, attempt_number: attempts + 1, outcome: 'gave_up', correct: false, score: 0, hint: null, released_answer: { answer: 'A', rationale: '教材示例说明 apple 是苹果。', evidence_citation_ids: ['chunk-1'] } }; }
    else if (pathname.endsWith('/study-status')) body = { sets: generationPolled ? [{ practice_set_id: setId, book_id: bookId, status: released ? 'IN_PROGRESS' : 'NOT_STARTED', total_questions: 2, completed_questions: released ? 1 : 0, attempted_questions: attempts ? 1 : 0, correct_questions: 0, next_exercise_id: released ? nextExerciseId : exerciseId }] : [], plans: [] };
    else if (pathname.endsWith('/resume')) body = generationPolled ? { practice_set_id: setId, book_id: bookId, course_id: courseId, exercise_id: released ? nextExerciseId : exerciseId, attempt_number: released ? 0 : attempts, released: false } : null;
    else if (pathname.endsWith('/reports') && method === 'POST') { reportBody = route.request().postDataJSON() as Record<string, unknown>; body = { status: 'open' }; }
    else body = {};
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.route('**/v1/courses/*/chat', async (route) => {
    chatBody = route.request().postDataJSON() as Record<string, unknown>;
    chatCorrelationId = route.request().headers()['x-correlation-id'];
    await route.fulfill({ contentType: 'text/event-stream', body: `event: token\ndata: {"text":"Review the textbook example."}\n\nevent: citation\ndata: {"chunk_id":"chunk-1","relative_path":"English.pdf","anchor_type":"page","anchor_value":"3","text_excerpt":"apple"}\n\nevent: done\ndata: {"trace_id":"trace","answer_tokens":5,"session_id":"${planId}"}\n\n` });
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '找教材' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole('button', { name: '打开教材' }).click();
  await expect(page.getByRole('option', { name: 'Module 1' })).toHaveCount(1);
  await page.getByRole('button', { name: '生成练习' }).click();
  await expect(page.getByText('What is the English word for 苹果?')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page.getByText('参考答案')).toHaveCount(0);
  await page.getByText('Pear').click();
  await page.getByRole('button', { name: '提交答案' }).click();
  await expect(page.getByText('请再看教材')).toBeVisible();
  await expect(page.getByText('参考答案')).toHaveCount(0);
  await page.getByPlaceholder('针对当前题目提问').fill('Give me a hint');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText('Review the textbook example.')).toBeVisible();
  expect(chatBody?.assessment_mode).toBe(true);
  expect(chatBody?.attempt_number).toBe(1);
  await page.getByRole('button', { name: '放弃并查看答案' }).click();
  await expect(page.getByText(/参考答案: A/)).toBeVisible();
  await page.locator('.hiruzen-card details').last().locator('summary').click();
  await page.getByRole('combobox', { name: '问题类型' }).selectOption('unsafe');
  await page.getByRole('button', { name: '报告问题' }).click();
  await expect(page.getByText('报告已提交。')).toBeVisible();
  expect(reportBody?.reason).toBe('unsafe');
  await page.getByPlaceholder('针对当前题目提问').fill('Please explain the textbook example');
  await page.getByRole('button', { name: '发送' }).click();
  const latestTutorReply = page.locator('.hiruzen-tutor .hiruzen-message').last();
  await expect(latestTutorReply.locator('summary')).toBeVisible();
  await latestTutorReply.locator('summary').click();
  await expect(latestTutorReply.getByText('English.pdf')).toBeVisible();
  expect(chatBody?.assessment_mode).toBe(true);
  expect(chatBody?.course_id).toBeUndefined(); // Course scope belongs in the direct Agent URL.
  expect(chatBody?.attempt_number).toBe(3);
  expect(chatBody?.session_id).toBe(planId);
  expect(chatCorrelationId).toMatch(/[0-9a-f-]{36}/);
  await page.reload();
  await page.getByRole('button', { name: '学习进度' }).click();
  await page.getByRole('button', { name: '继续学习', exact: true }).click();
  await expect(page.getByText('Is apple a fruit?')).toBeVisible();
  await expect(page.getByText('参考答案')).toHaveCount(0);
});

test('language defaults to Chinese and survives a reload', async ({ page }) => {
  await page.route('**/v1/practice/**', (route) => route.fulfill({ contentType: 'application/json', body: route.request().url().endsWith('/categories') ? '[]' : '{"items":[],"next_cursor":null}' }));
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Hiruzen' })).toBeFocused();
  const language = page.getByRole('combobox', { name: '语言' });
  await expect(language).toHaveValue('zh');
  await language.selectOption('en');
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Language' })).toHaveValue('en');
  await expect(page.getByRole('heading', { name: 'Books' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Language' }).selectOption('bilingual');
  await page.reload();
  await expect(page.getByRole('heading', { name: '找教材 / Books' })).toBeVisible();
});
