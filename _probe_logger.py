# -*- coding: utf-8 -*-
"""探针: Logger 起停 + ASC/BLF 回读验证"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.can_logger import CanLogger
from app.core.data_hub import KIND_FRAME
from app.models.dto import FrameDTO

import can

for fmt in ('asc', 'blf'):
    lg = CanLogger()
    p = f'_lg_test.{fmt}'
    ok, err = lg.start(p, fmt)
    assert ok, err
    frames = [
        FrameDTO(timestamp=time.time(), channel_key='CAN1', direction='RX',
                 id=0x5F, name='M', dlc=8, data=b'\x01' * 8, is_fd=False),
        FrameDTO(timestamp=time.time() + 0.1, channel_key='CAN2',
                 direction='TX', id=0x100, name='N', dlc=64,
                 data=b'\x02' * 64, is_fd=True),
    ]
    lg._on_push(lg._sub_id, KIND_FRAME, frames)
    lg.stop()
    logs = list(can.LogReader(p))
    print(fmt, 'written=2 read=', len(logs),
          'ids=', [hex(m.arbitration_id) for m in logs],
          'fd=', [m.is_fd for m in logs],
          'ch=', [m.channel for m in logs])
    assert len(logs) == 2
    os.remove(p)
print('LOGGER OK')
