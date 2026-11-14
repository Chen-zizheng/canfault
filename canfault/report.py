# -*- coding: utf-8 -*-
"""把一次运行写成 JSON + Markdown 两份报告。

JSON 给机器（CI 里判回归），Markdown 给人（贴 issue / 写周报）。
"""
from __future__ import annotations

import json
import os
import time


def write_json(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def render_markdown(payload: dict) -> str:
    lines = ["# canfault 运行报告", ""]
    lines.append("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 接口 / 通道：%s / %s" % (payload.get("interface"), payload.get("channel")))
    if "fuzz" in payload:
        f = payload["fuzz"]
        lines += [
            "",
            "## 模糊测试",
            "",
            "| 指标 | 数值 |",
            "| --- | --- |",
            "| 发送帧数 | %d |" % f["sent"],
            "| 时长 | %.2f s |" % f["duration_s"],
            "| 吞吐 | %.0f 帧/s |" % f["frames_per_s"],
            "| 崩溃总数 | %d |" % f["crashes"],
            "| 去重后崩溃 | %d |" % f["unique_crashes"],
        ]
        if f["unique"]:
            lines += ["", "## 去重后的崩溃", "", "| 报文 | 异常 | 签名 |", "| --- | --- | --- |"]
            for c in f["unique"]:
                lines.append("| %s | %s | %s |" % (c["frame"], c["message"], c["signature"]))
    if "faults" in payload:
        lines += ["", "## 故障注入", "", "| 类型 | 输入帧 | 输出帧 | 净增 |", "| --- | --- | --- | --- |"]
        for row in payload["faults"]:
            lines.append("| %s | %d | %d | %+d |" % (row["kind"], row["input"], row["output"], row["delta"]))
    if payload.get("minimized"):
        lines += ["", "## 最小化", ""]
        lines += ["- %s → %s" % (m["from"], m["to"]) for m in payload["minimized"]]
    lines.append("")
    return "\n".join(lines)


def write_markdown(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(payload))
    return path
