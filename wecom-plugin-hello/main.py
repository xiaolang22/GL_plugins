import sys
import os
import logging
import json
import xml.etree.ElementTree as ET
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import PlainTextResponse
import uvicorn

LIB_PATH = os.path.join(os.path.dirname(__file__), '..', 'weworkapi_python-master', 'callback_python3')
sys.path.insert(0, LIB_PATH)

from WXBizMsgCrypt import WXBizMsgCrypt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

TOKEN = "4tGHzTEzQVLNykfP6f8"
ENCODING_AES_KEY = "phrLP0vxU8RxeJ5cDTz338qkz8cNIVXtzSlWm9Oijkd"
CORP_ID = ""

wxcpt = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORP_ID)


@app.get("/test")
async def verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...)
):
    logging.info("=== 收到验证请求 ===")
    logging.info(f"msg_signature: {msg_signature}")
    logging.info(f"timestamp: {timestamp}")
    logging.info(f"nonce: {nonce}")
    
    try:
        ret, sReplyEchoStr = wxcpt.VerifyURL(msg_signature, timestamp, nonce, echostr)
        if ret != 0:
            logging.error(f"验证失败，错误码: {ret}")
            return PlainTextResponse(content="", status_code=200)
        
        if isinstance(sReplyEchoStr, bytes):
            response = sReplyEchoStr.decode('utf-8').strip()
        else:
            response = sReplyEchoStr.strip()
        
        logging.info(f"返回内容: {response}")
        return PlainTextResponse(content=response, status_code=200)
    except Exception as e:
        logging.error(f"验证异常: {e}")
        return PlainTextResponse(content="", status_code=200)


@app.post("/test")
async def handle_plugin(request: Request):
    # 1. 获取 URL 参数
    query_params = request.query_params
    msg_signature = query_params.get("msg_signature")
    timestamp = query_params.get("timestamp")
    nonce = query_params.get("nonce")
    
    if not all([msg_signature, timestamp, nonce]):
        logging.error("缺少必要参数")
        return Response(content="", status_code=400)
    
    # 2. 读取请求体（加密的 JSON）
    body_json_str = await request.body()
    logging.info(f"收到加密请求体: {body_json_str[:200]}...")
    
    # 3. 解析 JSON，提取 encrypt 字段，并构造 XML 格式（因为当前库只支持 XML）
    try:
        body_dict = json.loads(body_json_str)
        encrypt = body_dict.get("encrypt", "")
        if not encrypt:
            logging.error("请求体中缺少 encrypt 字段")
            return Response(content="", status_code=200)
        
        # 构造企业微信回调 XML 格式
        xml_body = f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>"
        xml_body_bytes = xml_body.encode('utf-8')
        logging.info(f"构造的 XML: {xml_body[:200]}...")
        
        # 4. 解密请求（现在传入 XML 格式）
        ret, decrypted_msg = wxcpt.DecryptMsg(xml_body_bytes, msg_signature, timestamp, nonce)
        if ret != 0:
            logging.error(f"解密失败，错误码: {ret}")
            return Response(content="", status_code=200)
        
        logging.info(f"解密后的明文: {decrypted_msg}")
        
        # 5. 解析明文（此时是 JSON 格式的字符串）
        msg_data = json.loads(decrypted_msg)
        user_content = msg_data.get("text", {}).get("content", "")
        logging.info(f"用户说: {user_content}")
        
    except json.JSONDecodeError as e:
        logging.error(f"JSON 解析失败: {e}")
        return Response(content="", status_code=200)
    except Exception as e:
        logging.error(f"处理请求异常: {e}")
        return Response(content="", status_code=200)
    
    # 6. 构造回复内容
    reply_text = "Hello, World!"
    
    # 7. 构造回复 JSON
    reply_json = {
        "msgtype": "text",
        "text": {"content": reply_text}
    }
    
    # 8. 加密回复
    reply_str = json.dumps(reply_json, ensure_ascii=False)
    ret, encrypted_reply = wxcpt.EncryptMsg(reply_str, nonce, timestamp)
    if ret != 0:
        logging.error(f"加密回复失败，错误码: {ret}")
        return Response(content="", status_code=200)
    
    logging.info(f"加密后的回复: {encrypted_reply[:200]}...")
    
    # 9. 返回加密后的回复
    return Response(content=encrypted_reply, media_type="application/json")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)