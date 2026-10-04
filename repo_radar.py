#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repo_radar.py - GitHub 项目雷达

从"你关心的问题"出发，批量搜索 GitHub 仓库，并按「维护活跃度」打分排序，
而不是按 star 数。输出一张可直接判断"能不能用"的清单。

设计原则
--------
1. 零第三方依赖，只用 Python 标准库（你本机 Python 3.13 直接可跑）
2. 匿名调用 GitHub REST API，无需 gh 登录、无需 token（有 token 更好，见下）
3. 核心输出是「活跃度评分」，star 只作为弱权重参考

用法
----
    # 用内置的备品备件/预测性维护关键词组合跑一遍
    python repo_radar.py

    # 自定义查询
    python repo_radar.py -q "predictive maintenance" -q "inventory forecast" --language python

    # 只要商用友好的许可证
    python repo_radar.py -q "anomaly detection" --license apache-2.0,mit

    # 输出 JSON（给别的程序消费）
    python repo_radar.py -q "time series" --json out.json

提高速率上限（推荐）
--------------------
未认证时 GitHub 限制 搜索 10 次/分钟、核心 60 次/小时。
去 https://github.com/settings/tokens 生成一个 Classic token（只勾 public_repo 即可，
本次只用公开数据），然后：

    set GITHUB_TOKEN=ghp_xxxx        (Windows cmd)
    $env:GITHUB_TOKEN="ghp_xxxx"     (PowerShell)
    export GITHUB_TOKEN=ghp_xxxx     (Git Bash / macOS / Linux)

有 token 后搜索提到 30 次/分钟、核心 5000 次/小时。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
UA = "repo-radar/1.0 (+https://github.com)"

# ---------------------------------------------------------------- 内置关键词
# 面向「半导体制造 / 备品备件 / 设备健康」场景
DEFAULT_QUERIES = [
    "predictive maintenance",
    "inventory forecast",
    "spare parts optimization",
    "equipment health monitoring",
    "manufacturing time series",
]

# 商用友好许可证（工业项目基本要求）
FRIENDLY_LICENSES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause",
    "isc", "mpl-2.0", "lgpl-3.0", "unlicense", "cc0-1.0",
}

# 明确不适合闭源商用的（会显著降分并提示）
COPYLEFT_LICENSES = {"gpl-3.0", "gpl-2.0", "agpl-3.0"}


# ---------------------------------------------------------------- HTTP 基础
def _request(url: str, token: str | None, retries: int = 3) -> tuple[object, dict]:
    """发一个 GET，返回 (json, headers)。处理限流与退避重试。"""
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
                return json.loads(body), dict(resp.headers)
        except urllib.error.HTTPError as e:
            hdrs = dict(e.headers or {})
            if e.code == 403 and "rate limit" in (e.reason or "").lower():
                reset = hdrs.get("X-RateLimit-Reset")
                wait = max(1, int(reset) - int(time.time()) + 1) if reset else 60
                wait = min(wait, 65)
                print(f"    [限流] 等待 {wait}s 后重试…", file=sys.stderr)
                time.sleep(wait)
                last_err = e
                continue
            if e.code == 422:
                # 查询语法问题，别重试
                raise
            last_err = e
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"请求失败: {url} -> {last_err}")


def search_repos(query: str, token: str | None, per_page: int = 30,
                 language: str | None = None, licenses: list[str] | None = None,
                 min_stars: int = 50, pushed_after: str | None = None) -> list[dict]:
    """搜索仓库。把过滤条件下推到 GitHub 侧，减少无效结果。"""
    parts = [query.strip()]
    if language:
        parts.append(f"language:{language}")
    if min_stars:
        parts.append(f"stars:>={min_stars}")
    if pushed_after:
        parts.append(f"pushed:>{pushed_after}")
    for lic in licenses or []:
        parts.append(f"license:{lic}")
    q = " ".join(parts)

    url = f"{API}/search/repositories?" + urllib.parse.urlencode({
        "q": q, "sort": "stars", "order": "desc", "per_page": per_page,
    })
    data, _ = _request(url, token)
    items = data.get("items", []) if isinstance(data, dict) else []
    return items


