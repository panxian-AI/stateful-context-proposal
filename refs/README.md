# 引用核验表

> 本仓库所有外部结论都列在这里。**编号不对、结论对不上，请直接开 issue。**
> 核验日期：2026-10-28。均为公开 arXiv，未做实验复现（除本仓库 bench 自测）。

| # | arXiv | 标题 / 简称 | 本仓库用到的结论 | 核验 | 备注 |
|---|---|---|---|---|---|
| [1] | 2512.23675 | TTT-E2E: Test-Time Training for Ultra-Long Context | 3B/164B token；128K 长文质量追平全注意力；128K 推理延迟约 2.7×（H100 口径）；窗口 8K + chunk 1K | ✅ 编号+结论属实 | 加速比为 prefill/推理延迟口径，**非纯 decode**；未测对话掉上下文召回 |
| [2] | 2610.25317 | Atoms, Not Knowledge: Addressable Memory Breaks Long-Horizon Recall | V4.1-Flash 上事实 50→1000 条 98%→12.7%；两跳 26% vs 期望 25%；in-context gap 约 28pp | ✅ 编号+结论属实 | **实验模型含 DeepSeek-V4.1-Flash**，是本项目最直接的相关证据 |
| [3] | 2606.16707 | User as Code: Compiling Long-Horizon Interaction into Executable State | 聚合类任务 99% vs MemMachine 43% / Mem0 6%；LOCOMO 纯召回 78.8% | ✅ 编号属实 | 支撑 L2 类型化状态机一支 |
| [4] | 2607.08032 | 率失真视角下的紧凑记忆（UCI） | 提出 COMPACT-Bench，统一紧凑记忆评测框架 | ✅ 编号属实 | ⚠️ 是**统一框架/综述**，**不是**"对所有紧凑记忆成立的率失真下界定理"。本仓库只借其评测语言 |
| [5] | 2412.06464 | Gated DeltaNet | 线性序列模型，ICLR 2025 camera-ready | ✅ 编号属实 | L0 候选之一 |
| [6] | 2605.10870 | DeMem | 描述相似度对证据兼容 Spearman ρ=0.103，AUC 0.548 | ✅ 编号属实 | 说明"语义相似 ≠ 该记住" |
| [7] | 2601.02845 | TiMem | LOCoMo 75.30%，召回长度省 52.20% | ✅ 编号属实 | 时间感知压缩的对照 |
| ~~[8]~~ | ~~2607.27539~~ | GemmaSV / 可寻址删除一支 | ~~精确删除 + 召回双通过~~ | ⚠️ 已降级 | 论文属实，但"可删除性"来自其嫁接的 support-vector store，**不是** Gemma 原生能力；未报 >0.5 AUC。**本仓库不引用其具体数字** |

## 明确不引用 / 已删除的条目

- 任何标注为"In-Place TTT 外部复现 / 博客级负面证据"的无编号来源：**查无公开来源，已删除，不进入本仓库。**
- 任何"百万 token 下 X× 加速"的跨论文横比：**口径不统一，本仓库不做横向排名，只跑自己的 bench。**

## 口径约定

- 加速比一律标注硬件 + 阶段（prefill / decode / 端到端），不写裸数字。
- "追平"指原论文在指定 benchmark 上的报告值，本仓库**未独立复现**，仅作动机证据。
- 本仓库自己的数字只来自 [`bench/`](../bench)，写在 [`results/`](../results)，带提交哈希和命令。

欢迎补充你跑出来的对照。
