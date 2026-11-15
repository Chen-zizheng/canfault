# canfault — 车载 CAN 总线的故障注入与报文模糊测试

一个基于 python-can 的 CAN 故障注入与模糊测试工具：向 virtual / vcan 总线发送报文，用严格解析报文的 ECU 模拟器记录异常、按签名去重，并尝试缩减触发相同签名的报文。

仓库包含 26 条 pytest 用例。下文结果来自已有的 [故障注入报告](reports/faults.json)、[模糊测试报告](reports/fuzz.md) 和 [测试门禁报告](reports/gate.json)，不是本次重新运行所得。原 README 记录环境为 WSL2 Ubuntu、vcan0、Python 3.14、python-can 4.6.1、pytest 9.0.2；报告本身未记录全部环境字段，复跑命令见下文。

```
canfault faults   按 6 类故障依次注入，看 DUT 的反应
canfault fuzz     在总线上跑模糊测试，可选崩溃最小化
canfault ecu      只监听，等价于「把被测件单独挂上去看它多久崩」
```

## 结构

```
canfault/
  frame.py    CAN 帧模型、u16 打包、DLC 校验
  ecu.py      被测对象：严格解析报文的 ECU 模拟器（DUT）
  faults.py   5 类已实现的报文变换 + timing_drift 占位，纯函数，不碰总线
  fuzz.py     种子变异、崩溃去重、逐字节最小化
  report.py   JSON + Markdown 报告
  cli.py      命令行入口
tests/        26 条用例，CI 用 virtual 接口，不依赖内核模块
```

## 快速开始

```bash
# 1. 造一条虚拟总线（Linux / WSL2 内核需支持 vcan，不需要真实硬件）
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0

# 2. 装依赖
python3 -m pip install -r requirements.txt

# 3. 跑单元测试（用 virtual 接口，无需 vcan）
python3 -m pytest -q

# 4. 注入与模糊测试
python3 -m canfault.cli --interface socketcan --channel vcan0 faults --rate 0.05 --out reports/faults.json
python3 -m canfault.cli --interface socketcan --channel vcan0 fuzz --seconds 20 --minimize --out reports/fuzz.json
```

## 故障注入报告

种子是 384 帧「正常驾驶」报文（6 个 ID × 64 个时间片），注入比例 5%：

| 故障类型 | 输入帧 | 输出帧 | 净增 |
| --- | --- | --- | --- |
| drop（丢帧） | 384 | 364 | -20 |
| duplicate（重复帧） | 384 | 404 | +20 |
| dlc_tamper（缩短数据段，改变 DLC） | 384 | 384 | 0 |
| out_of_range（信号半字节改为 0xF） | 384 | 384 | 0 |
| bus_load（命中帧重复 8 次） | 384 | 524 | +140 |
| timing_drift（占位，未改变时序） | 384 | 384 | 0 |

这些输入/输出帧数可在 [faults.json](reports/faults.json) 核对。原 README 另列的 5、11、28、32、53、56 是同一 DUT 连续执行六轮后的累计异常计数，不是各类独立崩溃次数，且 JSON 未保存这些计数，因此不用于故障效果排名。`timing_drift` 当前只原样输出帧，CLI 没有对应逐帧延迟调度，不能声称已验证时序漂移。

## 模糊测试报告（20 秒）

来源：[fuzz.md](reports/fuzz.md)，报告时间 2026-11-14 14:53:24，接口 socketcan / vcan0：

```
发送尝试 57860 帧 / 20.00 s ≈ 2893 次/s；模拟器异常 12877 次，去重后 12 个签名
  0x100 [8] 08 80 00 00 00 00 00 00  [FrameError] throttle out of range: 2176 not in [0, 1000]
  0x300 [8] 7E 84 67 E5 46 D5 3E C8  [FrameError] gear out of range: 6 not in [0, 5]
  0x500 [8] 85 03 36 B3 6F 13 BC AE  [FrameError] coolant out of range: -123 not in [-40, 150]
  0x600 [8] 05 05 00 00 00 00 00 00  [FrameError] heartbeat gap: expected 0, got 5
  ...（共 12 个去重后的崩溃，完整列表见下方报告链接）
```

完整列表及缩减结果见 [fuzz.md](reports/fuzz.md)。去重键是「异常类型 + 帧 ID + 抹平数字后的异常信息」：12877 次异常聚合为 12 个签名，不等于发现 12 个真实产品缺陷。发送统计在 `bus.send` 异常时也会递增，因此是发送尝试数，不能据此证明全部帧成功上总线。

## 五个设计取舍

1. **单元测试用 virtual 接口，不用 vcan。** CI 机器没有内核模块也能跑；vcan 只留给「真跑一遍看数字」这一步。为此 `EcuSim` 只依赖 `bus.recv()` 和 `bus.send()` 两个方法，不认具体 interface。
2. **用严格的模拟 DUT 提供可检查的异常判据。** DLC 必须为 8、未知 ID 抛异常、5 个信号检查范围、心跳计数必须连号。这些是模拟器的校验规则，不代表真实 ECU 的缺陷或安全边界。
3. **注入器是纯函数。** `inject(frames, plan)` 输入报文列表、输出报文列表，不碰总线也不 sleep，所以报文变换能被单元测试直接断言（比如在注入比例为 1 时，DLC 篡改后的帧短于 8 字节），而不是靠跑一遍总线看日志。
4. **去重键抹平数字。** 用「异常类型 + 帧 ID + 数字替换成 # 的异常信息」聚合同类校验失败，避免不同数值被误计为不同签名；签名数仍需人工分析，不直接等于缺陷数。
5. **最小化按「同签名」判定。** 删一个字节通常会把 DLC 从 8 变成 7，触发的是另一条规则，签名不同就不算最小化成功。这样避免把原异常缩成另一类 DLC 错误。实现逐字节贪心删除，只尝试前 3 个签名，不保证全局最短，也不保证每次都能缩短。

## 已知限制

- 只支持 Classical CAN 的 8 字节数据段，CAN FD / 29 位扩展帧没有实现。
- `timing_drift` 是占位分支，当前不修改帧也不注入发送间隔；时序漂移和微秒级一致性测试尚未实现。
- DUT 是模拟器，不是真实的 AUTOSAR 协议栈；真实 ECU 的崩溃往往是总线关闭、内存越界这类，这里的崩溃统一表现为解析异常。
- 没有接 Allure，报告输出 JSON / Markdown。CI 可读取 `unique_crashes`，但只比较数量会漏掉签名替换，建议同时比较签名和预期规则。
- [gate.json](reports/gate.json) 保存一次 26 passed、0 failed 的门禁结果，wall time 为 3.459 秒；这是历史报告，不是本次环境测试结论。
