import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || 'http://127.0.0.9/api/v1'
);

const smokeMemberId = process.env.LOCAL_SMOKE_LOGIN_ID || 'nextjs_smoke';
const smokeMemberPassword =
  process.env.LOCAL_SMOKE_LOGIN_PASSWORD || 'NextjsSmoke123!';
const smokeBoard = process.env.LOCAL_SMOKE_USER_BOARD || 'free';
const smokeMarker = process.env.LOCAL_SMOKE_USER_MARKER || 'Next.js user action smoke';
const smokeRunId = `${Date.now()}`;
const smokePdfBuffer = Buffer.from(
  '%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n',
  'utf8'
);
const desktopViewport = { width: 1366, height: 900 };
const mobileViewport = { width: 390, height: 844 };

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message, details = undefined) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

function printFailure(error, prefix = 'check-local-user-actions') {
  console.error(`[${prefix}] ${error.message}`);
  if (error.details) {
    console.error(JSON.stringify(error.details, null, 2));
  }
}

function runSeed(script, env = {}, args = []) {
  const scriptPath = fileURLToPath(new URL(`../../scripts/${script}`, import.meta.url));
  const result = spawnSync('php', [scriptPath, '--json', ...args], {
    env: {
      ...process.env,
      LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
      LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
      ...env,
    },
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run ${script}: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail(`${script} failed`, {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  try {
    const payload = JSON.parse(result.stdout.trim());
    if (!payload?.success) {
      fail(`${script} did not return success`, payload);
    }
    return payload;
  } catch {
    fail(`${script} returned invalid JSON`, {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }
}

async function fetchApi(path, options = {}) {
  const response = await fetch(`${expectedApiUrl}${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // no JSON body, e.g. 204
  }

  return { response, payload };
}

async function apiJson(path, options = {}) {
  const { response, payload } = await fetchApi(path, options);

  if (!response.ok || !payload?.success) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }

  return payload;
}

async function apiOk(path, options = {}) {
  const { response, payload } = await fetchApi(path, options);
  if (!response.ok || (response.status !== 204 && payload && payload.success === false)) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }
  return payload;
}

async function login() {
  const payload = await apiJson('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ mb_id: smokeMemberId, mb_password: smokeMemberPassword }),
  });
  const token = payload.data?.token;
  const refreshToken = payload.data?.refresh_token;
  if (!token) {
    fail('smoke member login did not return a token');
  }
  return { token, refreshToken };
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function cleanupExistingSmoke(token) {
  const headers = authHeaders(token);
  const posts = await apiJson(
    `/boards/${smokeBoard}/posts?sfl=wr_subject&stx=${encodeURIComponent(smokeMarker)}&per_page=50`,
    { headers }
  );

  for (const post of posts.data || []) {
    const subject = String(post.wr_subject || '');
    if (!subject.includes(smokeMarker)) continue;
    if (post.mb_id !== smokeMemberId) {
      fail('refusing to delete a smoke-looking post owned by another member', post);
    }
    await apiOk(`/posts/${smokeBoard}/${post.wr_id}`, {
      method: 'DELETE',
      headers,
    });
  }

  const qas = await apiJson(
    `/qas?sfl=qa_subject&stx=${encodeURIComponent(smokeMarker)}&per_page=50`,
    { headers }
  );

  for (const qa of qas.data || []) {
    const subject = String(qa.qa_subject || '');
    if (!subject.includes(smokeMarker)) continue;
    if (qa.mb_id !== smokeMemberId || qa.qa_status !== 0) {
      fail('refusing to delete an answered or non-owned smoke-looking Q&A item', qa);
    }
    await apiOk(`/qas/${qa.qa_id}`, {
      method: 'DELETE',
      headers,
    });
  }
}

async function cleanupCreatedSmoke(token, state) {
  const headers = authHeaders(token);

  if (state.createdPostId) {
    const post = await fetchApi(`/posts/${smokeBoard}/${state.createdPostId}`, { headers });
    if (post.response.ok && post.payload?.success) {
      const subject = String(post.payload.data?.wr_subject || '');
      if (!subject.includes(smokeMarker) || post.payload.data?.mb_id !== smokeMemberId) {
        fail('refusing to delete a non-smoke post during cleanup', post.payload.data);
      }
      await apiOk(`/posts/${smokeBoard}/${state.createdPostId}`, {
        method: 'DELETE',
        headers,
      });
    } else if (post.response.status !== 404) {
      fail('failed to inspect created post before cleanup', {
        status: post.response.status,
        payload: post.payload,
      });
    }
    state.createdPostId = null;
  }

  if (state.createdQaId) {
    const qa = await fetchApi(`/qas/${state.createdQaId}`, { headers });
    if (qa.response.ok && qa.payload?.success) {
      const subject = String(qa.payload.data?.qa_subject || '');
      if (!subject.includes(smokeMarker) || qa.payload.data?.mb_id !== smokeMemberId) {
        fail('refusing to delete a non-smoke Q&A item during cleanup', qa.payload.data);
      }
      await apiOk(`/qas/${state.createdQaId}`, {
        method: 'DELETE',
        headers,
      });
    } else if (qa.response.status !== 404) {
      fail('failed to inspect created Q&A item before cleanup', {
        status: qa.response.status,
        payload: qa.payload,
      });
    }
    state.createdQaId = null;
  }
}

async function assertOkResponse(response, label) {
  if (!response.ok()) {
    let body = '';
    try {
      body = await response.text();
    } catch {
      // Body may be unavailable after navigation; status and URL still identify the failure.
    }
    fail(`${label} response failed`, {
      status: response.status(),
      url: response.url(),
      body,
    });
  }
}

async function assertNoHorizontalOverflow(page, label) {
  const layout = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const viewportWidth = Math.round(window.visualViewport?.width || doc.clientWidth || window.innerWidth);
    const fixedElements = new WeakSet();
    const containedOverflowValues = new Set(['auto', 'scroll', 'hidden', 'clip']);

    function isVisible(element) {
      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') {
        return false;
      }
      return element.getClientRects().length > 0;
    }

    function describeElement(element) {
      const parts = [element.tagName.toLowerCase()];
      if (element.id) {
        parts.push(`#${element.id}`);
      }
      if (element.className && typeof element.className === 'string') {
        parts.push(`.${element.className.trim().split(/\s+/).slice(0, 3).join('.')}`);
      }
      return parts.join('');
    }

    function isInsideFixedElement(element) {
      for (let current = element; current && current !== body; current = current.parentElement) {
        if (fixedElements.has(current)) {
          return true;
        }
        if (getComputedStyle(current).position === 'fixed') {
          fixedElements.add(current);
          return true;
        }
      }
      return false;
    }

    function isInsideHorizontalOverflowContainer(element) {
      for (let current = element.parentElement; current && current !== body; current = current.parentElement) {
        const style = getComputedStyle(current);
        if (!containedOverflowValues.has(style.overflowX)) {
          continue;
        }
        const rect = current.getBoundingClientRect();
        if (rect.left >= -1 && rect.right <= viewportWidth + 1) {
          return true;
        }
      }
      return false;
    }

    const offenders = Array.from(document.querySelectorAll('body *'))
      .filter((element) => !isInsideFixedElement(element))
      .filter((element) => !isInsideHorizontalOverflowContainer(element))
      .map((element) => ({ element, rect: element.getBoundingClientRect() }))
      .filter(({ element, rect }) => {
        if (rect.width <= 0 || rect.height <= 0 || !isVisible(element)) {
          return false;
        }
        return rect.left < -1 || rect.right > viewportWidth + 1;
      })
      .map(({ element, rect }) => ({
        element: describeElement(element),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        overflow: Math.ceil(Math.max(0, rect.right - viewportWidth, -rect.left)),
      }))
      .sort((a, b) => b.overflow - a.overflow)
      .slice(0, 10);

    return {
      viewportWidth,
      horizontalOverflow: offenders.reduce((max, offender) => Math.max(max, offender.overflow), 0),
      offenders,
    };
  });

  if (layout.horizontalOverflow > 1) {
    fail(`${label} has horizontal overflow`, layout);
  }
}

async function withViewport(page, viewport, callback) {
  const previous = page.viewportSize() || desktopViewport;
  await page.setViewportSize(viewport);
  try {
    return await callback();
  } finally {
    await page.setViewportSize(previous);
  }
}

async function fillRichTextOrTextarea(page, textareaSelector, content, editorIndex = -1) {
  const textarea = page.locator(textareaSelector);
  if ((await textarea.count()) > 0 && (await textarea.first().isVisible())) {
    await textarea.first().fill(content);
    return;
  }

  const editors = page.locator('.tiptap[contenteditable="true"]');
  const editor = editorIndex === -1 ? editors.last() : editors.nth(editorIndex);
  await editor.waitFor({ state: 'visible', timeout: 10000 });
  await editor.fill(content);
}

async function verifyBoardPostAndComment(page, token, state) {
  const subject = `${smokeMarker} post ${smokeRunId}`;
  const content = `${smokeMarker} post body ${smokeRunId}`;
  const comment = `${smokeMarker} comment ${smokeRunId}`;
  const attachmentName = `nextjs-user-upload-${smokeRunId}.pdf`;

  await page.goto(`${appUrl}/${smokeBoard}/write`, { waitUntil: 'networkidle' });
  await page.locator('#wr_subject').fill(subject);
  await fillRichTextOrTextarea(page, 'textarea#wr_content', content);
  const writeForm = page.locator('form').filter({ has: page.locator('#wr_subject') }).first();
  await writeForm.locator('input[type="file"]').last().setInputFiles({
    name: attachmentName,
    mimeType: 'application/pdf',
    buffer: smokePdfBuffer,
  });
  await writeForm.getByText(attachmentName, { exact: false }).waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const [postResponse, filesResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/boards/${smokeBoard}/posts`) &&
        response.request().method() === 'POST'
    ),
    page.waitForResponse(
      (response) =>
        response.url().includes(`/boards/${smokeBoard}/`) &&
        response.url().includes('/files') &&
        response.request().method() === 'POST'
    ),
    writeForm.locator('button[type="submit"]').last().click(),
  ]);
  await assertOkResponse(postResponse, 'board post create');
  await assertOkResponse(filesResponse, 'board attachment upload');
  await page.waitForURL(new RegExp(`/${smokeBoard}/[0-9]+$`), { timeout: 10000 });
  const postId = Number(new URL(page.url()).pathname.split('/').filter(Boolean).pop() || 0);
  if (!postId) {
    fail('board post create did not navigate to a post detail URL', { url: page.url() });
  }
  state.createdPostId = postId;

  const createdPost = await apiJson(`/posts/${smokeBoard}/${postId}`, {
    headers: authHeaders(token),
  });
  if (
    createdPost.data?.wr_subject !== subject ||
    !String(createdPost.data?.wr_content || '').includes(content) ||
    createdPost.data?.mb_id !== smokeMemberId
  ) {
    fail('board post create did not persist through the API', createdPost.data);
  }

  const detailFile = (createdPost.data?.files || []).find(
    (file) => String(file.bf_source || '') === attachmentName
  );
  if (!detailFile?.bf_url || Number(detailFile.bf_filesize || 0) <= 0) {
    fail('board attachment did not appear in the post detail payload', createdPost.data?.files);
  }

  const fileList = await apiJson(`/boards/${smokeBoard}/${postId}/files`, {
    headers: authHeaders(token),
  });
  const persistedFile = (fileList.data || []).find(
    (file) => String(file.bf_source || '') === attachmentName
  );
  if (!persistedFile?.bf_url || Number(persistedFile.bf_filesize || 0) <= 0) {
    fail('board attachment upload did not persist through the files API', fileList.data);
  }

  await page.goto(`${appUrl}/${smokeBoard}/${postId}`, { waitUntil: 'networkidle' });
  await page.getByText(attachmentName, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await fillRichTextOrTextarea(page, 'textarea[placeholder="댓글을 입력하세요"]', comment);

  const [commentResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/comments/${smokeBoard}/${postId}`) &&
        response.request().method() === 'POST'
    ),
    page.locator('button').filter({ hasText: '댓글 등록' }).last().click(),
  ]);
  await assertOkResponse(commentResponse, 'comment create');

  const commentedPost = await apiJson(`/posts/${smokeBoard}/${postId}`, {
    headers: authHeaders(token),
  });
  const persistedComment = (commentedPost.data?.comments || []).find(
    (item) => String(item.wr_content || '').includes(comment)
  );
  const commentId = Number(persistedComment?.wr_id || 0);
  if (!commentId) {
    fail('comment create did not persist through the API', commentedPost.data?.comments);
  }

  return {
    postId,
    commentId,
    subject,
    comment,
    attachment: attachmentName,
  };
}

