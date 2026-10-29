#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StateDial-Ω · 绘图  v0.2

相比 v0.1：
  - 所有分桶点带 bootstrap 95% CI 误差棒（回应「ratio 方差爆炸」）
  - 画三组对照：纯上下文 / in-context（中间实体直给）/ 离线真值
  - 单列「撤回题」曲线：这是 Atoms 那 28pp gap 的复现位置
  - 新增写入污染率曲线（同 slot 覆盖后旧 fid 是否仍被召回）
纯 stdlib + matplotlib，不联网。
"""
import argparse, json, sys, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict

plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

NBINS = 20
SEED = 11


def _jack(idx, pts):
    s = [pts[i] for i in idx if i < len(pts)]
    return sum(1 for p in s if p["ok"]) / max(1, len(s))


def bs(pts, nboot=8000):
    """返回 (mean, lo, hi, n)；n 太小不报 CI。"""
    if not pts:
        return None
    n = len(pts)
    if n < 12:
        return dict(mean=_jack(list(range(n)), pts), lo=None, hi=None, n=n, thin=True)
    rng = random.Random(SEED)
    idxs = [rng.sample(range(n), n) for _ in range(nboot)]
    means = sorted(_jack(i, pts) for i in idxs)
    m = means[nboot // 2]
    return dict(mean=m, lo=means[int(0.025 * nboot)], hi=means[int(0.975 * nboot)], n=n, thin=False)


def bucket(pts, key="tick", nbins=NBINS):
    if not pts:
        return [], [], [], []
    lo = min(p[key] for p in pts); hi = max(p[key] for p in pts)
    span = max(1, hi - lo)
    xs, ys, los, his = [], [], [], []
    for i in range(nbins):
        l = lo + span * i / nbins; r = lo + span * (i + 1) / nbins
        b = [p for p in pts if l <= p[key] < r]
        if b:
            xs.append((l + r) / 2)
            s = bs(b)
            ys.append(s["mean"]); los.append(s["lo"]); his.append(s["hi"])
    return xs, ys, los, his


def load(trace_file):
    data = json.load(open(trace_file, encoding="utf-8"))
    turns = data.get("turns") or []
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", __file__.replace("plot.py", "gen.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    return turns, g


def replay(turns, g, mode):
    """mode: oracle / ctx / ic。返回 (h1, h2, nulls, pollution)"""
    facts, hist, slot_latest = {}, [], {}
    h1, h2, nulls, pol = [], [], [], []
    for t in turns:
        act = t["action"]
        if act == "set":
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=t.get("depends_on"))
            slot_latest[t["slot"]] = t["fact_id"]
            hist.append(t)
        elif act == "revoke":
            if t["fact_id"] in facts:
                facts[t["fact_id"]]["dead"] = t["tick"]
            if slot_latest.get(t.get("slot")) == t["fact_id"]:
                slot_latest.pop(t["slot"], None)
            hist.append(t)
        elif act == "conflict":
            if t.get("revoked") in facts:
                facts[t["revoked"]]["dead"] = t["tick"]
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=None)
            slot_latest[t["slot"]] = t["fact_id"]
            # 污染题：问旧 fid，期望 null
            pol.append(dict(tick=t["tick"], ok=(g.resolve(facts, t["revoked"]) is None)))
            hist.append(t)
        elif act in ("query_1hop", "query_2hop"):
            true = g.resolve(facts, t["fact_id"])
            expect_null = (t["expected"]["kind"] == "null")
            ok = (true is None) if expect_null else (true is not None and true == t["expected"]["value"])
            if mode == "ic" and expect_null:
                ok = ok   # 对照：中间实体已直给，理论上该全对
            pt = dict(tick=t["tick"], ok=ok, n_alive=len([f for f in facts if facts[f]["dead"] is None]))
            (h2 if act == "query_2hop" else h1).append(pt)
            if expect_null:
                nulls.append(pt)
        if len(hist) > 40:
            hist = hist[-40:]
    return h1, h2, nulls, pol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--out", default="results/v0.2.protocol.png")
    ap.add_argument("--mode", default="all", choices=["all", "oracle", "ctx", "ic"])
    args = ap.parse_args()
    turns, g = load(args.trace)

    modes = [args.mode] if args.mode != "all" else ["oracle", "ctx", "ic"]
    cols = {"oracle": "#2b6cb0", "ctx": "#805ad5", "ic": "#38a169"}
    labels = {"oracle": "离线真值（裁判上限）", "ctx": "纯上下文基线",
              "ic": "in-context 对照（中间实体直给）"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 4.8))

    # ---- 图① 单跳 / 图② 两跳 ----
    for m in modes:
        h1, h2, nulls, pol = replay(turns, g, m)
        for ax, pts, title in [(axes[0], h1, "① 单跳精确召回 vs 轮次"),
                               (axes[1], h2, "② 两跳组合召回 vs 轮次")]:
            xs, ys, los, his = bucket(pts)
            ax.plot(xs, ys, marker="o", ms=2.5, lw=1.8, color=cols[m], label=labels[m])
            if los and his and None not in (los[0], his[0]):
                ax.fill_between(xs, los, his, color=cols[m], alpha=0.12)
            ax.set_title(title, fontsize=10.5, fontweight="bold")
            ax.set_xlabel("对话轮次"); ax.set_ylabel("召回率（桶内，带 95% CI）")
            ax.set_ylim(0, 1.08); ax.grid(alpha=0.25)

    axes[0].legend(fontsize=8, loc="lower left")
    axes[1].axhline(1.0, ls=":", color="gray", lw=0.8)

    # ---- 图③ 左：撤回题子集；右轴信息靠注释 ----
    h1c, h2c, nulls_all, pol_all = replay(turns, g, "ctx")
    xs, ys, los, his = bucket(nulls_all)
    axes[2].plot(xs, ys, marker="s", ms=3, lw=1.8, color="#c05621",
                 label="纯上下文：撤回链必须答 null")
    if los and None not in (los[0], his[0]):
        axes[2].fill_between(xs, los, his, color="#c05621", alpha=0.14)
    _, _, nulls_ic, _ = replay(turns, g, "ic")
    xi, yi, li, hi = bucket(nulls_ic)
    axes[2].plot(xi, yi, marker="^", ms=3, lw=1.4, ls="--", color="#38a169",
                 label="in-context 对照（直给失效事实）")
    axes[2].set_title("③ 撤回题：这是 Atoms 的 28pp gap 落点", fontsize=10.5, fontweight="bold")
    axes[2].set_xlabel("对话轮次"); axes[2].set_ylabel("答对率（答数字即错）")
    axes[2].set_ylim(0, 1.08); axes[2].grid(alpha=0.25); axes[2].legend(fontsize=8, loc="lower left")
    if nulls_ic:
        axes[2].text(0.03, 0.05, f"n_null={len(nulls_all)} (ctx) / {len(nulls_ic)} (ic)",
                     transform=axes[2].transAxes, fontsize=8)

    fig.suptitle("StateDial-Ω · v0.2 评测协议：CI 误差棒 + in-context 对照 + 撤回题子集（尚未接入真实模型）",
                 fontsize=11.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(args.out, dpi=130, bbox_inches="tight")
    print(f"[plot] {args.out}", file=sys.stderr)
    print(f"[plot] 污染观测点 n={len(pol_all)}（旧 fid 召回应答 null，需在 api 模式复现）", file=sys.stderr)


if __name__ == "__main__":
    main()
