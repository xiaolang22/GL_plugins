"""打印机控制服务 - 通过 TCP 9100 端口发送 ESC/POS 指令，对外暴露 HTTP /print 接口"""
import socket
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

PRINTER_IP = "127.0.0.1"
PRINTER_PORT = 9101  # ESC/POS 默认端口

# 常用 ESC/POS 指令
INIT = b"\x1b\x40"           # 初始化打印机
LF = b"\n"                   # 换行
ALIGN_C = b"\x1b\x61\x01"    # 居中
ALIGN_L = b"\x1b\x61\x00"    # 左对齐
ALIGN_R = b"\x1b\x61\x02"    # 右对齐
BOLD_ON = b"\x1b\x21\x08"    # 加粗
BOLD_OFF = b"\x1b\x21\x00"   # 取消加粗
CUT = b"\x1d\x56\x42\x00"    # 切纸


# ---------- 底层打印引擎 ----------

def _connect() -> socket.socket:
    """建立到打印机的连接"""
    return socket.create_connection((PRINTER_IP, PRINTER_PORT), timeout=5)


def print_lines(lines: List[str]) -> int:
    """完整打印流程：先切纸 → 逐行打印 → 切纸

    Returns:
        实际发送的字节数
    """
    sock = _connect()
    total_bytes = 0
    try:
        # # 1. 先切纸（清理上次残留）
        # sock.sendall(CUT)
        # total_bytes += len(CUT)
        # 2. 初始化
        sock.sendall(INIT)
        total_bytes += len(INIT)

        # 3. 逐行打印，全程不切纸
        for text in lines:
            cmd = ALIGN_L + text.encode("gbk") + LF
            sock.sendall(cmd)
            total_bytes += len(cmd)

        # 4. 最后切纸
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

    line_count = len(req.lines)
    char_count = sum(len(s) for s in req.lines)

    try:
        byte_count = print_lines(req.lines)
    except (socket.timeout, ConnectionError, OSError) as e:
        return PrintResponse(success=False, message=f"printer error: {e}",
                             line_count=line_count, char_count=char_count, byte_count=0)

    return PrintResponse(success=True, message="ok",
                         line_count=line_count, char_count=char_count, byte_count=byte_count)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
