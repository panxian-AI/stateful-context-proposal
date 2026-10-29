# 常数状态 · 地址化账本

> 一份**等待被证伪**的长时对话上下文假设，附可复现的合成评测骨架。
> 不是论文，不宣称结果。脚本在 [`bench/`](./bench)，跑完你自己看曲线。

**一句话**：窗口外推、RAG、滚动摘要都只是把上限推远。更硬的解法是——

> 模型内部只留 **O(1) 的决策状态**；不可压缩的历史下沉为
> **可寻址、可版本化、可按地址证明的外部账本**。

这不代表"无限上下文"（那在信息论上不可能精确成立）。它承诺的是三件事：

| 承诺 | 含义 |
|---|---|
| 活跃状态有界 | 每步 decode 成本不随历史长度增长 |
| 精确事实可证 | UUID / 数值 / 撤销走地址读写，不扫全文 |
| 长程一致可测 | 合成集里故意埋冲突、撤回、跨轮依赖，看它到底记不记得住 |

---

## 为什么我觉得这件事值得做

- **最强的新路线还没人在"对话"上验过。** TTT-E2E 在 3B / 164B token、128K 长文上质量追平全注意力，128K 推理延迟约 2.7×（H100 口径）；但它验的是长文档，**不是"第 N 轮还能精确撤回第 37 条规则"**。
- **已经有反例当标尺。** Atoms, Not Knowledge（arXiv:2610.25317）在 DeepSeek-V4.1-Flash 上测出：事实 50→1000 条，召回 98%→12.7%；两跳组合 26% ≈ 独立乘积 25%。**存得住，不等于组得成推理链。** 谁先跨这条线，谁重新定义记忆。
- ⚠️ **一处自我修正（v0.2）**：早期版本写过「V4 的 MLA 低秩行存天然适合做 L1 地址账本」——**这是错的**。V4 仍在 MLA 体系，但切到了 MQA mode；序列维压缩由 CSA/HCA 做，是**时间维池化，压完的条目不可逐条寻址**，跟「按 UUID 精确读写某一条」是两件事。L1 现在定位为**与底座无关的确定性寻址层**，模型只当 issuer，不当 store。详见 proposal §3 与 CHANGELOG。
- **更值得说的是反方向**：V4 技术报告通篇没提 TTT / Titans 这类测试时记忆更新。本提案的 L0 押的正是这条被有意没走的路——所以它是「想请你们看看为什么可能不该走」，不是「你们顺手就能做」。

## 三层拆分

```
┌─ L0 决策状态 (TTT / Gated-Delta)     O(1) decode，丢一点无所谓；远期，要重训
├─ L1 地址化精确账本 (确定性寻址层)      按需取，可删/可版本/可审计；模型只当 issuer
└─ L2 类型化状态机 (解释器)             聚合/约束/计数跑代码，今天就能上
```

> L0 与 L2 是「已实现 / 可工程化」的两端；**L1 的寻址机制是目前最弱、也最容易被自己引用的论文打脸的一环**（见 proposal §7 四条致命问题）。这份提案不假装解决了它。

职责刻意分开，不堆成"又一个记忆模块"。完整论证、致命问题和认输条件见 [`proposal.md`](./proposal.md)。

## 30 秒自测（v0.2）

```bash
cd bench
pip install -r requirements.txt
python gen.py --turns 300 --facts 600 --seed 42 --out results/demo.jsonl

# 离线真值裁判：跑通协议、画 CI 与 in-context 对照（不联网、不调模型）
python eval.py results/demo.jsonl --mode oracle
python plot.py results/demo.jsonl --out results/v0.2.protocol.png

# 接真实模型时（需 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL）
python eval.py results/demo.jsonl --mode api --seeds 3
python eval.py results/demo.jsonl --mode ic  --seeds 3   # in-context 对照
```

**声明**：`results/` 里的图是**离线真值裁判的形态校验**，`eval.py` 默认不调任何模型。
它证明的是「评测协议本身有没有算出合理的结果」，不是「某模型记得了」。
接上真实模型之前，请把这一点当免责声明读两遍——我也是被评审提醒才加上这句的。

出来的图是两条曲线：**事实召回率 vs 轮次**、**两跳组合 synergy ratio vs 轮次**。
`synergy ratio ≤ 1.1` 且单跳还行 → 这条路线没赢，承认失败。这就是本仓库的验收标准。

## 目录

| 路径 | 内容 |
|---|---|
| [`proposal.md`](./proposal.md) | 完整提案：架构、信息论边界、四条致命问题、ablation、验收门槛 |
| [`bench/`](./bench) | 合成数据生成器 + 评测 + 绘图（模型无关，走 OpenAI 兼容 API） |
| [`refs/`](./refs) | 引用编号核验表：arXiv 编号、结论、是否已复现 |
| [`results/`](./results) | 放你自己的跑分，PR 欢迎 |

## 我想问的只有一句

> **内部曲线是否也看到"单条强、两跳崩"？**

如果贵组已经有这条数据，哪怕不能公开，告诉我方向对不对，这份东西的价值就到了。

也欢迎把你们的评测集、你们的内存接口放进来一起跑。建个公开基准（`StateDial-Ω`），整个领域缺的就是这个。

---

**panxian-AI** · 相关工作：[Multi_Agent_Dynamic_Narrative_Engine](https://github.com/panxian-AI/Multi_Agent_Dynamic_Narrative_Engine)
（多智能体长程叙事里同样撞上状态一致性，这是这份提案的工程起点。）

许可：代码 MIT，提案 CC BY 4.0。随便 fork，随便证伪。