def get_contributor_count(full_name: str, token: str | None) -> int | None:
    """取贡献者数量。只读第 1 页，够判断"是否单人项目"。"""
    url = f"{API}/repos/{full_name}/contributors?per_page=100&anon=false"
    try:
        data, _ = _request(url, token)
        if isinstance(data, list):
            return len(data)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- 打分
def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def score_repo(repo: dict, contributors: int | None) -> dict:
    """核心逻辑：按维护活跃度打 0-100 分，star 只占很小权重。"""
    now = datetime.now(timezone.utc)
    reasons: list[str] = []
    warnings: list[str] = []
    score = 0.0

    pushed = parse_dt(repo.get("pushed_at"))
    created = parse_dt(repo.get("created_at"))

    # --- 1. 最近提交活跃度（最高权重 40 分）---------------
    # 停滞超过一年的项目，无论其他指标多好，总分不得进入"可用"区间
    stalled_hard = False
    if pushed:
        days = (now - pushed).days
        if days <= 7:
            score += 40; reasons.append("7 天内活跃提交")
        elif days <= 30:
            score += 34; reasons.append(f"{days} 天内有提交")
        elif days <= 90:
            score += 26; reasons.append("3 个月内有提交")
        elif days <= 180:
            score += 16; reasons.append(f"{days} 天前提交过")
        elif days <= 365:
            score += 6; warnings.append(f"已 {days} 天无提交，维护放缓")
        else:
            score += 0
            stalled_hard = True
            warnings.append(f"⚠ 超过一年无提交（{days} 天），项目已停滞")
    else:
        warnings.append("⚠ 无 pushed_at 数据")
        stalled_hard = True

    # --- 2. 贡献者数量（20 分）---------------------------
    if contributors is None:
        score += 8; warnings.append("贡献者数未知")
    elif contributors >= 20:
        score += 20; reasons.append(f"{contributors}+ 贡献者，社区健康")
    elif contributors >= 8:
        score += 16; reasons.append(f"{contributors} 名贡献者")
    elif contributors >= 3:
        score += 10; reasons.append(f"{contributors} 名贡献者")
    elif contributors >= 2:
        score += 5; warnings.append("仅 2 名贡献者，抗风险弱")
    else:
        score += 0; warnings.append("⚠ 单人项目，维护者离开即停更")

    # --- 3. issue 处理情况（20 分）-----------------------
    open_i = repo.get("open_issues_count", 0)
    stars = repo.get("stargazers_count", 0)
    if stars > 0:
        ratio = open_i / max(stars, 1)
        if ratio < 0.02:
            score += 20; reasons.append("issue 积压极少")
        elif ratio < 0.05:
            score += 15; reasons.append("issue 积压可控")
        elif ratio < 0.15:
            score += 8
        else:
            score += 0
        if open_i > 1000:
            warnings.append(f"⚠ {open_i} 个未关 issue，响应能力存疑")
    else:
        score += 10

    # --- 4. 许可证商用友好度（20 分）---------------------
    lic = (repo.get("license") or {}).get("spdx_id") or ""
    lic_l = lic.lower()
    copyright_risk = False
    if lic_l in FRIENDLY_LICENSES:
        score += 20; reasons.append(f"许可证 {lic}，商用友好")
    elif lic_l in COPYLEFT_LICENSES:
        # 传染性许可证对闭源商用是硬伤，必须显著降分而不是加点警示词
        score += 0
        copyright_risk = True
        warnings.append(f"⚠ 许可证 {lic} 有传染性（copyleft），闭源商用需法务评估")
    elif not lic or lic_l in ("noassertion", "other"):
        score += 2
        copyright_risk = True
        warnings.append("⚠ 未声明许可证，商用存在法律风险")
    else:
        score += 12; reasons.append(f"许可证 {lic}")

    # --- 5. 社区规模（弱权重，最多 10 分）----------------
    if stars >= 10000:
        score += 10; reasons.append(f"{stars} star")
    elif stars >= 3000:
        score += 8; reasons.append(f"{stars} star")
    elif stars >= 1000:
        score += 6
    elif stars >= 300:
        score += 4
    elif stars >= 100:
        score += 2

    # --- 6. 项目成熟度：存在时间（bonus 最多 10）---------
    if created:
        age_days = (now - created).days
        if age_days > 1095:
            score += 10; reasons.append("沉淀 3 年以上")
        elif age_days > 730:
            score += 7; reasons.append("沉淀 2 年以上")
        elif age_days > 365:
            score += 5
        elif age_days < 90:
            score += 0; warnings.append("新项目（<3 个月），API 可能不稳")

    # --- 7. 硬性封顶（这些是"一票否决"级别的信号）--------
    if repo.get("archived"):
        warnings.append("⚠⚠ 仓库已归档（只读），不可用于新项目")
        score = min(score, 15)
    elif stalled_hard:
        # 停滞一年以上：即便 star 再高、社区再大，也不给"可用"的错觉
        score = min(score, 42)
    if copyright_risk:
        score = min(score, 72)

    return {
        "score": round(min(score, 100.0), 1),
        "reasons": reasons,
        "warnings": warnings,
        "days_since_push": (datetime.now(timezone.utc) - pushed).days if pushed else None,
    }