async function verifyMypageActivityLists(page, token, activity) {
  const headers = authHeaders(token);
  const posts = await apiJson('/members/me/posts?per_page=50', { headers });
  const post = (posts.data || []).find(
    (item) =>
      item.bo_table === smokeBoard &&
      Number(item.wr_id) === Number(activity.postId) &&
      item.wr_subject === activity.subject
  );
  if (!post) {
    fail('my posts API did not include the created board post', {
      expected: activity,
      posts: posts.data,
    });
  }

  const comments = await apiJson('/members/me/comments?per_page=50', { headers });
  const comment = (comments.data || []).find(
    (item) =>
      item.bo_table === smokeBoard &&
      Number(item.wr_id) === Number(activity.commentId) &&
      Number(item.wr_parent) === Number(activity.postId) &&
      String(item.wr_content || '').includes(activity.comment)
  );
  if (!comment) {
    fail('my comments API did not include the created comment', {
      expected: activity,
      comments: comments.data,
    });
  }

  await page.goto(`${appUrl}/mypage/posts`, { waitUntil: 'networkidle' });
  await page.getByText(activity.subject, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  await page.goto(`${appUrl}/mypage/comments`, { waitUntil: 'networkidle' });
  await page.getByText(activity.comment, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  return {
    myPostId: post.wr_id,
    myCommentId: comment.wr_id,
  };
}

async function verifyQaCreate(page, token, state) {
  const subject = `${smokeMarker} Q&A ${smokeRunId}`;
  const content = `${smokeMarker} Q&A body ${smokeRunId}`;

  await page.goto(`${appUrl}/mypage/qas/new`, { waitUntil: 'networkidle' });

  if ((await page.locator('#qa_email').count()) > 0) {
    await page.locator('#qa_email').fill(`${smokeMemberId}@example.test`);
  }
  if ((await page.locator('#qa_hp').count()) > 0) {
    await page.locator('#qa_hp').fill('010-1234-5678');
  }

  await page.locator('#qa_subject').fill(subject);
  await page.locator('#qa_content').fill(content);
  const qaForm = page.locator('form').filter({ has: page.locator('#qa_subject') }).first();

  const [qaResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().replace(/\/+$/, '').endsWith('/qas') &&
        response.request().method() === 'POST'
    ),
    qaForm.locator('button[type="submit"]').last().click(),
  ]);
  await assertOkResponse(qaResponse, 'Q&A create');
  await page.waitForURL(new RegExp('/mypage/qas/[0-9]+$'), { timeout: 10000 });
  const qaId = Number(new URL(page.url()).pathname.split('/').filter(Boolean).pop() || 0);
  if (!qaId) {
    fail('Q&A create did not navigate to a detail URL', { url: page.url() });
  }
  state.createdQaId = qaId;

  const createdQa = await apiJson(`/qas/${qaId}`, {
    headers: authHeaders(token),
  });
  if (
    createdQa.data?.qa_subject !== subject ||
    createdQa.data?.qa_content !== content ||
    createdQa.data?.mb_id !== smokeMemberId
  ) {
    fail('Q&A create did not persist through the API', createdQa.data);
  }

  return {
    qaId,
    subject,
  };
}

