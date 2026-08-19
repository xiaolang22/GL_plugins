"""打印机控制最小实现 - 通过 TCP 9100 端口发送 ESC/POS 指令"""
import socket

PRINTER_IP = "192.168.211.200"
PRINTER_PORT = 9100  # ESC/POS 默认端口

# 常用 ESC/POS 指令
INIT = b"\x1b\x40"           # 初始化打印机
LF = b"\n"                   # 换行
ALIGN_C = b"\x1b\x61\x01"    # 居中
ALIGN_L = b"\x1b\x61\x00"    # 左对齐
ALIGN_R = b"\x1b\x61\x02"    # 右对齐
BOLD_ON = b"\x1b\x21\x08"    # 加粗
BOLD_OFF = b"\x1b\x21\x00"   # 取消加粗
CUT = b"\x1d\x56\x42\x00"    # 切纸


def _connect() -> socket.socket:
    """建立到打印机的连接"""
    return socket.create_connection((PRINTER_IP, PRINTER_PORT), timeout=5)


def _align_cmd(align: str) -> bytes:
    return {"left": ALIGN_L, "center": ALIGN_C, "right": ALIGN_R}[align]


def print_lines(lines) -> None:
    """完整打印流程：先切纸 → 逐行打印 → 切纸

    Args:
        lines: 行列表，每行可以是 str 或 (text, align, bold) 元组
    """
    sock = _connect()
    try:
        # 1. 先切纸（清理上次残留）
        sock.sendall(CUT)
        # 2. 初始化
        sock.sendall(INIT)

        # 3. 逐行打印，全程不切纸
        for line in lines:
            if isinstance(line, str):
                text, align, bold = line, "left", False
            else:
                text = line[0]
                align = line[1] if len(line) > 1 else "left"
                bold = line[2] if len(line) > 2 else False

            cmd = _align_cmd(align)
            if bold:
                cmd += BOLD_ON
            cmd += text.encode("gbk")
            if bold:
                cmd += BOLD_OFF
            cmd += LF
            sock.sendall(cmd)

        # 4. 最后切纸
        sock.sendall(CUT)
    finally:
        sock.close()


def print_demo() -> None:
    """演示打印"""
    print_lines([
        ("==== 测试打印 ====", "center", True),
        "第一行内容",
        "第二行内容",
        "第三行内容",
        ("谢谢惠顾", "center"),
    ])


if __name__ == "__main__":
    print_demo()