def grade(score: float) -> str:
    if score >= 80:
        return "强烈推荐"
    if score >= 65:
        return "可以用"
    if score >= 45:
        return "谨慎评估"
    return "不建议"


# ---------------------------------------------------------------- 输出
def fmt_int(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def render_table(rows: list[dict], show_warnings: bool = True) -> str:
    if not rows:
        return "（无结果）"

    lines: list[str] = []
    for i, r in enumerate(rows, 1):
        repo = r["repo"]
        s = r["analysis"]
        name = repo["full_name"]
        lines.append(f"{i:>2}. [{s['score']:>5}] {grade(s['score'])}  {name}")
        lines.append(
            f"     ★{fmt_int(repo.get('stargazers_count'))}  "
            f"fork {fmt_int(repo.get('forks_count'))}  "
            f"issue {fmt_int(repo.get('open_issues_count'))}开放  "
            f"贡献者 {r.get('contributors') or '?'}  "
            f"最近提交 {s['days_since_push']}天前"
        )
        desc = (repo.get("description") or "").strip()
        if desc:
            lines.append(f"     {desc[:110]}")
        lic = (repo.get("license") or {}).get("spdx_id") or "无"
        lines.append(f"     语言 {repo.get('language') or '?'}   许可证 {lic}   {repo['html_url']}")
        if s["reasons"]:
            lines.append(f"     + {' / '.join(s['reasons'][:4])}")
        if show_warnings and s["warnings"]:
            lines.append(f"     ! {' / '.join(s['warnings'][:3])}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(
        description="GitHub 项目雷达 —— 按维护活跃度找可用仓库，而不是按 star",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-q", "--query", action="append", dest="queries",
                    help="搜索关键词，可重复传入")
    ap.add_argument("--language", help="限定语言，如 python / java")
    ap.add_argument("--license", help="限定许可证，逗号分隔，如 apache-2.0,mit")
    ap.add_argument("--min-stars", type=int, default=50, help="star 下限，默认 50")
    ap.add_argument("--pushed-after", default=None,
                    help="只看此日期后推送过的，如 2026-01-01")
    ap.add_argument("--per-page", type=int, default=15, help="每个关键词取多少条，默认 15")
    ap.add_argument("--top", type=int, default=20, help="最终展示前多少条，默认 20")
    ap.add_argument("--json", dest="json_out", help="另存 JSON 到指定文件")
    ap.add_argument("--no-contributors", action="store_true",
                    help="跳过贡献者查询（省 API 配额，但评分精度下降）")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    queries = args.queries or DEFAULT_QUERIES
    licenses = [x.strip() for x in args.license.split(",")] if args.license else None

    print("=" * 72)
    print("  GitHub 项目雷达")
    print("=" * 72)
    print(f"  关键词   : {len(queries)} 组")
    for q in queries:
        print(f"             - {q}")
    print(f"  语言     : {args.language or '不限'}")
    print(f"  许可证   : {args.license or '不限（会标注商用风险）'}")
    print(f"  star下限 : {args.min_stars}")
    print(f"  推送时间 : {args.pushed_after or '不限'}")
    print(f"  认证     : {'已配置 token' if token else '匿名（速率受限，建议设 GITHUB_TOKEN）'}")
    print("=" * 72)
    print()

    seen: dict[str, dict] = {}
    for q in queries:
        print(f"[搜索] {q}"
              + (f"  (语言={args.language})" if args.language else ""))
        try:
            items = search_repos(q, token, per_page=args.per_page,
                                 language=args.language, licenses=licenses,
                                 min_stars=args.min_stars,
                                 pushed_after=args.pushed_after)
        except Exception as e:
            print(f"   跳过：{e}", file=sys.stderr)
            continue
        print(f"   命中 {len(items)} 条")
        for it in items:
            fn = it.get("full_name")
            if fn and fn not in seen:
                it["_matched_query"] = q
                seen[fn] = it
        time.sleep(1)  # 搜索接口限流较紧，稍作间隔

    if not seen:
        print("\n没有结果。可能原因：关键词太窄 / 网络不通 / 触发了限流。")
        return 1

    print(f"\n[去重后] 共 {len(seen)} 个候选，开始分析…\n")

    rows: list[dict] = []
    total = len(seen)
    for idx, (fn, repo) in enumerate(seen.items(), 1):
        contributors = None
        if not args.no_contributors:
            contributors = get_contributor_count(fn, token)
            time.sleep(0.15)
        analysis = score_repo(repo, contributors)
        rows.append({"repo": repo, "analysis": analysis, "contributors": contributors})
        sys.stderr.write(f"\r  分析中 {idx}/{total} …")
    sys.stderr.write("\r" + " " * 40 + "\r")

    rows.sort(key=lambda r: r["analysis"]["score"], reverse=True)
    top = rows[: args.top]

    print("=" * 72)
    print(f"  结果（按活跃度评分排序，共 {len(rows)} 个候选，展示前 {len(top)}）")
    print("=" * 72)
    print()
    print(render_table(top))

    # 汇总提示
    fresh = [r for r in rows if (r["analysis"]["days_since_push"] or 9999) <= 90]
    risky = [r for r in rows if r["analysis"]["warnings"]]
    print("-" * 72)
    print(f"  近 90 天有提交  : {len(fresh)} / {len(rows)}")
    print(f"  带风险提示      : {len(risky)} / {len(rows)}")
    print(f"  评分 >= 80      : {sum(1 for r in rows if r['analysis']['score'] >= 80)} 个")
    print("-" * 72)
    print()
    print("提示：评分只是初筛。选定候选后务必再手动看三处：")
    print("  1. Issues 按 👍 排序，看大家实际卡在哪")
    print("  2. README 里的部署方式，是否支持内网 / 离线安装")
    print("  3. Releases 页的发版节奏")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(
                [{
                    "name": r["repo"]["full_name"],
                    "url": r["repo"]["html_url"],
                    "score": r["analysis"]["score"],
                    "grade": grade(r["analysis"]["score"]),
                    "stars": r["repo"].get("stargazers_count"),
                    "forks": r["repo"].get("forks_count"),
                    "open_issues": r["repo"].get("open_issues_count"),
                    "contributors": r.get("contributors"),
                    "days_since_push": r["analysis"]["days_since_push"],
                    "language": r["repo"].get("language"),
                    "license": (r["repo"].get("license") or {}).get("spdx_id"),
                    "description": r["repo"].get("description"),
                    "reasons": r["analysis"]["reasons"],
                    "warnings": r["analysis"]["warnings"],
                } for r in rows],
                f, ensure_ascii=False, indent=2,
            )
        print(f"\nJSON 已写入：{args.json_out}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
