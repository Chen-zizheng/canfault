# canfault — 车载 CAN 总线的故障注入与报文模糊测试

一个能在 WSL 里 5 分钟跑起来的迷你测试工具：往 vcan 虚拟总线上灌报文，看被测 ECU 多久崩、崩在哪一条报文上，然后把那条报文缩到最短。

不是演示截图，仓库里 26 条 pytest 全绿，下面的数字都是在这台机器上真跑出来的。

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
  faults.py   6 类故障注入，纯函数，不碰总线
  fuzz.py     种子变异、崩溃去重、逐字节最小化
  report.py   JSON + Markdown 报告
  cli.py      命令行入口
tests/        26 条用例，CI 用 virtual 接口，不依赖内核模块
```

## 快速开始

```bash
# 1. 造一条虚拟总线（WSL2 / Ubuntu 均可，不需要真实硬件）
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

## 6 类故障注入（实测）

种子是 384 帧「正常驾驶」报文（6 个 ID × 64 个时间片），注入比例 5%：

| 故障类型 | 输入帧 | 输出帧 | 净增 | DUT 崩溃次数 |
| --- | --- | --- | --- | --- |
| drop（丢帧） | 384 | 364 | -20 | 5 |
| duplicate（重复帧） | 384 | 404 | +20 | 11 |
| dlc_tamper（DLC 篡改） | 384 | 384 | 0 | 28 |
| out_of_range（信号越界） | 384 | 384 | 0 | 32 |
| bus_load（总线负载拉高） | 384 | 524 | +140 | 53 |
| timing_drift（时序漂移） | 384 | 384 | 0 | 56 |

信号越界只 32 次就崩，是因为 DUT 对 5 个信号都做了上下限检查；丢帧反而最不容易崩（少一帧不会让解析器抛异常，只会让心跳计数对不上）。

## 模糊测试（20 秒实测）

```
发送 57860 帧 / 20.00 s = 2893 帧/s；崩溃 12877 次，去重后 12 个
  0x100 [8] 08 80 00 00 00 00 00 00  [FrameError] throttle out of range: 2176 not in [0, 1000]
  0x300 [8] 7E 84 67 E5 46 D5 3E C8  [FrameError] gear out of range: 6 not in [0, 5]
  0x500 [8] 85 03 36 B3 6F 13 BC AE  [FrameError] coolant out of range: -123 not in [-40, 150]
  0x600 [8] 05 05 00 00 00 00 00 00  [FrameError] heartbeat gap: expected 0, got 5
  ...（共 12 个去重后的崩溃，完整列表见 reports/fuzz.md）
```

12877 次崩溃去重成 12 个，是因为去重键是「异常类型 + 帧 ID + 抹平数字后的异常信息」——同一条规则被踩一万次，仍然是同一个缺陷。

## 五个设计取舍

1. **单元测试用 virtual 接口，不用 vcan。** CI 机器没有内核模块也能跑；vcan 只留给「真跑一遍看数字」这一步。为此 `EcuSim` 只依赖 `bus.recv()` 和 `bus.send()` 两个方法，不认具体 interface。
2. **必须自己造 DUT。** 没有被测件就没有「崩溃」可谈。这个 ECU 模拟器故意写得很严：DLC 必须 8、未知 ID 直接抛、5 个信号都查范围、心跳计数必须连号。宽松的解析器会让模糊测试一个崩溃都找不到，工具就成了摆设。
3. **注入器是纯函数。** `inject(frames, plan)` 输入报文列表、输出报文列表，不碰总线也不 sleep，所以 6 类故障能被单元测试直接断言（比如「DLC 篡改后所有帧都短于 8 字节」），而不是靠跑一遍总线看日志。
4. **去重键要抹平数字。** 第一版把调用栈位置也算进签名，结果同一条 DLC 规则被报成十几种崩溃；改成「异常类型 + 帧 ID + 数字替换成 #」之后，12 个才是真实缺陷数。
5. **最小化按「同签名」判定。** 删一个字节通常会把 DLC 从 8 变成 7，触发的是另一条规则，签名不同就不算最小化成功。这是有意的：跨缺陷类型的收缩会得出「空报文也能崩」这种没用的结论。

## 已知限制

- 只支持 Classical CAN 的 8 字节数据段，CAN FD / 29 位扩展帧没有实现。
- `timing_drift` 只标记报文，实际发送间隔由 runner 的 `time.sleep` 控制，精度是毫秒级，做不了微秒级的时序一致性测试。
- DUT 是模拟器，不是真实的 AUTOSAR 协议栈；真实 ECU 的崩溃往往是总线关闭、内存越界这类，这里的崩溃统一表现为解析异常。
- 没有接 Allure，报告是手写 JSON / Markdown；要接 CI 时直接读 JSON 里的 `unique_crashes` 判回归即可。