async function verifyMobileActivityPages(page, activity, qaActivity) {
  return withViewport(page, mobileViewport, async () => {
    const checks = [
      {
        label: 'mobile board detail attachment page',
        url: `${appUrl}/${smokeBoard}/${activity.postId}`,
        text: activity.attachment,
      },
      {
        label: 'mobile mypage posts page',
        url: `${appUrl}/mypage/posts`,
        text: activity.subject,
      },
      {
        label: 'mobile mypage comments page',
        url: `${appUrl}/mypage/comments`,
        text: activity.comment,
      },
      {
        label: 'mobile Q&A detail page',
        url: `${appUrl}/mypage/qas/${qaActivity.qaId}`,
        text: qaActivity.subject,
      },
    ];

    for (const check of checks) {
      await page.goto(check.url, { waitUntil: 'networkidle' });
      await page.getByText(check.text, { exact: false }).first().waitFor({
        state: 'visible',
        timeout: 10000,
      });
      await assertNoHorizontalOverflow(page, check.label);
    }

    return {
      mobileActivityPages: checks.length,
    };
  });
}

let browser = null;
let credentials = null;
let exitCode = 0;
const state = {
  createdPostId: null,
  createdQaId: null,
};

try {
  runSeed('seed_nextjs_smoke_user.php');
  credentials = await login();
  await cleanupExistingSmoke(credentials.token);

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: desktopViewport,
    serviceWorkers: 'block',
  });
  await context.addCookies([
    {
      name: 'g5_token',
      value: credentials.token,
      url: appUrl,
      sameSite: 'Lax',
    },
    ...(credentials.refreshToken
      ? [
          {
            name: 'g5_refresh',
            value: credentials.refreshToken,
            url: appUrl,
            sameSite: 'Lax',
          },
        ]
      : []),
  ]);

  const page = await context.newPage();
  const results = [];
  const activity = await verifyBoardPostAndComment(page, credentials.token, state);
  results.push(activity);
  results.push(await verifyMypageActivityLists(page, credentials.token, activity));
  const qaActivity = await verifyQaCreate(page, credentials.token, state);
  results.push(qaActivity);
  results.push(await verifyMobileActivityPages(page, activity, qaActivity));
  await context.close();

  console.table(results);
  console.log(`[check-local-user-actions] app=${appUrl}`);
  console.log(`[check-local-user-actions] api=${expectedApiUrl}`);
} catch (error) {
  printFailure(error);
  exitCode = 1;
} finally {
  if (browser) {
    await browser.close();
  }
  if (credentials?.token) {
    try {
      await cleanupCreatedSmoke(credentials.token, state);
      await cleanupExistingSmoke(credentials.token);
    } catch (error) {
      printFailure(error, 'check-local-user-actions cleanup');
      exitCode = 1;
    }
  }
  try {
    runSeed('seed_nextjs_smoke_user.php');
  } catch (error) {
    printFailure(error, 'check-local-user-actions reset');
    exitCode = 1;
  }
}

process.exit(exitCode);
