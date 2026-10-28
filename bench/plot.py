#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StateDial-Ω · 绘图  v0.1  （纯 stdlib + matplotlib）"""
import argparse, json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict

plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def bucket(points, key="tick", nbins=20):
    if not points:
        return [], []
    lo, hi = min(p[key] for p in points), max(p[key] for p in points)
    span = max(1, hi - lo)
    out_x, out_y = [], []
    for i in range(nbins):
        l = lo + span * i / nbins
        r = lo + span * (i + 1) / nbins
        bucket = [p for p in points if l <= p[key] < r]
        if bucket:
            out_x.append((l + r) / 2)
            out_y.append(sum(1 for p in bucket if p["ok"]) / len(bucket))
    return out_x, out_y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", help="gen.py 输出（含 turns）或 eval 结果 json")
    ap.add_argument("--out", default="results/demo.png")
    ap.add_argument("--nbins", type=int, default=20)
    args = ap.parse_args()

    data = json.load(open(args.trace, encoding="utf-8"))
    turns = data.get("turns") or data.get("turns")  # 兼容
    # 离线重算 ok（与 eval.py 同一裁判）
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", __file__.replace("plot.py", "gen.py"))
    gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)

    facts, h1, h2 = {}, [], []
    for t in turns:
        if t["action"] == "set":
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=t.get("depends_on"))
        elif t["action"] == "revoke" and t["fact_id"] in facts:
            facts[t["fact_id"]]["dead"] = t["tick"]
        elif t["action"] == "conflict":
            if t.get("revoked") in facts:
                facts[t["revoked"]]["dead"] = t["tick"]
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=None)
        elif t["action"] == "query_1hop":
            true = gen.resolve(facts, t["fact_id"])
            h1.append(dict(tick=t["tick"], ok=(true is not None and true == t["expected"]["value"])))
        elif t["action"] == "query_2hop":
            true = gen.resolve(facts, t["fact_id"])
            h2.append(dict(tick=t["tick"], ok=(true is not None and true == t["expected"]["value"])))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))

    for ax, pts, title, color in [(ax1, h1, "① 单跳精确召回 vs 轮次", "#2b6cb0"),
                                  (ax2, h2, "② 两跳组合召回 vs 轮次", "#c05621")]:
        x, y = bucket(pts, nbins=args.nbins)
        ax.plot(x, y, marker="o", ms=3, lw=1.8, color=color)
        ax.axhline(1.0, ls=":", color="gray", lw=0.8)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_xlabel("对话轮次")
        ax.set_ylabel("召回率（该桶内）")
        ax.set_ylim(0, 1.08)
        ax.grid(alpha=0.25)
        ax.text(0.03, 0.05, f"n={len(pts)}  queries", transform=ax.transAxes, fontsize=8)

    fig.suptitle("StateDial-Ω · 纯上下文基线：离线条目数增长下的召回（离线真值裁判，v0.1）",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(args.out, dpi=130, bbox_inches="tight")
    print(f"[plot] {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
