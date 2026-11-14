# -*- coding: utf-8 -*-
import os
import sys

import can
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def bus_pair():
    """两条挂在同一虚拟通道上的总线：tx 发，rx 收。

    用 virtual 而不是 socketcan，是为了让 CI 在没有任何内核模块的机器上也能跑。
    """
    channel = "test-%d" % id(object())
    tx = can.Bus(interface="virtual", channel=channel)
    rx = can.Bus(interface="virtual", channel=channel)
    try:
        yield tx, rx
    finally:
        tx.shutdown()
        rx.shutdown()
