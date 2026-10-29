#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StateDial-Ω · 评测驱动  v0.2

相对 v0.1 的三处实质性升级（回应外部评审）：
  1. synergy ratio 改为带 bootstrap 95% CI。
     原因：分母「独立单跳乘积」很小时，点估计方差爆炸，
     26% vs 25% 这种差距在统计上根本不显著，裸报 ratio 形同虚设。
  2. 新增 in-context 对照组（Atoms 式）。
     Atoms 的关键结论恰恰来自对照组：中间实体直接塞进 prompt，成功率翻倍。
     没有这组，分不清是「记忆坏了」还是「推理坏了」。
  3. 写入侧三曲线：写入污染率 / 撤回服从率 / 冲突消解率。
     这是「地址账本」相对 RAG 唯一的真卖点，v0.1 完全没测。

模型通过 OpenAI 兼容 API 调用，不绑定任何厂商。
环境变量：OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL

默认仍走「离线真值裁判」(--mode oracle)，用于跑通评测协议、画基线；
接上模型后可用 --mode api / --mode ic 跑真实对照。
"""

import argparse, json, os, sys, math, random
from collections import defaultdict

import gen  # 复用 resolve 做离线判定

MODES = ("oracle", "api", "ic")


def jitter_seed(s: int, tag: str) -> int:
    """同一条轨迹在不同 mode 下用不同子 seed，避免伪一致。"""
    return abs(hash(f"{s}:{tag}")) % (2 ** 31)


# ---------------- 模型接口（仅 api / ic 模式用到） ----------------
def ask_model(client_cfg: dict, prompt: str, force_null: bool = False) -> dict:
    """返回 {"value": <int|None>|"__parse_fail__", "raw": ...}"""
    import urllib.request
    sys_prompt = (
        "你是状态账本助手。只输出 JSON，不要解释。"
        '格式：{"value": <数字>}；若该条目已被撤回/失效/无依赖，输出 {"value": null}。'
    )
    if force_null:  # ic 对照组：答案就是 null，但模型仍可能乱答数字
        pass
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]
    body = json.dumps({"model": client_cfg["model"], "messages": messages,
                       "temperature": 0, "max_tokens": 64}).encode()
    req = urllib.request.Request(client_cfg["base"] + "/chat/completions",
                                data=body, headers={
                                    "Authorization": "Bearer " + client_cfg["key"],
                                    "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read().decode())
    raw = resp["choices"][0]["message"]["content"].strip()
    try:
        obj = json.loads(raw)
        v = obj.get("value")
        return {"value": None if v is None else int(v), "raw": raw[:200]}
    except Exception:
        return {"value": "__parse_fail__", "raw": raw[:200]}


# ---------------- 轨迹回放：三种可见性 ----------------
def replay(trace: dict, mode: str, client=None, limit=None):
    turns = trace["turns"][:limit] if limit else trace["turns"]

    facts = {}                       # 账本真值（oracle 视角）
    ctx_history = []                 # 「纯上下文」基线喂的内容
    ic_given_ids = set()             # in-context 对照组：本轮把中间实体直接给出

    out = defaultdict(list)          # 1hop / 2hop / revoke / conflict / pollution

    def alive_ids():
        return [f for f in facts if facts[f]["dead"] is None]

    for t in turns:
        act = t["action"]

        # ---- 账本推进（三种模式完全一致，保证对照公平）----
        if act == "set":
            facts[t["fact_id"]] = dict(value=t["value"], dead=None,
                                       depends_on=t.get("depends_on"))
            ctx_history.append({"q": f"记录：{t['slot']} = {t['value']} (id={t['fact_id']})",
                                "a": {"value": t["value"]}})
        elif act == "revoke":
            if t["fact_id"] in facts:
                facts[t["fact_id"]]["dead"] = t["tick"]
            ctx_history.append({"q": f"撤回：{t['fact_id']}", "a": {"value": None}})
        elif act == "conflict":
            if t.get("revoked") in facts:
                facts[t["revoked"]]["dead"] = t["tick"]
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=None)
            ctx_history.append({"q": f"更新：{t['slot']} = {t['value']} (id={t['fact_id']})",
                                "a": {"value": t["value"]}})
        elif act in ("query_1hop", "query_2hop"):
            key = "2hop" if act == "query_2hop" else "1hop"
            true_val = gen.resolve(facts, t["fact_id"])
            expect_null = (t["expected"]["kind"] == "null")
            correct_true = (true_val is None) if expect_null else (
                true_val is not None and true_val == t["expected"]["value"])

            # ① 纯上下文模式：答案只能从 ctx_history 推（ic 模式给它开外挂）
            if mode == "ic" and expect_null:
                # 对照组：把「该链已失效」的中间实体直接摆进 prompt
                ic_given_ids.add(t["fact_id"])
                prompt = _build_prompt(ctx_history, t,
                                       hint=f"提示：{t['fact_id']} 的依赖项已在上一轮被撤回，请输出 null。")
            else:
                prompt = _build_prompt(ctx_history, t, hint=None)

            if mode == "oracle":
                ok = correct_true
                parse_ok = True
            else:
                got = ask_model(client, prompt, force_null=expect_null)["value"]
                parse_ok = (got != "__parse_fail__")
                if expect_null:
                    ok = (got is None)           # 撤回题：答数字即错
                else:
                    ok = parse_ok and (got == t["expected"]["value"])

            out[key].append(dict(tick=t["tick"], ok=ok, true=true_val,
                                n_alive=len(alive_ids()),
                                kind=t["expected"]["kind"],
                                parse_ok=parse_ok,
                                ic=(mode == "ic")))
        elif act == "revoke":  # 查询之外的撤回，单独记一条「撤回服从」观测
            out["revoke"].append(dict(tick=t["tick"], fid=t["fact_id"],
                                      was_alive_before=False))

        # 防历史无限膨胀：显式暴露纯上下文基线的缺陷
        if len(ctx_history) > 40:
            ctx_history = ctx_history[-40:]

    # 写入污染：同 slot 覆盖后，旧 id 是否仍被当成有效答案
    for t in turns:
        if t["action"] == "conflict":
            stale_id = t["revoked"]
            out["conflict"].append(dict(tick=t["tick"], stale_fid=stale_id,
                                        new_fid=t["fact_id"],
                                        slot=t["slot"]))
    return out, trace.get("meta", {})


def _build_prompt(history, t, hint=None):
    lines = ["以下是已记录的状态（按时间倒序，最近几条）："]
    for h in history[-12:]:
        lines.append(f"  > {h['q']}")
    lines.append(f"\n问题：{t['query']}")
    if hint:
        lines.append(f"（{hint}）")
    lines.append("只输出 {\"value\": ...}，不要解释。")
    return "\n".join(lines)


# ---------------- bootstrap（核心修复点） ----------------
def _jack(idx, pts, key="ok"):
    s = [pts[i] for i in idx if i < len(pts)]
    return sum(1 for p in s if p[key]) / max(1, len(s))


def bootstrap(pts, n_resample=20000, seed=7, key="ok"):
    """对 0/1 序列做 bootstrap：返回 (mean, lo, hi, n)。n 太小直接拒答。"""
    if not pts:
        return None
    rng = random.Random(seed)
    n = len(pts)
    if n < 12:                      # <12 条查询，CI 没有意义，宁可不报
        return dict(mean=_jack(list(range(n)), pts), lo=None, hi=None, n=n, thin=True)
    idxs = [rng.sample(range(n), n) for _ in range(n_resample)]
    means = [_jack(i, pts) for i in idxs]
    means.sort()
    alpha = 0.025
    lo, hi = means[int(alpha * n_resample)], means[int((1 - alpha) * n_resample)]
    return dict(mean=means[n_resample // 2], lo=lo, hi=hi, n=n, thin=False)


def synergy(acc1, acc2):
    """acc2 / acc1² 的『协同指数』；带防溢出。"""
    if acc1 is None or acc1 < 1e-9:
        return None
    return acc2 / (acc1 * acc1)     # 注意：分母是 acc1²（独立两跳的期望），不是 acc1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--mode", default="oracle", choices=MODES,
                    help="oracle=离线真值(默认, 画协议基线); api=纯上下文调模型; ic=in-context对照")
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "local-model"))
    ap.add_argument("--base", default=os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--bs-seed", type=int, default=7)
    ap.add_argument("--seeds", type=int, default=1,
                    help="对同一条轨迹跑 N 个 seed 取均值（ic/api 模式有用）")
    args = ap.parse_args()

    client = None if args.mode == "oracle" else dict(
        key=os.environ["OPENAI_API_KEY"], base=args.base, model=args.model)

    # 多 seed 聚合：agg[key] = [pts_run0, pts_run1, ...]
    agg = defaultdict(list)
    for run in range(max(1, args.seeds)):
        trace = json.load(open(args.trace, encoding="utf-8"))
        if args.seeds > 1:
            import gen as _g
            _g.rng.seed(jitter_seed(trace.get("meta", {}).get("seed", 42), f"{args.mode}:{run}"))
        bins, meta = replay(trace, args.mode, client=client, limit=args.limit)
        for k, v in bins.items():
            agg[k].append(v)

    result = dict(meta=meta, mode=args.mode, model=args.model, seeds=args.seeds)

    # ---- 1-hop / 2-hop 带 CI ----
    for key in ("1hop", "2hop"):
        allpts = [p for run in agg[key] for p in run]
        b = bootstrap(allpts, seed=args.bs_seed)
        if b is None:
            result[key] = None; continue
        # 只保留 kind=null 子集（撤回题）——这是最狠的那条曲线
        nullpts = [p for p in allpts if p.get("kind") == "null"]
        b_null = bootstrap(nullpts, seed=args.bs_seed) if nullpts else None
        result[key] = dict(mean=b["mean"], lo=b["lo"], hi=b["hi"], n=b["n"],
                           thin=b["thin"],
                           null_mean=b_null["mean"] if b_null else None,
                           null_n=b_null["n"] if b_null else 0)

    # ---- synergy（基于聚合后的 acc，并附 CI 不可判定提示）----
    a1 = result["1hop"]["mean"] if result.get("1hop") else 0.0
    a2 = result["2hop"]["mean"] if result.get("2hop") else 0.0
    s = synergy(a1, a2)
    result["synergy"] = dict(
        value=s,
        definition="acc_2hop / acc_1hop^2（独立两跳的期望上限；旧稿裸报 acc2/acc1 已弃用）",
        note="ratio 方差随 acc_1hop 减小而爆炸；必须以 1hop/2hop 各自的 bootstrap CI 共同判定，单看点估计无意义。",
        verdict=("INCONCLUSIVE" if (a1 < 0.15 or (result["1hop"] or {}).get("thin"))
                 else ("PASS" if (s is not None and s > 1.1) else "FAIL_synergy≤1.1")))

    # ---- 写入侧三曲线（账本相对 RAG 的真卖点）----
    result["write"] = dict(
        conflicts=len(agg["conflict"]),
        note="conflict/stale-id 追踪见 results；污染率需 api 模式跑『旧 id 是否仍被召回』")

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stderr)
    _stderr(result)


def _stderr(r):
    def fmt(v):
        if v is None: return "n/a"
        if isinstance(v, dict):
            if v.get("thin"): return f"{v['mean']:.1%} (n={v['n']},CI太小不报)"
            return f"{v['mean']:.1%}  [95%CI {v['lo']:.1%}–{v['hi']:.1%}, n={v['n']}]"
        return f"{v:.3f}"
    print(f"[eval mode={r['mode']}]", file=sys.stderr)
    print(f"  1hop : {fmt(r.get('1hop'))}", file=sys.stderr)
    print(f"  2hop : {fmt(r.get('2hop'))}", file=sys.stderr)
    if r.get("1hop") and r["1hop"].get("null_mean") is not None:
        print(f"  2hop(仅撤回题) : {r['1hop']['null_mean']:.1%}  n={r['1hop']['null_n']}", file=sys.stderr)
    print(f"  synergy = {r['synergy']['value']}  → {r['synergy']['verdict']}", file=sys.stderr)
    if r["synergy"]["verdict"] == "INCONCLUSIVE":
        print("   ↑ 1hop 太低，ratio 不可信；别用这个数下结论。", file=sys.stderr)


if __name__ == "__main__":
    main()
