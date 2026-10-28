#!/usr/bin/env bash
# StateDial-Ω 自检：生成 → 绘图，不依赖任何模型/网络
set -e
cd "$(dirname "$0")"
python gen.py --turns 300 --seed 1 --out /tmp/demo.jsonl >/dev/null
python plot.py /tmp/demo.jsonl --out /tmp/demo.png
echo "OK: trace=$(wc -c < /tmp/demo.jsonl) bytes, plot=/tmp/demo.png"
