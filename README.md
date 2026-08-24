# arXiv 每日论文速览 → 微信推送

每天自动抓取 arXiv 上 **微分几何（math.DG）、一般拓扑（math.GN）、几何拓扑（math.GT）** 的新论文，用 **DeepSeek 生成中文标题、一句话总结和中英文摘要**，通过**微信公众号测试号模板消息**推送到你的微信（点击消息可跳转论文原文）。

- 完全免费（GitHub Actions 定时 + DeepSeek 日均约 0.01 元）
- 不需要服务器、不需要电脑开机
- 每天北京时间 09:30 自动运行，也可手动触发

## 目录结构

```
arxiv-daily-wechat/
├── main.py                  # 主流程：抓取 → 总结 → 推送
├── arxiv_fetcher.py         # arXiv API 抓取（math.DG / math.GN / math.GT）
├── summarizer.py            # DeepSeek 批量中文总结
├── wechat_push.py           # 微信公众号测试号模板消息推送
├── config.example.json      # 本地配置模板（复制为 config.json 使用）
├── requirements.txt         # 依赖（仅 requests）
└── .github/workflows/daily.yml  # GitHub Actions 定时任务
```

## 一、准备工作（10 分钟）

### 1. DeepSeek API Key

1. 注册 [DeepSeek 开放平台](https://platform.deepseek.com/)（手机号即可）
2. 进入「API Keys」→ 创建一个 key，形如 `sk-xxxxxxxx`，**复制保存好**（只显示一次）
3. 充值几块钱就够用很久（每天约 0.01 元）

### 2. 微信公众号测试号（免费、个人可申请）

1. 打开 [微信测试号申请页](https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login)，用**你的微信扫码登录**
2. 登录后页面显示 **appID** 和 **appsecret**，先复制保存
3. 在「测试号二维码」区域，**用另一部手机（或自己再扫一次）微信扫码关注**，你的 openid 会出现在下方「测试者」列表里，复制保存
4. 在「模板消息」→「新增测试模板」，在模板库搜索并选用一个模板（推荐搜 **"新消息通知"** 或 **"信息提醒"**），点「提交」，系统会生成一个 **模板 ID**，复制保存；同时记下模板的**字段名**（通常是 `first`、`keyword1`、`keyword2`、`keyword3`、`remark`，具体以你选的模板为准）

### 3. GitHub 账号

注册 [GitHub](https://github.com/)（免费），并安装好 [Git](https://git-scm.com/)。

## 二、部署到 GitHub Actions（20 分钟）

### 第 1 步：上传项目

在 GitHub 网页上点 **New repository** 新建一个仓库（如 `arxiv-daily-wechat`），然后在你电脑上执行：

```bash
cd "D:\vscode\arxiv catch\arxiv-daily-wechat"
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/arxiv-daily-wechat.git
git push -u origin main
```

> 注意：`config.example.json` 不会包含密钥，密钥全部通过下面的 Secrets 配置，不会泄露到仓库。

### 第 2 步：配置密钥（Secrets）

进入你的仓库 → **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名称 | 填什么 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 的 key（sk- 开头） |
| `WECHAT_APP_ID` | 测试号 appID |
| `WECHAT_APP_SECRET` | 测试号 appsecret |
| `WECHAT_TEMPLATE_ID` | 测试号模板 ID |
| `WECHAT_OPENID` | 你的 openid |

再切换到 **Variables** 标签添加（非敏感配置）：

| Variable 名称 | 填什么 |
|---|---|
| `ARXIV_CATEGORIES` | `math.DG,math.GN,math.GT`（要改分类就改这里） |
| `DEEPSEEK_MODEL` | `deepseek-chat` |

### 第 3 步：手动测试

仓库 → **Actions** → 左侧选 **arxiv-daily-wechat** → 点 **Run workflow**。

等 1-2 分钟跑完，如果 Actions 日志显示 `[完成] 已发送 N 条消息到微信`，你的微信就会收到论文速览（如果当天是新论文发布日；**周末 arXiv 不发布新论文，会显示"今天没有新论文"**，属正常）。

之后每天北京时间 09:30 自动运行，无需任何操作。

## 三、本地运行（可选，方便调试）

```bash
cd "D:\vscode\arxiv catch\arxiv-daily-wechat"
pip install -r requirements.txt

# 方式 A：复制配置模板并填写（config.json 已在 .gitignore 中，不会上传）
cp config.example.json config.json
python main.py --dry-run      # 先预览，不发微信
python main.py                # 正式运行

# 方式 B：或直接用环境变量
DEEPSEEK_API_KEY=sk-xxx WECHAT_APP_ID=wx... python main.py --dry-run
```

## 四、常见问题

**Q1：收到消息但模板字段显示空白/格式不对？**
不同模板的字段名可能不同（比如不是 `keyword1` 而是 `thing1`）。把你选中的模板字段名填到 `config.json` 的 `template_fields` 映射里（或在 GitHub 上给 `main.py` 里 `DEFAULT_TEMPLATE_FIELDS` 改名）。

**Q2：发送报错 `errcode: 40001`？**
access_token 失效会自动重试；如果持续失败，检查 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 是否复制完整（appsecret 很长，容易漏）。

**Q3：为什么周末收不到论文？**
arXiv 周六、周日不宣布新论文，属于正常现象。

**Q4：论文太多会刷屏吗？**
默认单次最多推送 8 篇，每篇 1 条消息（每条含一句话总结 + 中英文摘要，可点击跳转论文原文）。想调整：改 `max_papers_per_run`（数量）和 `PAPERS_PER_MESSAGE`（每条几篇）。

**Q5：想换总结语言或模型？**
`DEEPSEEK_MODEL` 换成 `deepseek-reasoner` 等即可；提示词在 `summarizer.py` 的 `SYSTEM_PROMPT` 里改。

## 费用说明

- GitHub Actions：免费（每月 2000 分钟额度，本项目每天跑 1-2 分钟）
- DeepSeek：每天约 30-60 篇论文，输入约 3-6 万 token，日均成本约 **0.01-0.03 元**
- 微信公众号测试号：免费，无条数限制
