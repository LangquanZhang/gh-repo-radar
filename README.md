# repo_radar — GitHub 项目雷达

从**你关心的问题**出发批量搜 GitHub，按**维护活跃度**排序，而不是按 star 数。

解决的问题：GitHub 首页 Trending 有 1–2 天滞后，推的是"昨天涨得快"的项目，等你看到时红利期已过；
而 star 数本身几乎不含"这个项目现在还能不能用"的信息 —— 一个 3 万 star 的仓库可能两年没提交、issue 无人回应。

## 快速开始

需要 Python 3.9+（你本机已有 3.13）。**零第三方依赖**，只用标准库。

```bash
# 直接跑（内置了备品备件 / 预测性维护的关键词）
python repo_radar.py

# 或者双击
run.bat
```

## 提高速率上限（强烈建议）

匿名调用时 GitHub 限制**搜索接口 10 次/分钟、核心接口 60 次/小时**，跑几个关键词就会撞限流。

去 https://github.com/settings/tokens 生成一个 **Classic token**（**不需要勾任何 scope**，本工具只读公开数据）。

**token 只存一个地方**（换 token 就改这里，别处不用动）：

```
C:\Users\Lq\.config\gh-radar\token.env      <- 编辑里面的 GITHUB_TOKEN= 一行
```

`run.bat` 会自动读取该文件并注入环境变量，双击即可，不需要任何额外操作。
文件留空 = 自动退回匿名模式，不会报错。

只有**绕过 run.bat、手动敲命令行**时，才需要自己设环境变量：

```bat
:: Windows cmd
set GITHUB_TOKEN=ghp_xxxxxxxxxxxx

:: PowerShell
$env:GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

:: Git Bash / macOS / Linux
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

有 token 后：搜索 30 次/分钟、核心 5000 次/小时。

## 常用参数

```bash
# 自定义关键词（可重复传）
python repo_radar.py -q "predictive maintenance" -q "anomaly detection"

# 限定语言和许可证
python repo_radar.py -q "time series" --language python --license apache-2.0,mit

# 只要近期活跃的、star 过千的
python repo_radar.py -q "equipment health" --min-stars 1000 --pushed-after 2026-01-01

# 存成 JSON 给别的程序用
python repo_radar.py -q "inventory forecast" --json out.json

# 省 API 配额（跳过贡献者查询，评分精度略降）
python repo_radar.py --no-contributors
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `-q, --query` | 搜索关键词，可重复传入 | 内置 5 组制造/备件关键词 |
| `--language` | 限定编程语言 | 不限 |
| `--license` | 限定许可证，逗号分隔 | 不限（会标注商用风险） |
| `--min-stars` | star 下限 | 50 |
| `--pushed-after` | 只看此日期后推送过的 | 不限 |
| `--per-page` | 每个关键词取多少条 | 15 |
| `--top` | 最终展示多少条 | 20 |
| `--json` | 另存 JSON | 无 |
| `--no-contributors` | 跳过贡献者查询 | 否 |

## 评分逻辑

总分 0–100，权重按"对能否落地的影响"排序，**不是**按 star：

| 维度 | 满分 | 判断依据 |
|---|---|---|
| 提交活跃度 | 40 | 最近一次 push 距今多久 |
| 贡献者数量 | 20 | ≥20 人为 20 分，单人为 0 分 |
| issue 处理 | 20 | 未关 issue 数与 star 的比例 |
| 许可证 | 20 | MIT/Apache 得满分；GPL 得 0 分并警告 |
| 社区规模 | 10 | star 数（弱权重） |
| 项目成熟度 | 10 | 存在时长 |

**三条硬性封顶**（一票否决级信号，会强制压低总分）：

- **已归档** → 封顶 15 分。归档仓库只读，不可能用于新项目。
- **超过一年无提交** → 封顶 42 分。哪怕 3 万 star、60 个贡献者，也不给"可用"的错觉。
- **许可证有风险**（copyleft 或未声明）→ 封顶 72 分。工业闭源项目踩 GPL 是法律风险，不能淹没在总分里。

评级：`≥80 强烈推荐` / `≥65 可以用` / `≥45 谨慎评估` / `<45 不建议`

## 自检

改了评分逻辑后，跑一遍离线自检确认没跑偏：

```bash
python self_test.py     # 评分逻辑单测，7 个场景 + 3 项边界检查
python e2e_test.py      # 端到端流程 + 输出渲染（不联网，用构造数据）
```

## 重要提醒

**评分只是初筛，不能替代人工判断。** 选定候选后务必再看三处：

1. **Issues 页按 👍 排序** —— 排最前的就是最多人踩的坑，比 README 诚实
2. **README 的部署方式** —— 是否支持内网 / 离线安装（工业场景硬需求）
3. **Releases 页的发版节奏** —— 两年没发版的别用于生产

另外建议顺手看一眼 `dependents`（依赖者列表），那是找同生态优质项目的捷径：

```bash
gh api repos/<owner>/<repo>/dependents --paginate
```
