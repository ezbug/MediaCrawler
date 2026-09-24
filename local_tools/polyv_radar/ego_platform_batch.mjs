import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const taskspaceId = Number(process.env.POLYV_TASKSPACE_ID);
const scriptPath = process.env.POLYV_BATCH_SCRIPT || '';
const outputRoot = process.env.POLYV_BATCH_OUTPUT_DIR || '';
const snapshotRoot = process.env.POLYV_BATCH_SNAPSHOT_DIR || '';
const resultPath = process.env.POLYV_BATCH_RESULT_PATH || '';
const maxContents = process.env.POLYV_BATCH_MAX_CONTENTS || '15';
const maxComments = process.env.POLYV_BATCH_MAX_COMMENTS || '30';

if (!Number.isInteger(taskspaceId) || taskspaceId <= 0) throw new Error('需要有效的 POLYV_TASKSPACE_ID');
if (!scriptPath || !outputRoot) throw new Error('批处理缺少采集脚本或输出目录');

const keywords = JSON.parse(process.env.POLYV_BATCH_KEYWORDS || '[]');
if (!Array.isArray(keywords) || keywords.some((item) => typeof item !== 'string' || !item.trim())) {
  throw new Error('POLYV_BATCH_KEYWORDS 必须是非空字符串数组');
}

function safeName(value) {
  return String(value).trim().replace(/[\\/:*?"<>|\n\r\t]+/g, '_').replace(/\s+/g, ' ').slice(0, 80) || '未命名';
}

async function writeSnapshot(page, destination) {
  try {
    const snapshot = await page.snapshot({ scope: 'full_page' });
    const text = typeof snapshot === 'string' ? snapshot : JSON.stringify(snapshot, null, 2);
    await fs.writeFile(destination, text || '', 'utf-8');
    return { status: 'saved', path: destination };
  } catch (error) {
    return { status: 'failed', path: '', error: String(error?.message || error).slice(0, 300) };
  }
}

async function listJsonlFiles(directory) {
  const results = [];
  async function visit(current) {
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(target);
      else if (entry.isFile() && entry.name.endsWith('.jsonl')) results.push(target);
    }
  }
  await visit(directory);
  return results;
}

async function countRows(directory, predicate) {
  let count = 0;
  for (const file of await listJsonlFiles(directory)) {
    if (!predicate(path.basename(file))) continue;
    const text = await fs.readFile(file, 'utf-8');
    count += text.split('\n').filter(Boolean).length;
  }
  return count;
}

await fs.mkdir(outputRoot, { recursive: true });
await fs.mkdir(snapshotRoot, { recursive: true });

const task = await taskSpace(taskspaceId);
const page = task.page('p1');
const tasks = [];
const originalArgv = process.argv;
const originalKeyword = process.env.KEYWORD;
const originalOutput = process.env.OUTPUT_DIR;

for (let index = 0; index < keywords.length; index += 1) {
  const keyword = keywords[index].trim();
  const slug = `${String(index + 1).padStart(2, '0')}-${safeName(keyword)}`;
  const outputDir = path.join(outputRoot, slug);
  const beforePath = path.join(snapshotRoot, `${slug}.before.txt`);
  const afterPath = path.join(snapshotRoot, `${slug}.after.txt`);
  await fs.mkdir(outputDir, { recursive: true });
  const startedAt = new Date();
  const record = {
    keyword,
    output_dir: outputDir,
    snapshot_before: '',
    snapshot_after: '',
    status: 'failed',
    error: '',
    started_at: startedAt.toISOString(),
    finished_at: '',
    duration_seconds: 0,
    raw_contents: 0,
    raw_comments: 0,
  };

  const before = await writeSnapshot(page, beforePath);
  record.snapshot_before = before.path;
  if (before.status === 'failed') record.error = `before snapshot: ${before.error}`;

  process.env.KEYWORD = keyword;
  process.env.OUTPUT_DIR = outputDir;
  process.argv = ['node', scriptPath, keyword, maxContents, maxComments, outputDir];
  process.exitCode = 0;
  try {
    const moduleUrl = `${pathToFileURL(scriptPath).href}?polyv_keyword=${encodeURIComponent(keyword)}&batch=${Date.now()}`;
    await import(moduleUrl);
    const exitCode = Number(process.exitCode || 0);
    if (exitCode !== 0) record.error = `采集脚本退出码 ${exitCode}`;
    else record.status = 'success';
  } catch (error) {
    record.error = String(error?.message || error).slice(0, 500);
  } finally {
    process.exitCode = 0;
    process.argv = originalArgv;
    if (originalKeyword === undefined) delete process.env.KEYWORD;
    else process.env.KEYWORD = originalKeyword;
    if (originalOutput === undefined) delete process.env.OUTPUT_DIR;
    else process.env.OUTPUT_DIR = originalOutput;
  }

  const after = await writeSnapshot(page, afterPath);
  record.snapshot_after = after.path;
  if (after.status === 'failed' && !record.error) record.error = `after snapshot: ${after.error}`;
  record.raw_contents = await countRows(outputDir, (name) => !name.toLowerCase().includes('comment'));
  record.raw_comments = await countRows(outputDir, (name) => name.toLowerCase().includes('comment'));
  record.finished_at = new Date().toISOString();
  record.duration_seconds = Math.max(0, (Date.parse(record.finished_at) - Date.parse(record.started_at)) / 1000);
  tasks.push(record);
}

const summary = {
  workflow_name: 'polyv-leads',
  workflow_version: '1',
  taskspace: taskspaceId,
  page: 'p1',
  tasks,
};
if (resultPath) {
  await fs.mkdir(path.dirname(resultPath), { recursive: true });
  await fs.writeFile(resultPath, JSON.stringify(summary, null, 2), 'utf-8');
}
console.log(JSON.stringify(summary, null, 2));
