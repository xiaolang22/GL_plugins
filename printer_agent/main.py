"""打印机控制服务 - 通过 TCP 9100 端口发送 ESC/POS 指令，对外暴露 HTTP /print、/print_batch 接口

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

LINE_SPACING_DEFAULT = b"\x1b\x32"  # 恢复默认行距 ESC 2

# 每行打印后复位所有样式(含行距)，避免污染下一行
RESET_STYLE = (
    BOLD_OFF + UNDERLINE_OFF + REVERSE_OFF
    + b"\x1d\x21\x00"   # 复位字号
    + LINE_SPACING_DEFAULT  # 复位行距
)


# ---------- 行解析与指令拼装 ----------

def _parse_line(raw: str) -> tuple:
    """解析 '文本|center,bold,spacing:30' → ('文本', style_dict)"""
    style = {
        "align": "left",
        "size": "normal",
        "bold": False,
        "underline": False,
        "reverse": False,
        "spacing": None,   # None 表示用默认行距, 不发指令; 整数则发 ESC 3 n
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
            elif token.startswith("spacing:"):
                # spacing:N  N∈[0,255] 单位 1/216 英寸
                try:
                    n = int(token.split(":", 1)[1])
                    if 0 <= n <= 255:
                        style["spacing"] = n
                except ValueError:
                    pass  # 非法值静默忽略
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
    # 行距: 仅当显式指定时设置 (ESC 3 n), 不指定则保留打印机当前默认
    if style["spacing"] is not None:
        cmd += bytes([0x1b, 0x33, style["spacing"]])
    cmd += text.encode("gbk", errors="replace")  # 不可编码字符替换为 ?，避免整次打印失败
    cmd += LF           # 先按设置的行距换行(LF 时 ESC 3 n 才生效)
    cmd += RESET_STYLE  # 换行后再复位样式(含行距), 避免污染下一行
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


# ---------- 批量打印 ----------

class BatchSheet(BaseModel):
    index: int          # 调用方指定的单据序号，结果中原样回传
    lines: List[str]    # 该张单的打印内容，格式与 /print 的 lines 一致


class BatchPrintRequest(BaseModel):
    sheets: List[BatchSheet]


class SheetPrintResult(BaseModel):
    index: int
    success: bool
    message: str
    line_count: int
    char_count: int
    byte_count: int


class BatchPrintResponse(BaseModel):
    success: bool        # 全部单成功才为 True
    message: str
    total: int
    success_count: int
    fail_count: int
    results: List[SheetPrintResult]   # 顺序与输入 sheets 一致


def _send_sheet(sock: socket.socket, lines: List[str]) -> int:
    """在已建立的连接上发送单张打印单（不含 INIT）：逐行打印 → 切纸。

    返回发送字节数。每行样式均显式设置并在换行后复位（见 RESET_STYLE），
    因此单据之间不需要重发 INIT。
    """
    total_bytes = 0
    for raw in lines:
        text, style = _parse_line(raw)
        cmd = _line_cmd(text, style)
        sock.sendall(cmd)
        total_bytes += len(cmd)
    sock.sendall(CUT)
    total_bytes += len(CUT)
    return total_bytes


def print_batch_sheets(sheets: List[BatchSheet]) -> List[SheetPrintResult]:
    """串行批量打印：整批共用一条 TCP 连接，单据之间以 CUT 切纸分隔。

    为什么不能每张单新建连接 + 重发 INIT（实测 3 张单只出 1 张纸）：
    - 9101 端口的打印代理按"连接"投递打印任务，快速连续建连时新连接
      会冲掉上一条连接尚未出纸的任务；
    - INIT(ESC @) 会清空打印机打印缓冲，后一张单的 INIT 会清掉前一张
      单缓冲中尚未打完的内容。
    因此整批复用一条连接，仅在连接建立（及断线重连）时发一次 INIT。

    - 严格串行，按输入顺序逐张发送，每张单末尾 CUT 独立切纸；
    - 单张失败（内容为空 / 超时 / 断连等）只记录该张失败结果，不中断
      后续单据（best-effort）；断连后下一张单自动重建连接；
    - 不并发：单台物理打印机，并发会导致 ESC/POS 指令交错。
    """
    results: List[SheetPrintResult] = []
    sock = None  # type: socket.socket | None
    try:
        for sheet in sheets:
            if not sheet.lines:
                results.append(SheetPrintResult(
                    index=sheet.index, success=False, message="lines is empty",
                    line_count=0, char_count=0, byte_count=0))
                continue

            # 统计基于解析后的纯文本
            parsed = [_parse_line(raw) for raw in sheet.lines]
            line_count = len(parsed)
            char_count = sum(len(t) for t, _ in parsed)

            try:
                if sock is None:
                    sock = _connect()
                    sock.sendall(INIT)  # 仅连接建立时初始化一次
                    byte_count = len(INIT) + _send_sheet(sock, sheet.lines)
                else:
                    byte_count = _send_sheet(sock, sheet.lines)
            except (socket.timeout, ConnectionError, OSError) as e:
                # 连接已不可用：丢弃坏连接，下一张单重建连接后继续
                try:
                    sock.close()
                except OSError:
                    pass
                sock = None
                results.append(SheetPrintResult(
                    index=sheet.index, success=False, message=f"printer error: {e}",
                    line_count=line_count, char_count=char_count, byte_count=0))
                continue

            results.append(SheetPrintResult(
                index=sheet.index, success=True, message="ok",
                line_count=line_count, char_count=char_count, byte_count=byte_count))
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return results


@app.post("/print_batch", response_model=BatchPrintResponse)
def print_batch_api(req: BatchPrintRequest) -> BatchPrintResponse:
    if not req.sheets:
        return BatchPrintResponse(
            success=False, message="sheets is empty",
            total=0, success_count=0, fail_count=0, results=[])

    results = print_batch_sheets(req.sheets)
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count
    return BatchPrintResponse(
        success=(fail_count == 0),
        message=f"total={len(results)}, success={success_count}, failed={fail_count}",
        total=len(results), success_count=success_count,
        fail_count=fail_count, results=results)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
