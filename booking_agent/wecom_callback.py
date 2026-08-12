"""企业微信回调事件处理：使用官方 SDK WXBizMsgCrypt 做签名验证 + AES解密 + XML解析

直接复用项目内已跑通的企业微信官方 Python SDK：
  GL_plugins/weworkapi_python-master/callback_python3/

参考 test/main.py 的实现（已验证通过企业微信后台 URL 验证）。
"""
import os
import sys
import logging
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

# ========== 引入官方 SDK ==========
# SDK 路径相对于 booking_agent/ 目录：../weworkapi_python-master/callback_python3
_SDK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "weworkapi_python-master", "callback_python3")
_SDK_DIR = os.path.normpath(_SDK_DIR)
if _SDK_DIR not in sys.path:
    sys.path.insert(0, _SDK_DIR)

try:
    from WXBizMsgCrypt import WXBizMsgCrypt  # 官方 SDK 类
    _HAS_SDK = True
except ImportError as e:
    WXBizMsgCrypt = None  # type: ignore
    _HAS_SDK = False
    logging.error(
        f"[回调] 无法导入官方 SDK WXBizMsgCrypt: {e}。"
        f"请确认目录存在: {_SDK_DIR}"
    )


def check_dependency() -> bool:
    """检查回调依赖是否就绪：官方 SDK + pycryptodome"""
    if not _HAS_SDK:
        logging.error("[回调] 官方 SDK WXBizMsgCrypt 未导入，回调功能不可用")
        return False
    # WXBizMsgCrypt 内部 import Crypto.Cipher，若 pycryptodome 未安装会在调用时才报错
    # 这里提前探测一次
    try:
        from Crypto.Cipher import AES  # noqa: F401
    except ImportError:
        logging.error(
            "[回调] pycryptodome 未安装，回调功能不可用。"
            "请运行: pip install pycryptodome"
        )
        return False
    return True


def make_crypt(token: str, encoding_aes_key: str, corp_id: str):
    """创建官方 SDK WXBizMsgCrypt 实例"""
    if not check_dependency():
        raise RuntimeError("回调依赖未就绪")
    return WXBizMsgCrypt(token, encoding_aes_key, corp_id)


def verify_url(
    wxcpt,
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
) -> str:
    """URL 验证（GET 请求）

    企业微信后台配置回调URL时，会发送 GET 请求验证。
    调用官方 VerifyURL，成功返回解密后的明文 echostr，失败抛出异常。
    """
    ret, sReplyEchoStr = wxcpt.VerifyURL(msg_signature, timestamp, nonce, echostr)
    if ret != 0:
        raise ValueError(f"VerifyURL 失败，错误码: {ret}")

    if isinstance(sReplyEchoStr, bytes):
        return sReplyEchoStr.decode("utf-8").strip()
    return str(sReplyEchoStr).strip()


def parse_callback(
    wxcpt,
    msg_signature: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> Dict[str, Any]:
    """解析回调事件（POST 请求）

    1. 调用官方 SDK 的 DecryptMsg 完成验签 + 解密
    2. 解析明文 XML，返回结构化字典

    返回: {
        "event": str,           # 事件类型，如 "smart_sheet_change"
        "change_type": str,     # 变更类型，如 "update_record"
        "doc_id": str,          # 文档ID
        "sheet_id": str,        # 工作表ID
        "record_ids": List[str],# 记录ID列表
        "from_user": str,       # 操作人userid
    }
    """
    # SDK 的 DecryptMsg 需要传入 XML 格式（包含 <Encrypt> 节点）的字节串
    # 企业微信回调 POST 的 body 默认就是这种 XML，可以直接传
    ret, decrypted_msg = wxcpt.DecryptMsg(body, msg_signature, timestamp, nonce)
    if ret != 0:
        raise ValueError(f"DecryptMsg 失败，错误码: {ret}")

    # 明文 XML 解析
    if isinstance(decrypted_msg, bytes):
        plain_text = decrypted_msg.decode("utf-8")
    else:
        plain_text = str(decrypted_msg)

    root = ET.fromstring(plain_text)

    def _get_text(tag: str) -> str:
        elem = root.find(tag)
        if elem is None:
            return ""
        if elem.text is None:
            return ""
        return elem.text

    event = _get_text("Event")
    change_type = _get_text("ChangeType")
    doc_id = _get_text("DocId")
    sheet_id = _get_text("SheetId")
    from_user = _get_text("FromUserName")

    record_ids = [elem.text for elem in root.findall("RecordId") if elem.text]

    result = {
        "event": event,
        "change_type": change_type,
        "doc_id": doc_id,
        "sheet_id": sheet_id,
        "record_ids": record_ids,
        "from_user": from_user,
    }

    logging.info(
        f"[回调] 收到事件: event={event}, change_type={change_type}, "
        f"doc_id={doc_id}, sheet_id={sheet_id}, "
        f"record_ids={len(record_ids)}条, from_user={from_user}"
    )
    return result
