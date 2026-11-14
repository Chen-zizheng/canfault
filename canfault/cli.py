# -*- coding: utf-8 -*-
"""命令行入口。

三条子命令：
  faults  按 6 类故障依次注入，看 DUT 的反应
  fuzz    在总线上跑模糊测试，可选最小化
  ecu     只做监听，等价于「把被测件单独挂上去看它多久崩」
"""
from __future__ import annotations

import argparse
import sys
import time

import can

from . import report
from .ecu import EcuSim, nominal_frames
from .faults import FAULT_KINDS, FaultPlan, fault_report, inject
from .fuzz import minimize, run_fuzz

SEEDS = list(nominal_frames())


def _open(interface: str, channel: str):
    return can.Bus(interface=interface, channel=channel)


def cmd_faults(args) -> int:
    payload = {"interface": args.interface, "channel": args.channel, "faults": []}
    tx = _open(args.interface, args.channel)
    rx = _open(args.interface, args.channel)
    ecu = EcuSim(rx).start()
    try:
        for kind in FAULT_KINDS:
            plan = FaultPlan(kind=kind, rate=args.rate, seed=args.seed)
            stats = fault_report(SEEDS, plan)
            for frame in inject(SEEDS, plan):
                try:
                    tx.send(frame.to_can())
                except can.CanError:
                    pass
            time.sleep(0.2)
            payload["faults"].append(stats)
            print(
                "%-13s 输入 %4d 帧 → 输出 %4d 帧 (%+d)，DUT 已崩 %d 次"
                % (kind, stats["input"], stats["output"], stats["delta"], len(ecu.state.crashes))
            )
    finally:
        ecu.stop()
        tx.shutdown()
        rx.shutdown()
    if args.out:
        print("报告：", report.write_json(args.out, payload))
    return 0


def cmd_fuzz(args) -> int:
    tx = _open(args.interface, args.channel)
    rx = _open(args.interface, args.channel)
    ecu = EcuSim(rx).start()
    payload = {"interface": args.interface, "channel": args.channel}
    try:
        stats = run_fuzz(tx, ecu, SEEDS, seconds=args.seconds, seed=args.seed)
        payload["fuzz"] = stats.to_dict()
        print(
            "发送 %d 帧 / %.2f s = %.0f 帧/s；崩溃 %d 次，去重后 %d 个"
            % (stats.sent, stats.duration_s, stats.rate, len(stats.crashes), len(stats.unique))
        )
        for crash in stats.unique:
            print("  %-20s [%s] %s" % (crash.frame_hex, crash.exc_type, crash.message))
        if args.minimize:
            payload["minimized"] = []
            for crash in stats.unique[: args.max_minimize]:
                short = minimize(tx, ecu, crash, SEEDS)
                payload["minimized"].append({"from": crash.frame_hex, "to": short})
                print("  最小化：%s → %s" % (crash.frame_hex, short))
    finally:
        ecu.stop()
        tx.shutdown()
        rx.shutdown()
    if args.out:
        print("报告：", report.write_json(args.out, payload))
        print("报告：", report.write_markdown(args.out.rsplit(".", 1)[0] + ".md", payload))
    return 0


def cmd_ecu(args) -> int:
    bus = _open(args.interface, args.channel)
    ecu = EcuSim(bus).start()
    try:
        time.sleep(args.seconds)
    finally:
        ecu.stop()
        bus.shutdown()
    print("收到 %d 帧，崩溃 %d 次" % (ecu.state.frames_seen, len(ecu.state.crashes)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="canfault", description="CAN 总线故障注入与报文模糊测试")
    p.add_argument("--interface", default="socketcan", help="socketcan / virtual")
    p.add_argument("--channel", default="vcan0")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("faults", help="6 类故障注入")
    f.add_argument("--rate", type=float, default=0.05)
    f.add_argument("--seed", type=int, default=20260101)
    f.add_argument("--out", default="")
    f.set_defaults(func=cmd_faults)

    z = sub.add_parser("fuzz", help="报文模糊测试")
    z.add_argument("--seconds", type=float, default=20.0)
    z.add_argument("--seed", type=int, default=7)
    z.add_argument("--minimize", action="store_true")
    z.add_argument("--max-minimize", type=int, default=3)
    z.add_argument("--out", default="")
    z.set_defaults(func=cmd_fuzz)

    e = sub.add_parser("ecu", help="只监听")
    e.add_argument("--seconds", type=float, default=5.0)
    e.set_defaults(func=cmd_ecu)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
