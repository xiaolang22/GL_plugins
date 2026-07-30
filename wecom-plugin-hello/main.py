import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LIB_PATH = os.path.join(os.path.dirname(__file__), '..', 'weworkapi_python-master', 'callback_python3')
sys.path.insert(0, LIB_PATH)

from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse
import uvicorn
from WXBizMsgCrypt import WXBizMsgCrypt

app = FastAPI()

TOKEN = "4tGHzTEzQVLNykfP6f8"
ENCODING_AES_KEY = "phrLP0vxU8RxeJ5cDTz338qkz8cNIVXtzSlWm9Oijkd"
wxcpt = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, "")  # 智能机器人必须传空字符串


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
    logging.info(f"echostr (前50字符): {echostr[:50]}...")
    
    try:
        ret, sReplyEchoStr = wxcpt.VerifyURL(msg_signature, timestamp, nonce, echostr)
        logging.info(f"ret 返回值: {ret}")
        logging.info(f"sReplyEchoStr 类型: {type(sReplyEchoStr)}")
        
        if ret != 0:
            logging.error(f"验证失败，错误码: {ret}")
            return PlainTextResponse(content="", status_code=200)
        
        if isinstance(sReplyEchoStr, bytes):
            response = sReplyEchoStr.decode('utf-8').strip()
        else:
            response = sReplyEchoStr.strip()
        
        logging.info(f"返回内容: {response}")
        logging.info(f"返回内容长度: {len(response)}")
        return PlainTextResponse(content=response, status_code=200)
    except Exception as e:
        logging.error(f"异常: {e}")
        return PlainTextResponse(content="", status_code=200)


@app.post("/test")
async def hello_plugin():
    return {"content": "Hello, World!"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)