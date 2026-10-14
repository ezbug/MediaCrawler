import fs from 'node:fs/promises';
import crypto from 'node:crypto';

export function validatePacket(packet, today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date())) {
  const { mail, audit } = packet;
  const hash = crypto.createHash('sha256').update(packet.canonical_email).digest('hex');
  if (audit.status !== 'passed' || audit.audited_on !== today || hash !== audit.email_hash || JSON.stringify(JSON.parse(packet.canonical_email)) !== JSON.stringify(mail)) {
    throw new Error('audit_missing_or_email_changed');
  }
  return mail;
}

const PRE_SEND_ERRORS = [
  'gmail_page_required',
  'compose_button_not_found',
  'recipient_field_not_found',
  'compose_verification_failed',
  'body_editor_missing',
  'unique_compose_dialog_required',
  'send_button_not_found',
];

async function fillAndDispatch(page, mail, audit, submit) {
  if (!(await page.url()).startsWith('https://mail.google.com/')) throw new Error('gmail_page_required');
  const hasCompose = await page.evaluate(() => document.querySelectorAll('input[name=subjectbox]').length > 0);
  if (!hasCompose) {
    const composeOpened = await page.evaluate(() => {
      const button = [...document.querySelectorAll("div[role=button],button")].find(
        (el) => /写邮件|Compose|撰写/.test(el.getAttribute("aria-label") || el.innerText || ""),
      );
      if (!button) return false;
      button.click();
      return true;
    });
    if (!composeOpened) throw new Error('compose_button_not_found');
  }
  await page.waitForSelector('input[name=subjectbox]', { timeout: 10000 });
  // Gmail 的收件人输入框被 chip 容器包着，尺寸为 0，但打开撰写后默认已聚焦；
  // 因此用键盘直接输入而不是 fill()。
  const readRecipients = () => page.evaluate(() => {
    const scope = document.querySelector('input[name=subjectbox]')?.closest('[role=dialog]');
    if (!scope) return [];
    return [...new Set([...scope.querySelectorAll('[email],[data-hovercard-id]')]
      .map((el) => el.getAttribute('email') || el.getAttribute('data-hovercard-id'))
      .filter(Boolean))];
  });
  let recipients = await readRecipients();
  if (!(recipients.length === 1 && recipients[0].toLowerCase() === mail.to.toLowerCase())) {
    const focusedTo = await page.evaluate(() => {
      const scope = document.querySelector('input[name=subjectbox]')?.closest('[role=dialog]');
      const field = scope?.querySelector('input[aria-label*="收件人"],input[aria-label*="To"]');
      if (!field) return false;
      field.focus();
      return document.activeElement === field;
    });
    if (!focusedTo) {
      throw new Error('recipient_field_not_found');
    }
    await page.keyboard.insertText(mail.to);
    await page.waitForTimeout(900);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(1200);
    recipients = await readRecipients();
  }
  await page.fill('input[name=subjectbox]', mail.subject);
  const filled = await page.evaluate(mail => {
    const subject = document.querySelector('input[name=subjectbox]');
    const scope = subject.closest('[role=dialog]');
    if (!scope) throw new Error('unique_compose_dialog_required');
    const editor = scope.querySelector('[role=textbox][contenteditable=true]');
    if (!editor) throw new Error('body_editor_missing');
    const hidden = document.createElement('div');
    hidden.setAttribute('style', 'display:none!important;max-height:0;overflow:hidden;opacity:0');
    hidden.textContent = ('\u00a0\u200c').repeat(100);
    const visible = document.createElement('div');
    visible.style.cssText = 'font-size:15px;line-height:1.8;color:#222;white-space:pre-wrap';
    visible.textContent = mail.body;
    editor.replaceChildren(hidden, visible);
    editor.dispatchEvent(new InputEvent('input', { bubbles: true }));
    return { body: visible.textContent, subject: subject.value };
  }, mail);
  if (filled.body !== mail.body || filled.subject !== mail.subject || recipients.length !== 1 || recipients[0].toLowerCase() !== mail.to.toLowerCase()) {
    throw new Error('compose_verification_failed');
  }
  if (!submit) return { status: 'draft_verified', submitted: false, email_id: audit.email_id };
  const dispatched = await page.evaluate(() => {
    const scope = document.querySelector("input[name=subjectbox]")?.closest("[role=dialog]");
    if (!scope) return false;
    const button = [...scope.querySelectorAll("div[role=button],button")].find(
      (el) => /发送|Send/.test(el.getAttribute("aria-label") || el.innerText || ""),
    );
    if (!button) return false;
    button.click();
    return true;
  });
  if (!dispatched) throw new Error('send_button_not_found');
  await page.waitForFunction(() => /邮件已发送|Message sent/.test(document.body.innerText), undefined, { timeout: 15000 });
  return { status: 'sent_ui_confirmed', submitted: true, email_id: audit.email_id };
}

export async function send(payloadPath, spaceId, submit = false) {
  const packet = JSON.parse(await fs.readFile(payloadPath, 'utf8'));
  const mail = validatePacket(packet);
  const { audit } = packet;
  const task = await taskSpace(spaceId);
  const page = task.page('p1');
  let lastError = null;
  // 只对“点击发送之前”的失败重试：先关掉残留撰写窗口并回到收件箱，再重来一次。
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await fillAndDispatch(page, mail, audit, submit);
    } catch (error) {
      const message = String((error && error.message) || error);
      const isPreSend = PRE_SEND_ERRORS.some((marker) => message.includes(marker));
      if (!isPreSend) throw error;
      lastError = error;
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(900);
      await page.goto('https://mail.google.com/mail/u/0/#inbox').catch(() => {});
      await page.waitForTimeout(2600);
    }
  }
  throw lastError;
}
