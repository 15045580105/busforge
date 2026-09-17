# -*- coding: utf-8 -*-
"""探针: 覆盖模式列头排序 (时间列不排序; DLC/ID 数值感知 + 点击翻向 + 模式联动)"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent

from app.ui.widgets.trace_view import TraceView
from app.models.dto import FrameDTO


def rows(v):
    return [(v._table.topLevelItem(i).text(0),
             v._table.topLevelItem(i).text(3),
             v._table.topLevelItem(i).text(5))
            for i in range(v._table.topLevelItemCount())]


def click_col(v, col):
    """直接构造按下事件送表头处理器 (离屏无事件循环, QTest 点击不送达)"""
    hdr = v._table.header()
    pos = QPoint(hdr.sectionViewportPosition(col)
                 + hdr.sectionSize(col) // 2, hdr.height() // 2)
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(pos),
                     QPointF(hdr.mapToGlobal(pos)),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    hdr.mousePressEvent(ev)


def main():
    app = QApplication(sys.argv)
    v = TraceView()
    v.resize(900, 500)
    v.show()

    frames = [
        FrameDTO(timestamp=9.5, channel_key='CAN1', direction='RX',
                 id=0x300, name='C', dlc=64, data=b'\x03' * 64),
        FrameDTO(timestamp=10.25, channel_key='CAN1', direction='RX',
                 id=0x5F, name='A', dlc=8, data=b'\x01' * 8),
        FrameDTO(timestamp=11.0, channel_key='CAN2', direction='TX',
                 id=0x100, name='B', dlc=8, data=b'\x02' * 8),
    ]
    v._toggle_mode(True)   # 覆盖模式
    v._on_push(v._sub_id, 'frame', frames)
    v._refresh_table()
    assert v._table.topLevelItemCount() == 3
    hdr = v._table.header()
    # 时间列不排序: 初始指示器不显示 (默认落在时间列)
    assert not hdr.isSortIndicatorShown()

    # 1. 点击时间列: 无动作 (不排序/不显示指示器/行序不变)
    t = [r[0] for r in rows(v)]
    click_col(v, 0)
    assert not hdr.isSortIndicatorShown()
    assert [r[0] for r in rows(v)] == t
    print('PASS 1 时间列点击不排序:', t)

    # 2. DLC 列点击升序 (数值: 8,8,64), 再点翻降序
    click_col(v, 5)
    assert hdr.isSortIndicatorShown()
    d = [int(r[2]) for r in rows(v)]
    assert d == [8, 8, 64], d
    click_col(v, 5)
    d2 = [int(r[2]) for r in rows(v)]
    assert d2 == [64, 8, 8], d2
    assert hdr.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    print('PASS 2 DLC点击升/降序:', d, '->', d2)

    # 3. 第三击取消: 指示器隐藏 + 恢复首次出现顺序 (C,A,B)
    click_col(v, 5)
    assert not hdr.isSortIndicatorShown()
    ids0 = [int(r[1], 16) for r in rows(v)]
    assert ids0 == [0x300, 0x5F, 0x100], ids0
    print('PASS 3 第三击取消恢复插入序:', [hex(i) for i in ids0])

    # 4. ID 数值排序 (95 < 256 < 768)
    click_col(v, 3)
    ids = [int(r[1], 16) for r in rows(v)]
    assert ids == [0x5F, 0x100, 0x300], ids
    print('PASS 4 ID点击数值升序:', [hex(i) for i in ids])

    # 5. 切回滚动模式: 指示器隐藏, 行恢复时间序截顶
    v._toggle_mode(False)
    assert not hdr.isSortIndicatorShown()
    t5 = [r[0] for r in rows(v)]
    assert t5 == sorted(t5), t5
    print('PASS 5 滚动模式指示器隐藏+时间序:', t5)

    print('ALL PASS')


if __name__ == '__main__':
    main()
