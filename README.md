# arXiv 每日论文速览 → 微信推送 + 网页推文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

每天自动抓取 arXiv 上 **微分几何（math.DG）、一般拓扑（math.GN）、几何拓扑（math.GT）、群论（math.GR）、度量几何（math.MG）、数论（math.NT）** 的新论文，用 **DeepSeek 生成 AI 总结与中英文摘要**，通过**微信公众号测试号**推送 **1 条汇总消息** 到你的微信，点击即可跳转到 **GitHub Pages 推文网页**（按分区列出全部论文，每篇含 AI 总结、中文摘要翻译、英文摘要原文与 arXiv 链接）。

- 完全免费（GitHub Actions 定时 + DeepSeek 日均约 0.02 元）
- 不需要服务器、不需要电脑开机
- 每天北京时间 12:30 自动推送（20:30 兜底补推，避免漏推），也可手动触发

## 效果一览

**微信收到（每天 1 条）**：
```
📚 arXiv 每日论文速览
共 128 篇 | 2026-08-24
微分几何、一般拓扑、几何拓扑、群论、度量几何、数论

微分几何：39 篇
一般拓扑：3 篇
几何拓扑：15 篇
群论：22 篇
度量几何：10 篇
数论：39 篇

📌 点击消息查看全部论文的 AI 总结、中英文摘要与 arXiv 链接
```

**点开消息 → GitHub Pages 网页**：按分区列出全部论文，每篇展开可看：
- 🤖 **AI 总结**（3-5 句：研究问题、方法、结果、意义）
- 📖 **中文摘要**（AI 翻译）
- 🌐 **English Abstract**（原文）
- 👉 **arXiv 链接**（点击直达原文）

## 目录结构

```
arxiv-daily-wechat/
├── main.py                  # 主流程：抓取 → 总结 → 生成网页 → 推送
├── arxiv_fetcher.py         # arXiv RSS 抓取（与网页实时同步，无索引延迟）
├── summarizer.py            # DeepSeek 批量生成中文标题/总结/AI总结/摘要翻译
├── page_builder.py          # 生成每日 HTML 推文页（含历史索引）
├── wechat_push.py           # 微信公众号测试号模板消息推送
├── config.example.json      # 本地配置模板（复制为 config.json 使用）
├── requirements.txt         # 依赖（仅 requests）
└── .github/workflows/daily.yml  # GitHub Actions 定时任务 + Pages 部署
```

## 一、准备工作（10 分钟）

### 1. DeepSeek API Key

