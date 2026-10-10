# 同行调查（Peer Research）

同行调查是雷达的第三个独立方向，与 POLYV 潜客漏斗、ZigoAI 漏斗互不相通。
调查对象是同行品牌，目标是三件事：同行查找、同行价格、宣传与私信话术。
数据来源限定为四个已部署平台（dy/xhs/bili/zhihu）的公开内容，以及用户手工
提供的自有收信材料。

## 生成查询计划

计划生成完全离线，不打开浏览器、不访问平台：

```bash
uv run python -m local_tools.polyv_radar peer-plan \
  --config local_tools/polyv_radar/pilot.toml \
  --brand 微吼 --brand 百家云 --brand 小鹅通 \
  --direction peer_pricing
```

默认展开一级优先级品牌的全平台计划；`--brand` 收窄到指定品牌，
`--all-brands` 加入二、三级品牌，`--max-queries` 限制条数。
计划写入 `polyv-radar-data/peer-research/<plan-id>.{json,md}`，
Markdown 版本按方向分组，便于人工挑选批次。

品牌与模板维护在 `peer_research_taxonomy.json`：新增同行直接改
`competitors` 数组；调整问法改 `directions.*.templates`。

## 执行采集

同行采集使用独立入口，数据写入 `polyv-radar-data/peer-research/`，
不进入 POLYV 潜客库：

```bash
uv run python -m local_tools.polyv_radar peer-collect \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <taskspace> \
  --brand 微吼 --direction peer_discovery --platform zhihu
```

也可以直接用现有采集入口复跑计划里的单条查询：

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <taskspace> \
  --platform dy --platform xhs \
  --keyword "微吼 价格" --keyword "微吼 多少钱"
```

每批建议 2～6 条查询，同平台并发保持 1，评论窗口沿用 90 天配置。
采集与结果复核统一走 Ego Lite；登录失效或出现验证码时停止对应平台。
查询较多时用 `--task-timeout-seconds` 放宽单平台批量超时（默认沿用配置的 180 秒，
12 条小红书查询会超时）。

## 三个方向的产出定义

**同行查找**：品牌 × 平台账号矩阵。每行包含账号名、认证信息、主页链接、
近期内容与发布频率、内容形态，并标注账号是否官方。

**同行价格**：价格情报表。每行包含品牌、价格数字、计价单位与周期、价格类型
（官网价/销售报价/用户成交价/传闻）、来源链接、发布日期、发布者身份。

**宣传与私信话术**：素材库。每行包含宣传原文或截图说明、触达路径
（评论/私信/电话）、话术结构、承诺点、用户反馈与反例。私信部分只收录
用户公开分享的内容或用户自有收信材料。

## 生成结构化报表

采集完成后用离线提炼生成两张表，写入 `polyv-radar-data/peer-research/reports/`：

```bash
uv run python -m local_tools.polyv_radar peer-report \
  --config local_tools/polyv_radar/pilot.toml
```

- `price-intel.csv` / `.md`：价格情报表，价格数字、分成比例、原文片段、来源链接，
  手机号与微信号自动遮蔽，价格数字保留可见。
- `promo-library.csv` / `.md`：宣传话术库，按同行自家账号、同行或媒体账号、
  测评或排行内容、用户讨论分类，并单列评论区触达话术。
  自有账号（`own_accounts.OWN_ACCOUNTS` 及保利威/POLYV）从报表中排除，
  避免把自家回复当成同行素材。

同一内容跨查询重复出现时按平台+链接去重，评论触达话术按评论 ID 去重。

## 证据标准

价格必须同时具备来源链接、发布日期和发布者身份；缺少来源的数字只标
“传闻价”，不作为结论。官网标价与销售口头报价分开记录，注意区分年费、
月费与按场计费。

官方账号必须通过平台认证或主页官方链接确认，不凭昵称判断；同名账号先记录
再核验，不跨平台合并身份。

引用用户公开分享的私信截图或转述时，保留原文链接与日期，不臆测聊天语境。

## 合规红线

- 不冒充客户或同行身份接触被调查账号；
- 不主动私信、关注、评论或点赞任何被调查账号；
- 不通过爬虫读取任何人的私信，不采集手机号、微信、邮箱等联系方式；
- 不绕过登录、验证码或平台访问限制。

## 数据隔离

同行调查使用独立目录与独立批次号（`peer-plan-*`），结果不进入 POLYV 潜客
回复队列，也不进入 ZigoAI 漏斗；反过来，潜客漏斗的身份与触达状态不参与
同行调查的账号判定。
