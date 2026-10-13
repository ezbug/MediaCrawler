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

export async function send(payloadPath, spaceId, submit = false) {
  const packet = JSON.parse(await fs.readFile(payloadPath, 'utf8'));
  const mail = validatePacket(packet);
  const { audit } = packet;
  const task = await taskSpace(spaceId);
  const page = task.page('p1');
  if (!(await page.url()).startsWith('https://mail.google.com/')) throw new Error('gmail_page_required');
  const existing = await page.evaluate(() => document.querySelectorAll('input[name=subjectbox]').length);
  if (existing) throw new Error('existing_compose_requires_user_attention');
  await page.click('loc=role:button[name="写邮件"]');
  await page.waitForSelector('input[name=subjectbox]', { timeout: 10000 });
  await page.fill('input[name=subjectbox]', mail.subject);
  const to = 'input[aria-label*="收件人"],input[name="to"],input[peoplekit-id]';
  await page.fill(to, mail.to);
  await page.press(to, 'Enter');
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
    const recipients = [...scope.querySelectorAll('[email],[data-hovercard-id]')].map(e => e.getAttribute('email') || e.getAttribute('data-hovercard-id'));
    return { body: visible.textContent, subject: subject.value, recipients };
  }, mail);
  if (filled.body !== mail.body || filled.subject !== mail.subject || filled.recipients.length !== 1 || filled.recipients[0] !== mail.to) {
    throw new Error('compose_verification_failed');
  }
  if (!submit) return { status: 'draft_verified', submitted: false, email_id: audit.email_id };
  await page.click('loc=role:button[name*="发送"]');
  await page.waitForFunction(() => /邮件已发送|Message sent/.test(document.body.innerText), undefined, { timeout: 15000 });
  return { status: 'sent_ui_confirmed', submitted: true, email_id: audit.email_id };
}
