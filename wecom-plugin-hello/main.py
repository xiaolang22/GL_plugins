import sys
import os
import logging
import json
import httpx
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
    
    # 3. 解析 JSON，提取 encrypt 字段，构造 XML 格式
    try:
        body_dict = json.loads(body_json_str)
        encrypt = body_dict.get("encrypt", "")
        if not encrypt:
            logging.error("请求体中缺少 encrypt 字段")
            return Response(content="", status_code=200)
        
        xml_body = f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>"
        xml_body_bytes = xml_body.encode('utf-8')
        
        # 4. 解密请求
        ret, decrypted_msg = wxcpt.DecryptMsg(xml_body_bytes, msg_signature, timestamp, nonce)
        if ret != 0:
            logging.error(f"解密失败，错误码: {ret}")
            return Response(content="", status_code=200)
        
        # 5. 解析明文 JSON
        msg_data = json.loads(decrypted_msg)
        user_content = msg_data.get("text", {}).get("content", "")
        response_url = msg_data.get("response_url", "")
        logging.info(f"用户说: {user_content}")
        logging.info(f"response_url: {response_url}")
        
        # 6. 【关键】主动回复：通过 response_url 发送消息
        # 先返回 200，表示已收到请求
        # 然后异步发送回复（这里为了简单，同步发送，实际可放在后台任务中）
        if response_url:
            reply_payload = {
                "msgtype": "markdown",
                "markdown": {
                "content": "Hello, World!"
            }
            }
            
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(
                        response_url,
                        json=reply_payload,
                        headers={"Content-Type": "application/json"}
                    )
                    logging.info(f"主动回复状态码: {resp.status_code}")
                    logging.info(f"主动回复响应: {resp.text}")
                except Exception as e:
                    logging.error(f"主动回复失败: {e}")
        else:
            logging.warning("没有 response_url，无法主动回复")
        
        # 7. 直接返回 200（此时回复已通过 response_url 发送）
        return Response(content="", status_code=200)
        
    except json.JSONDecodeError as e:
        logging.error(f"JSON 解析失败: {e}")
        return Response(content="", status_code=200)
    except Exception as e:
        logging.error(f"处理请求异常: {e}")
        return Response(content="", status_code=200)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)