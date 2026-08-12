"""企业微信回调事件处理：签名验证 + AES解密 + XML解析

依赖：pycryptodome (pip install pycryptodome)
若未安装，回调端点会返回明确错误，不影响其他功能。
"""
import hashlib
import base64
import struct
import logging
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

# 软依赖：pycryptodome
try:
    from Crypto.Cipher import AES
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
    AES = None  # type: ignore


def check_crypto_dependency() -> bool:
    """检查 pycryptodome 是否可用"""
    if not _HAS_CRYPTO:
        logging.error(
            "[回调] pycryptodome 未安装，回调功能不可用。"
            "请运行: pip install pycryptodome"
        )
        return False
    return True


def _verify_signature(token: str, timestamp: str, nonce: str, *extra: str) -> str:
    """计算企业微信回调签名

    签名算法：sha1(sorted([token, timestamp, nonce, *extra]).join(''))
    返回 SHA1 hex 摘要
    """
    sort_list = sorted([token, timestamp, nonce] + list(extra))
    raw = ''.join(sort_list).encode('utf-8')
    return hashlib.sha1(raw).hexdigest()


def _decrypt(encrypt_text: str, encoding_aes_key: str, corp_id: str) -> str:
    """AES-CBC 解密企业微信回调内容

    1. AES key = base64decode(EncodingAESKey + '=')
    2. IV = key[:16]
    3. 解密后去掉 PKCS7 padding
    4. 解析：random(16) + msg_len(4, big-endian) + msg + receiveid
    5. 校验 receiveid == corp_id
    """
    aes_key = base64.b64decode(encoding_aes_key + '=')
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    encrypted = base64.b64decode(encrypt_text)
    plain = cipher.decrypt(encrypted)

    # 去掉 PKCS7 padding
    pad_len = plain[-1]
    plain = plain[:-pad_len]

    # 解析结构：random(16) + msg_len(4) + msg + receiveid
    content_len = struct.unpack('!I', plain[16:20])[0]
    content = plain[20:20 + content_len].decode('utf-8')
    receive_id = plain[20 + content_len:].decode('utf-8')

    if receive_id != corp_id:
        raise ValueError(f"CorpId 校验失败: {receive_id} != {corp_id}")

    return content


def verify_url(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
    token: str,
    encoding_aes_key: str,
    corp_id: str,
) -> str:
    """URL 验证（GET 请求）

    企业微信后台配置回调URL时，会发送 GET 请求验证。
    验证签名后，解密 echostr 并返回明文。
    """
    if not check_crypto_dependency():
        raise RuntimeError("pycryptodome 未安装，无法验证回调URL")

    # 验证签名
    signature = _verify_signature(token, timestamp, nonce)
    if signature != msg_signature:
        raise ValueError(f"签名验证失败: {signature} != {msg_signature}")

    # 解密 echostr
    return _decrypt(echostr, encoding_aes_key, corp_id)


def parse_callback(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    token: str,
    encoding_aes_key: str,
    corp_id: str,
) -> Dict[str, Any]:
    """解析回调事件（POST 请求）

    1. 从 body XML 中提取 <Encrypt>
    2. 验证签名（含 encrypt 参数）
    3. 解密获取明文 XML
    4. 解析事件内容

    返回: {
        "event": str,           # 事件类型，如 "smart_sheet_change"
        "change_type": str,     # 变更类型，如 "update_record"
        "doc_id": str,          # 文档ID
        "sheet_id": str,        # 工作表ID
        "record_ids": List[str],# 记录ID列表
        "from_user": str,       # 操作人userid
    }
    """
    if not check_crypto_dependency():
        raise RuntimeError("pycryptodome 未安装，无法解析回调")

    # 1. 从 body 中提取 Encrypt
    body_text = body.decode('utf-8')
    root = ET.fromstring(body_text)
    encrypt_elem = root.find('Encrypt')
    if encrypt_elem is None or not encrypt_elem.text:
        raise ValueError("回调 XML 中缺少 <Encrypt> 元素")
    encrypt_text = encrypt_elem.text

    # 2. 验证签名（含 encrypt 参数）
    signature = _verify_signature(token, timestamp, nonce, encrypt_text)
    if signature != msg_signature:
        raise ValueError(f"签名验证失败: {signature} != {msg_signature}")

    # 3. 解密
    plain_xml = _decrypt(encrypt_text, encoding_aes_key, corp_id)

    # 4. 解析明文 XML
    plain_root = ET.fromstring(plain_xml)

    def _get_text(tag: str) -> str:
        elem = plain_root.find(tag)
        return elem.text if elem is not None and elem.text else ""

    event = _get_text('Event')
    change_type = _get_text('ChangeType')
    doc_id = _get_text('DocId')
    sheet_id = _get_text('SheetId')
    from_user = _get_text('FromUserName')

    # RecordId 可能有多条（批量变更）
    record_ids = [elem.text for elem in plain_root.findall('RecordId') if elem.text]

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