1. 注册 [DeepSeek 开放平台](https://platform.deepseek.com/)（手机号即可）
2. 进入「API Keys」→ 创建一个 key，形如 `sk-xxxxxxxx`，**复制保存好**（只显示一次）
3. 充值几块钱就够用很久（每天约 0.02 元）

### 2. 微信公众号测试号（免费、个人可申请）

1. 打开 [微信测试号申请页](https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login)，用**你的微信扫码登录**
2. 登录后页面显示 **appID** 和 **appsecret**，先复制保存
3. 在「测试号二维码」区域，**用手机微信扫码关注**，你的 openid 会出现在下方「测试者」列表里，复制保存
4. 在「模板消息」→「新增测试模板」，**模板标题**填 `arXiv 每日论文速览`，**模板内容**填下面这段（字段名保持 `first`/`keyword1`/`keyword2`/`keyword3`/`remark` 不变）：
   ```
   {{first.DATA}}
   分类：{{keyword1.DATA}}
   {{keyword2.DATA}}
   {{keyword3.DATA}}
   {{remark.DATA}}
   ```
   提交后复制生成的**模板 ID**（`**` 开头）

> 💡 置顶建议：在微信里找到测试号对话（订阅号消息 → 微信测试号），右上角「···」→ **置顶聊天**，以后从微信顶部直接进入，不用每次翻找。

### 3. GitHub 账号

注册 [GitHub](https://github.com/)（免费），并安装好 [Git](https://git-scm.com/)。

## 二、部署到 GitHub Actions（20 分钟）

### 第 1 步：上传项目

在 GitHub 网页上点 **New repository** 新建一个仓库（如 `arxiv-daily-wechat`），然后在你电脑上执行：

```bash
cd "你的项目目录"
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/arxiv-daily-wechat.git
git push -u origin main
```

> 注意：`config.example.json` 不含密钥；密钥全部通过下面的 Secrets 配置，不会泄露到仓库。

### 第 2 步：配置密钥（Secrets）

仓库 → **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名称 | 填什么 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 的 key（sk- 开头） |
| `WECHAT_APP_ID` | 测试号 appID |
| `WECHAT_APP_SECRET` | 测试号 appsecret |
| `WECHAT_TEMPLATE_ID` | 测试号模板 ID |
| `WECHAT_OPENID` | 你的 openid |

### 第 3 步：配置 Variables（非敏感，可选）

切到 **Variables** 标签添加（不配置则用代码默认值）：

| Variable 名称 | 默认值 | 作用 |
|---|---|---|
| `ARXIV_CATEGORIES` | `math.DG,math.GN,math.GT,math.GR,math.MG,math.NT` | 抓哪些分类 |
| `ARXIV_HOURS_BACK` | `30` | 回看最近多少小时的论文（临时想看历史可调大，如 `120`） |
| `ARXIV_MAX_PAPERS` | `200` | 详细模式单次最多推送多少篇 |
| `WECHAT_MODE` | `digest` | `digest`=每天 1 条汇总；`detailed`=每篇 1 条含中英文摘要 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 使用的模型 |

### 第 4 步：启用 GitHub Pages（重要）

仓库 → **Settings → Pages** → **Source 选择「GitHub Actions」** → Save。

> ⚠️ 不选这项，工作流里的"部署到 Pages"步骤会失败。启用后页面会显示部署地址：`https://<用户名>.github.io/arxiv-daily-wechat/`

### 第 5 步：手动测试

仓库 → **Actions** → 左侧选 **arxiv-daily-wechat** → 点 **Run workflow**。

等 1-2 分钟跑完，日志末尾应看到：
```
[完成] 已发送 1 条消息到微信
✅ 推文页面已部署
📌 访问地址: https://jiangzhexin.github.io/arxiv-daily-wechat/
```

之后每天自动运行两次：北京时间 12:30 主推送，20:30 兜底补推（去重机制保证已推送过的论文不会重复；12:30 因故没推时 20:30 自动补上）。arXiv 新论文在北京时间凌晨 2-3 点发布，中午推送时 RSS 已更新到位。

## 三、本地运行（可选，方便调试）

```bash
cd "你的项目目录"
pip install -r requirements.txt

# 方式 A：复制配置模板并填写（config.json 已在 .gitignore 中，不会上传）
cp config.example.json config.json
python main.py --dry-run      # 先预览，不发微信
python main.py                # 正式运行（本地跑需要配置环境变量/密钥）

# 方式 B：或直接用环境变量
DEEPSEEK_API_KEY=sk-xxx WECHAT_APP_ID=wx... python main.py --dry-run
```

## 四、如何修改抓取的分区（分类）

系统默认抓取 6 个数学分区。改分区有**两种方法**，推荐方法一（不用动代码）。

### 方法一：在 GitHub Variables 里改（推荐，不用改代码）

仓库 → **Settings → Secrets and variables → Actions → Variables** → 编辑 `ARXIV_CATEGORIES`，填你要的分区代码，**逗号分隔**，例如：

```
math.DG,math.GN,math.GT,math.GR,math.MG,math.NT,math.AP
```

改完点 **Run workflow** 即可生效。

### 方法二：改代码默认值

编辑 `main.py` 顶部的 `DEFAULT_CATEGORIES`（和 `page_builder.py` 一样维护一份），提交后自动生效。

### 常用 arXiv 数学分区代码

| 代码 | 名称 | 代码 | 名称 |
|---|---|---|---|
| `math.DG` | 微分几何 | `math.GR` | 群论 |
| `math.GN` | 一般拓扑 | `math.MG` | 度量几何 |
| `math.GT` | 几何拓扑 | `math.NT` | 数论 |
| `math.AP` | 分析学 | `math.AG` | 代数几何 |
| `math.AT` | 代数拓扑 | `math.AC` | 交换代数 |
| `math.CO` | 组合数学 | `math.CV` | 复分析 |
| `math.FA` | 泛函分析 | `math.LO` | 数理逻辑 |
| `math.OA` | 算子代数 | `math.PR` | 概率论 |
| `math.RT` | 表示论 | `math.SG` | 辛几何 |
| `math.SP` | 谱理论 | `math.ST` | 统计理论 |

完整列表见 [arXiv 分类大全](https://arxiv.org/category_taxonomy)。

### ⚠️ 重要：新增分区后如何显示中文名

- 直接用方法一改变量**立刻能用**，但新分区在消息/网页里会显示**英文代码**（如 `math.AP`）。
- 想要中文名：在 `main.py` 和 `page_builder.py` 两个文件的 `CATEGORY_NAMES` 字典里各加一行，例如：
  ```python
  "math.AP": "分析学",
  ```
  提交 push 后再 Run workflow 即可。

### 其他相关设置

- `ARXIV_HOURS_BACK`：回看最近多少小时的论文（默认 30；临时想看历史可调大到 120）
- `ARXIV_MAX_PAPERS`：详细模式单次最多推送多少篇（默认 200）

## 五、常见问题

**Q1：微信收到消息但字段显示空白/错位？**
不同模板的字段名可能不同。确保模板内容用的是 `{{first.DATA}}`、`{{keyword1.DATA}}`…`{{remark.DATA}}` 这套命名；如果你自定义了字段名，把对应关系填到 `config.json` 的 `template_fields` 映射里（或改 `main.py` 的 `DEFAULT_TEMPLATE_FIELDS`）。

**Q2：发送报错 `errcode: 40001`？**
access_token 失效会自动重试；持续失败则检查 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 是否复制完整（appsecret 很长，容易漏字符）。

**Q3：为什么周末收不到论文？**
arXiv 周六、周日不发布新论文，属正常现象；周一早上也会显示"没有新论文"。

**Q4：网页根地址打不开（404）？**
确认仓库 Settings → Pages 的 Source 是「GitHub Actions」，并且工作流日志显示"✅ 推文页面已部署"；部署后等 1 分钟再访问。

**Q5：微信点开消息是空白/打不开网页？**
模板消息需要配置 url 跳转。检查 `PAGE_BASE_URL`（在 `daily.yml` 里）是否等于你的 Pages 地址 `https://<用户名>.github.io/arxiv-daily-wechat`。

**Q6：想换总结语言或模型？**
`DEEPSEEK_MODEL` 换成 `deepseek-reasoner` 等即可；提示词在 `summarizer.py` 的 `SYSTEM_PROMPT` 里改。

**Q7：历史页面怎么保留？**
每天生成的 `daily-YYYY-MM-DD.html` 会提交回仓库（工作流自动完成），网页顶部有"📅 历史速览"入口可回看。

**Q8：推送的论文数量和 arXiv 网页上对不上？**
本项目通过 **arXiv RSS 订阅源**实时抓取（与网页公告列表同步，无搜索 API 的索引延迟），并按"最近一次公告"合并去重。注意：arXiv 网页的 `recent` 页面显示的是**最近多个工作日的累计**（如某天 19 篇可能是好几天总和），而本项目每天推送的是**最近一次公告的新论文**；同时 `last_pushed.json` 会过滤掉已推送过的论文，避免重复。如果你在网页上看到多天的论文，而推送只包含当天新增，这是正常行为。

**Q9：会不会重复推送？**
不会。每次推送的论文 ID 都会记录到 `last_pushed.json`（由工作流自动提交回仓库），下次运行自动过滤掉已推送的论文。中午 12:30 推送成功后，晚上 20:30 的兜底运行会检测到"没有新论文"并自动跳过。

## 六、隐私与公开说明（重要，请 copy/fork 本项目的同学阅读）

> ⚠️ 这个项目默认是 **Public（公开）仓库 + GitHub Pages 公开网页**，请知悉以下情况：

1. **网页和页面文件是公开的**：每天生成的论文推文页（`pages/daily-*.html`）会由工作流自动提交回仓库，同时部署为公开网页。**任何人都能 clone 仓库或直接访问网页**，看到这些页面。
2. **公开的内容不含隐私**：页面内容 = arXiv 公开论文的标题 + AI 生成的总结与摘要 + arXiv 链接。这些都是全球公开的学术信息，**不包含你的任何个人信息**。
3. **你的密钥绝对安全**：DeepSeek Key、微信测试号 appID/appsecret、openid 全部存放在 GitHub **Secrets** 中（不可见、不随仓库分发），`config.json` 也被 `.gitignore` 排除——**任何方式都不会泄露**。
4. **请勿提交真实密钥**：改代码时不要把真实密钥写进源码或配置文件再 push，一律放到 Secrets。
5. **想彻底不公开怎么办**：
   - 仓库改 **Private**：他人无法 clone，但注意**免费版 GitHub 的 Private 仓库 Pages 网页需要登录才能访问**，会导致微信里点开论文网页打不开（网页推文功能失效）。
   - 去掉工作流里"提交页面回仓库"的步骤（`daily.yml` 中 `git add -f pages/` 那一段）：仓库里不再保留历史页面文件，但 **Pages 网页本身依然公开**（这是 GitHub Pages 的性质），且会失去历史回看功能。
   - 如果你 fork 后想保留历史页面但不想公开源码：可改为仅 `pages/` 目录在公开仓库、代码在私有仓库（自行调整结构）。

## 费用说明

- GitHub Actions：免费（每月 2000 分钟额度，本项目每天跑 1-2 分钟）
- DeepSeek：每天 30-130 篇论文（含 AI 总结与摘要翻译），日均成本约 **0.02-0.05 元**
- 微信公众号测试号：免费，无条数限制
- GitHub Pages：免费

## 参考与致谢

本项目在设计与实现过程中参考了以下社区项目（思路参考，代码为独立编写）：

- [AIForerunner/daily-arXiv-ai-enhanced](https://github.com/AIForerunner/daily-arXiv-ai-enhanced) —— 采用 GitHub Actions + DeepSeek 做 arXiv 每日论文抓取与 AI 总结的思路
- [dw-dengwei/daily-arXiv-ai-enhanced](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced) —— 上述项目所 fork 的原始仓库

感谢这些开源作者的分享。本项目在此基础上改为**微信公众号测试号推送 + GitHub Pages 网页推文**的形态。

## License

本项目使用 [MIT License](LICENSE) 开源，欢迎自由使用、修改和分发。
