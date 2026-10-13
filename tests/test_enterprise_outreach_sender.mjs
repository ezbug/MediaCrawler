import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { validatePacket } from '../local_tools/enterprise_data/ego_gmail_gate.mjs';

function packet() {
  const mail = { body: '正文', to: 'ir@example.com', subject: '主题' };
  const canonical_email = JSON.stringify(mail);
  return { mail, canonical_email, audit: { status: 'passed', audited_on: '2026-10-13',
    email_hash: crypto.createHash('sha256').update(canonical_email).digest('hex') } };
}

test('passed exact mail is accepted', () => assert.deepEqual(validatePacket(packet(), '2026-10-13'), packet().mail));
test('edited recipient is rejected', () => {
  const p = packet(); p.mail.to = 'other@example.com';
  assert.throws(() => validatePacket(p, '2026-10-13'));
});
test('blocked report is rejected', () => {
  const p = packet(); p.audit.status = 'blocked';
  assert.throws(() => validatePacket(p, '2026-10-13'));
});
test('expired audit is rejected', () => assert.throws(() => validatePacket(packet(), '2026-10-14')));
