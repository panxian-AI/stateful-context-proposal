#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StateDial-Ω · 合成数据生成器  v0.1

目标：造出一批「单条事实记得住、两跳组合会崩」的多轮对话，
用来测「常数状态 + 地址化账本」vs「纯上下文 / 纯 RAG」的真实差距。

设计原则（对应 proposal §5 证伪协议）：
  - 每条事实有 UUID、版本、有效期、依赖边
  - 中途会撤回 / 覆盖 / 冲突，逼系统做「按地址证明」而不是「靠注意力猜」
  - 两跳题 = 事实 A 依赖事实 B，B 被撤回后 A 必须跟着失效

输出 jsonl：每轮一条 {
  action: set|revoke|conflict|query_1hop|query_2hop|distractor,
  tick, fact_id, value, depends_on, query, expected, reason, n_facts_alive
}
"""
import argparse, json, random, sys, uuid
from typing import Dict, List, Optional

rng = random.Random()

# ---------- 域：越小越容易被语义相似度误导 ----------
COLORS = ["azure", "moss", "amber", "plum", "silt"]
UNITS = ["budget", "quota", "deadline", "owner", "tier"]
MODIFIERS = ["primary", "backup", "emergency", "preview"]


def make_fact(tick: int, prev: Dict[str, dict] | None = None) -> dict:
    fid = "f_" + uuid.uuid4().hex[:10]
    color = rng.choice(COLORS)
    unit = rng.choice(UNITS)
    mod = rng.choice(MODIFIERS)
    # 数值故意用相近区间，防模型靠数值大小猜
    value = rng.randint(10, 99)
    depends_on = None
    if prev and rng.random() < 0.35:           # 35% 的事实挂在另一条上 → 两跳陷阱
        parent = rng.choice(list(prev.keys()))
        depends_on = parent
    return dict(fid=fid, slot=f"{mod}_{color}_{unit}", value=value,
                depends_on=depends_on, born=tick, dead=None)


def resolve(facts: Dict[str, dict], fid: str) -> Optional[int]:
    """沿 depends_on 链求值；任一环节已撤回则返回 None（= 应答『已失效/不知道』）"""
    seen = set()
    cur = fid
    while cur:
        if cur in seen:
            return None  # 环 → 未定义
        seen.add(cur)
        f = facts.get(cur)
        if not f or f["dead"] is not None:
            return None
        cur = f["depends_on"]
    return facts[fid]["value"]


def build(args) -> List[dict]:
    facts: Dict[str, dict] = {}
    turns: List[dict] = []
    tick = 0
    alive_history = []
    slot_latest: Dict[str, str] = {}   # slot -> 当前有效 fid，供「写入污染」评测

    for _ in range(args.turns):
        tick += 1
        n_alive = len([f for f in facts.values() if f["dead"] is None])
        r = rng.random()

        # --- 1. 写入新事实 ---
        if r < 0.42 or n_alive < 3:
            f = make_fact(tick, facts if n_alive else None)
            facts[f["fid"]] = f
            slot_latest[f["slot"]] = f["fid"]
            turns.append(dict(action="set", tick=tick, fact_id=f["fid"],
                             slot=f["slot"], value=f["value"],
                             depends_on=f["depends_on"], expected="ok",
                             reason="write", n_facts_alive=n_alive + 1))

        # --- 2. 撤回：这是最狠的测试点 ---
        elif r < 0.6 and n_alive:
            victim = rng.choice([f for f in facts.values() if f["dead"] is None])
            victim["dead"] = tick
            if slot_latest.get(victim["slot"]) == victim["fid"]:
                slot_latest.pop(victim["slot"], None)
            turns.append(dict(action="revoke", tick=tick, fact_id=victim["fid"],
                             slot=victim["slot"],
                             expected=dict(kind="null"), reason="revoke",
                             n_facts_alive=n_alive - 1))

        # --- 3. 覆盖冲突 ---
        elif r < 0.7 and n_alive:
            old = rng.choice([f for f in facts.values() if f["dead"] is None])
            new_val = rng.randint(10, 99)
            old["dead"] = tick
            f = make_fact(tick, facts)
            f["slot"] = old["slot"]            # 同 slot，不同 fid
            f["value"] = new_val
            facts[f["fid"]] = f
            slot_latest[f["slot"]] = f["fid"]
            turns.append(dict(action="conflict", tick=tick,
                             revoked=old["fid"], fact_id=f["fid"],
                             slot=f["slot"], value=new_val,
                             expected=dict(kind="value", value=new_val,
                                           stale_fid=old["fid"]),
                             reason="slot overwrite", n_facts_alive=n_alive))

        # --- 4. 单跳查询 ---
        elif r < 0.85 and n_alive:
            f = rng.choice([f for f in facts.values() if f["dead"] is None])
            turns.append(dict(action="query_1hop", tick=tick, fact_id=f["fid"],
                             query=f"当前 {f['slot']} 是多少？（id={f['fid']}）",
                             expected=dict(kind="value", value=f["value"]),
                             reason="1-hop exact", n_facts_alive=n_alive))

        # --- 5. 两跳组合：真正区分「存得住」和「组得成」---
        else:
            # 一半：整链存活 ⇒ 期望确定值（测「组得成」）
            # 一半：父节点已撤回 ⇒ 期望 null（答数字即错，测「知道它失效了」）
            if rng.random() < 0.5:
                candidates = [f for f in facts.values()
                              if f["dead"] is None and f["depends_on"]
                              and resolve(facts, f["fid"]) is not None]
                if not candidates:
                    continue
                f = rng.choice(candidates)
                exp = dict(kind="value", value=resolve(facts, f["fid"]),
                           chain=[f["fid"], f["depends_on"]])
            else:
                dead_leaves = [f for f in facts.values()
                               if f["dead"] is not None and f["depends_on"] is None]
                if not dead_leaves:
                    continue
                target = rng.choice(dead_leaves)
                exp = dict(kind="null", chain=[target["fid"]])
                f = dict(fid=target["fid"], slot=target["slot"], depends_on=None)
            turns.append(dict(action="query_2hop", tick=tick, fact_id=f["fid"],
                             query=f"基于 {f['slot']}（id={f['fid']}）及其依赖项，最终值是多少？",
                             expected=exp, reason="2-hop chain / dead-branch",
                             chain=exp.get("chain", []),
                             n_facts_alive=n_alive))

        if tick % 50 == 0:
            alive_history.append((tick, n_alive))

    # 末尾强制补一组两跳，方便画尾段曲线
    return turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--facts", type=int, default=500,
                    help="软上限提示（实际由写入概率决定）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="-")
    args = ap.parse_args()
    rng.seed(args.seed)
    turns = build(args)
    payload = dict(meta=dict(turns=len(turns), seed=args.seed,
                             version="StateDial-Omega-0.1"),
                   turns=turns)
    txt = json.dumps(payload, ensure_ascii=False)
    if args.out == "-":
        print(txt)
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(txt + "\n")
        print(f"[gen] {len(turns)} turns → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
