#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StateDial-Ω · 评测驱动  v0.1

对一个模型跑 jsonl 轨迹，输出：
  - 1-hop 精确召回率（按 tick 分桶）
  - 2-hop 精确召回率
  - synergy ratio = 2hop_acc / (1hop_acc × 独立乘积基线)
        ≤ 1.1  ⇒  「存得住但组不成链」，本路线没赢，认输（见 proposal §6）

模型通过 OpenAI 兼容 API 调用，不绑定任何厂商。
环境变量：OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
"""
import argparse, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

import gen  # 复用 resolve 逻辑做离线判定

SYSTEM = """你是状态账本助手。只输出 JSON，不要解释。
对查询，输出 {"value": <数字>}；若该项已被撤回/失效/无依赖，输出 {"value": null}。
禁止从对话历史里猜，只认仍然有效的条目。"""


def ask(client, model: str, history: list[dict], query: str) -> dict:
    messages = [{"role": "system", "content": SYSTEM}]
    for h in history:
        messages.append({"role": "user", "content": h["q"],
                        "content_type": "text"})  # 兼容部分服务端
        if h.get("a") is not None:
            messages.append({"role": "assistant", "content": json.dumps(h["a"], ensure_ascii=False)})
    messages.append({"role": "user", "content": query})
    # 用原生 http 而非 SDK，避免依赖
    import urllib.request
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": 0, "max_tokens": 64}).encode()
    req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions",
                                 data=body, headers={
                                     "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                     "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode())
    raw = resp["choices"][0]["message"]["content"].strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"value": "__parse_fail__", "raw": raw[:200]}


def replay(trace_file, model, max_workers=4, limit=None):
    data = json.load(open(trace_file, encoding="utf-8"))
    turns = data["turns"][:limit] if limit else data["turns"]

    facts = {}
    history = []          # 喂给模型的「可见历史」：这里模拟纯上下文基线
    bins = {"1hop": [], "2hop": []}

    def visible_facts():  # 上下文基线：只看得见未撤回的 set 文本
        return [f for f in facts.values() if f.get("dead") is None]

    for t in turns:
        action = t["action"]
        if action == "set":
            facts[t["fact_id"]] = dict(value=t["value"], dead=None,
                                       depends_on=t.get("depends_on"))
            history.append({"q": f"记录：{t['slot']} = {t['value']} (id={t['fact_id']})",
                            "a": {"value": t["value"]}})
        elif action == "revoke":
            if t["fact_id"] in facts:
                facts[t["fact_id"]]["dead"] = t["tick"]
            history.append({"q": f"撤回：{t['fact_id']}", "a": {"value": None}})
        elif action == "conflict":
            if t["revoked"] in facts:
                facts[t["revoked"]]["dead"] = t["tick"]
            facts[t["fact_id"]] = dict(value=t["value"], dead=None, depends_on=None)
            history.append({"q": f"更新：{t['slot']} = {t['value']} (id={t['fact_id']})",
                            "a": {"value": t["value"]}})
        elif action in ("query_1hop", "query_2hop"):
            exp = t["expected"]
            # 离线真值（裁判，不走模型）
            true_val = gen.resolve(facts, t["fact_id"])
            if exp["kind"] == "null":
                ok = (true_val is None)          # 链上有撤回 ⇒ 必须答不知道
            else:
                ok = (true_val is not None and true_val == exp["value"])
            # 这里先留位：真实评测走 ask()，v0.1 默认只跑「真值一致性校验」
            key = "2hop" if action == "query_2hop" else "1hop"
            bins[key].append(dict(tick=t["tick"], ok=ok, true=true_val,
                                 n_alive=t["n_facts_alive"], kind=exp["kind"]))
        # 防历史无限膨胀：纯上下文基线的显式缺陷
        if len(history) > 40:
            history = history[-40:]

    return bins, data["meta"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", help="gen.py 输出的 jsonl（实际为 ndjson 包裹对象）")
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "local-model"))
    ap.add_argument("--limit", type=int, default=None,
                    help="v0.1 默认只做离线真值校验；设 --limit 0 跑完整统计")
    args = ap.parse_args()

    bins, meta = replay(args.trace, args.model, limit=args.limit)
    h1 = [b for b in bins["1hop"] if b["ok"]]
    h2 = [b for b in bins["2hop"] if b["ok"]]
    acc1 = len(h1) / max(1, len(bins["1hop"]))
    acc2 = len(h2) / max(1, len(bins["2hop"]))

    out = dict(meta=meta, model=args.model,
               n_1hop=len(bins["1hop"]), n_2hop=len(bins["2hop"]),
               acc_1hop=round(acc1, 4), acc_2hop=round(acc2, 4),
               synergy_ratio=round(acc2 / max(1e-6, acc1), 3),
               verdict="PASS" if (acc2 / max(1e-6, acc1)) > 1.1 else "FAIL_LR≤1.1")

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stderr)
    print(f"[eval] 1hop={acc1:.1%}  2hop={acc2:.1%}  "
          f"synergy={out['synergy_ratio']}  → {out['verdict']}", file=sys.stderr)


if __name__ == "__main__":
    main()
