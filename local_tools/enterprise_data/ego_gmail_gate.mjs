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

async function discardLeftoverCompose(page) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const count = await page.evaluate(() => document.querySelectorAll('input[name=subjectbox]').length);
    if (!count) return;
    await page.evaluate(() => {
      const boxes = [...document.querySelectorAll('input[name=subjectbox]')];
      const last = boxes[boxes.length - 1];
      const dialog = last && last.closest('[role=dialog]');
      const editor = dialog && dialog.querySelector('[role=textbox]');
      (editor || last)?.focus?.();
    });
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(700);
    const clicked = await page.evaluate(() => {
      const discard = [...document.querySelectorAll('[role=button],button')].find(
        (el) => /丢弃|Discard/.test(el.getAttribute('aria-label') || el.innerText || ""),
      );
      if (discard) { discard.click(); return true; }
      const close = [...document.querySelectorAll('[role=button],button')].find(
        (el) => /关闭|Close/.test(el.getAttribute('aria-label') || ""),
      );
      if (close) { close.click(); return true; }
      return false;
    });
    await page.waitForTimeout(clicked ? 1000 : 500);
  }
}

async function fillAndDispatch(page, mail, audit, submit) {
  await discardLeftoverCompose(page).catch(() => {});
  const composeUrl = "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1" +
    `&to=${encodeURIComponent(mail.to)}&su=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(mail.body)}`;
  await page.goto(composeUrl, { timeout: 30000, waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[name=subjectbox]", { state: "visible", timeout: 20000 });
  await page.waitForTimeout(1200);
  const filled = await page.evaluate(() => {
    const subject = document.querySelector("input[name=subjectbox]");
    const scope = (subject && subject.closest("[role=dialog]")) || document;
    const recipients = [...new Set([...scope.querySelectorAll("[email],[data-hovercard-id]")]
      .map((el) => el.getAttribute("email") || el.getAttribute("data-hovercard-id"))
      .filter(Boolean))];
    const editor = scope.querySelector("[role=textbox][contenteditable=true]");
    return { subject: subject ? subject.value : "", recipients, body: editor ? editor.innerText : "" };
  });
  const normalize = (value) => String(value || "").replace(/[ ‌​]/g, " ").replace(/\s+/g, " ").trim();
  const recipientOk = filled.recipients.length === 1 && filled.recipients[0].toLowerCase() === mail.to.toLowerCase();
  if (filled.subject !== mail.subject || !recipientOk || normalize(filled.body) !== normalize(mail.body)) {
    throw new Error("compose_verification_failed");
  }
  if (!submit) return { status: "draft_verified", submitted: false, email_id: audit.email_id };
  await page.keyboard.press("Meta+Enter");
  await page.waitForFunction(() => /邮件已发送|Message sent/.test(document.body.innerText), undefined, { timeout: 20000 });
  return { status: "sent_ui_confirmed", submitted: true, email_id: audit.email_id };
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
