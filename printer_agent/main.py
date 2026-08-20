"""打印机控制服务 - 通过 TCP 9100 端口发送 ESC/POS 指令，对外暴露 HTTP /print 接口

行内联样式格式: "<文本>|<样式1>,<样式2>,..."
    样式 token:
      对齐: left / center / right
      字号: normal / tall / wide / double / quad
      其它: bold / underline / reverse
    缺省时使用默认样式 (左对齐, normal, 无修饰)
"""
import socket
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

PRINTER_IP = "127.0.0.1"
PRINTER_PORT = 9101  # ESC/POS 默认端口

# 常用 ESC/POS 指令
INIT = b"\x1b\x40"              # 初始化打印机
LF = b"\n"                      # 换行
ALIGN_L = b"\x1b\x61\x00"       # 左对齐
ALIGN_C = b"\x1b\x61\x01"       # 居中
ALIGN_R = b"\x1b\x61\x02"       # 右对齐
BOLD_ON = b"\x1b\x45\x01"       # 加粗开
BOLD_OFF = b"\x1b\x45\x00"      # 加粗关
UNDERLINE_ON = b"\x1b\x2d\x01"  # 下划线开
UNDERLINE_OFF = b"\x1b\x2d\x00" # 下划线关
REVERSE_ON = b"\x1d\x42\x01"    # 反白开
REVERSE_OFF = b"\x1d\x42\x00"   # 反白关
CUT = b"\x1d\x56\x42\x00"       # 切纸

# 字号 → GS ! n 字节映射 (高4位=高度倍数, 低4位=宽度倍数)
SIZE_MAP = {
    "normal": 0x00,  # 1x1
    "tall":   0x10,  # 高2x
    "wide":   0x01,  # 宽2x
    "double": 0x11,  # 2x2
    "quad":   0x22,  # 3x3
}

ALIGN_CMD = {"left": ALIGN_L, "center": ALIGN_C, "right": ALIGN_R}

# 每行打印后复位所有样式，避免污染下一行
RESET_STYLE = BOLD_OFF + UNDERLINE_OFF + REVERSE_OFF + b"\x1d\x21\x00"  # +复位字号


# ---------- 行解析与指令拼装 ----------

def _parse_line(raw: str) -> tuple:
    """解析 '文本|center,bold' → ('文本', style_dict)"""
    style = {
        "align": "left",
        "size": "normal",
        "bold": False,
        "underline": False,
        "reverse": False,
    }
    if "|" in raw:
        text, desc = raw.split("|", 1)
        for token in desc.split(","):
            token = token.strip()
            if not token:
                continue
            if token in ALIGN_CMD:
                style["align"] = token
            elif token in SIZE_MAP:
                style["size"] = token
            elif token == "bold":
                style["bold"] = True
            elif token == "underline":
                style["underline"] = True
            elif token == "reverse":
                style["reverse"] = True
            # 未识别 token 静默忽略
    else:
        text = raw
    return text, style


def _line_cmd(text: str, style: dict) -> bytes:
    """按样式拼装单行 ESC/POS 指令"""
    cmd = ALIGN_CMD[style["align"]]
    cmd += bytes([0x1d, 0x21, SIZE_MAP[style["size"]]])  # GS ! n
    cmd += BOLD_ON if style["bold"] else BOLD_OFF
    cmd += UNDERLINE_ON if style["underline"] else UNDERLINE_OFF
    cmd += REVERSE_ON if style["reverse"] else REVERSE_OFF
    cmd += text.encode("gbk")
    cmd += RESET_STYLE  # 复位所有样式
    cmd += LF
    return cmd


# ---------- 底层打印引擎 ----------

def _connect() -> socket.socket:
    """建立到打印机的连接"""
    return socket.create_connection((PRINTER_IP, PRINTER_PORT), timeout=5)


def print_lines(lines: List[str]) -> int:
    """完整打印流程: 先切纸 → 逐行打印(带样式) → 切纸

    Returns:
        实际发送的字节数
    """
    sock = _connect()
    total_bytes = 0
    try:

        # 1. 初始化
        sock.sendall(INIT)
        total_bytes += len(INIT)

        # 2. 逐行打印，全程不切纸
        for raw in lines:
            text, style = _parse_line(raw)
            cmd = _line_cmd(text, style)
            sock.sendall(cmd)
            total_bytes += len(cmd)

        # 3. 最后切纸
        sock.sendall(CUT)
        total_bytes += len(CUT)
    finally:
        sock.close()
    return total_bytes


# ---------- HTTP API 层 ----------

app = FastAPI(title="Printer Agent")


class PrintRequest(BaseModel):
    lines: List[str]


class PrintResponse(BaseModel):
    success: bool
    message: str
    line_count: int
    char_count: int
    byte_count: int


@app.post("/print", response_model=PrintResponse)
def print_api(req: PrintRequest) -> PrintResponse:
    if not req.lines:
        return PrintResponse(success=False, message="lines is empty",
                             line_count=0, char_count=0, byte_count=0)

    # 统计基于解析后的纯文本
    parsed = [_parse_line(raw) for raw in req.lines]
    line_count = len(parsed)
    char_count = sum(len(t) for t, _ in parsed)

    try:
        byte_count = print_lines(req.lines)
    except (socket.timeout, ConnectionError, OSError) as e:
        return PrintResponse(success=False, message=f"printer error: {e}",
                             line_count=line_count, char_count=char_count, byte_count=0)

    return PrintResponse(success=True, message="ok",
                         line_count=line_count, char_count=char_count, byte_count=byte_count)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
