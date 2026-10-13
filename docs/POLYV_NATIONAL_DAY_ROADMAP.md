# POLYV 国庆企业培训赛道实战

复用现有 POLYV SQLite、Ego Lite 和累计大板。ZigoAI 不参与本活动的入库、评分或完成数量。目标为 100 家真实机构名单、2 次有效业务交流、200 字以内赛道说明和 3 题复盘；目标不代表已完成。

## 五个阶段

| 阶段 | 负责人 | 产物 | 验收 |
| --- | --- | --- | --- |
| M0 明确口径 | 主代理、核验 Worker | 客户卡、入池规则、赛道说明 | 主体、场景、来源、联系入口齐全 |
| M1 核验20家 | 发现、核验 Worker | 首批客户卡、10条个性化开场 | 官方原文能复查，待核不计数量 |
| M2 扩充100家 | 主代理、发现 Worker | 每批20家、渠道产出 | 同机构只计一次；触达不等于客户回应 |
| M3 有效交流 | 主代理、对话 Worker | 双方原话、账号、时间、目标关系 | 对方有业务回应，我方有针对性跟进 |
| M4 交付复盘 | 主代理、核验 Worker | 名单、证据、三题复盘 | 数量对账；不足如实记录 |

## 客户卡规则

培训服务商可以采购视频能力，不能因发布培训服务就一律剔除。视频平台同行、渠道伙伴和培训交付方须区分。真实机构与明确培训场景即可进入适配名单，不要求每家公开询价。

`fit_score` 表示场景适配，`intent_score` 表示采购信号，二者独立。官网能访问只证明网页现状，不证明近期采购、履约能力或持续经营。发布日期未知不填采集日期代替。90天内需求优先，91–730天历史需求单列；机构持续经营与单条需求年龄分别核验。

企业去重采用明确的官方主体ID或已核实域名，不按昵称或模糊名称合并。集团多域名需经主体证据补齐同一 `company_id`，首次识别不明确的归属保留待核。

## 运行入口

```bash
uv run python -m local_tools.polyv_radar customer-campaign \
  --config local_tools/polyv_radar/pilot.toml \
  --campaign-id <campaign-id> --action init

uv run python -m local_tools.polyv_radar customer-campaign \
  --config local_tools/polyv_radar/pilot.toml \
  --campaign-id <campaign-id> --action import --input <company-cards.json>
```

数据写在配置的 `data_root/campaigns/<campaign-id>/`；原数据库增量增加活动表，不重写历史批次。幂等导出名单 JSON、CSV、HTML 和作业 Markdown。`--action exchange` 仅登记有真实双方证据的交流事件，不执行对外动作。

大板沿用 `/polyv-dashboard.html?campaign_id=<campaign-id>`，只读 API 为 `/api/radar/campaigns` 与 `/api/radar/campaigns/<campaign-id>/{summary,companies,dashboard.html}`。每5秒刷新，断线显示过期提示。服务只绑定 `127.0.0.1`。

Ego批处理入口为 `ego_company_discovery.mjs`、`ego_company_verify.mjs`，只导航和读取公开网页。用现有 TaskSpace 串行执行；输出保存真实页面、核验时间、原文和错误。验证码、证书错误、登录拦截不绕过。

## 委派与触达

主代理是唯一活动账本写入方，负责策略、合并、验收、发送及回查。发现 Worker 返回官方来源候选；核验 Worker 返回主体、场景、时效和来源证据；文案与对话 Worker 返回开场和互动分类。Worker 不同时操作浏览器或写账本。

只在当前授权范围内发送公开回复。官网联系页不等于社媒楼层；自动提交咨询表单、私信、电话及邮件不属于公开回复授权。队列必须传已核实 `--own-account`，生产回查必须匹配我方账号、完整文案和目标关系；账号未知或仅点击成功保留未核验状态，不重复发送。

有效交流要求对方有真实业务回应，且我方完成针对性跟进；“谢谢”、点赞、表情和单向发送都不计。执行阶段每日两次优先检查回复，平台拦截则保留阻塞，不把执行时间当客户响应时间。

详细复用规则见本机 `polyv-lead-auto-reply/references/national_day_customer_campaign.md`。具体批次数量、TaskSpace、名单和截图保存在仓库外，不写入永久 Skill 或 Git。
