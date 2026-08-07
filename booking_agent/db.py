import os
import sqlite3
import logging
import json  # 新增导入
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "booking.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    cursor = conn.cursor()

    # 智能表格表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL UNIQUE,
            doc_name TEXT NOT NULL,
            doc_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL
        )
    ''')

    # 模板工作表表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL UNIQUE,
            sheet_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES docs(doc_id)
        )
    ''')

    # 普通工作表表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL UNIQUE,
            sheet_name TEXT NOT NULL,
            sheet_date TEXT NOT NULL,
            session_type TEXT NOT NULL CHECK (session_type IN ('lunch', 'dinner')),
            weekday TEXT NOT NULL,
            template_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES docs(doc_id),
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    ''')

    # 人员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userid TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 操作日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            operation_type TEXT NOT NULL,
            target_type TEXT NOT NULL CHECK (target_type IN ('doc', 'sheet', 'template')),
            detail TEXT,
            error_msg TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (operator_id) REFERENCES users(id)
        )
    ''')

    # 迁移：为 templates 表添加 template_content 列（存储模板内容 JSON）
    cursor.execute("PRAGMA table_info(templates)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if "template_content" not in existing_columns:
        cursor.execute("ALTER TABLE templates ADD COLUMN template_content TEXT")
        logging.info("数据库迁移：templates 表新增 template_content 列")

    conn.commit()
    conn.close()
    logging.info("数据库初始化完成")

def insert_doc(doc_id, doc_name, doc_url, created_by):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO docs (doc_id, doc_name, doc_url, created_by)
        VALUES (?, ?, ?, ?)
    ''', (doc_id, doc_name, doc_url, created_by))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def insert_template(doc_id, sheet_id, sheet_name, created_by, template_content=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO templates (doc_id, sheet_id, sheet_name, created_by, template_content)
        VALUES (?, ?, ?, ?, ?)
    ''', (doc_id, sheet_id, sheet_name, created_by, json.dumps(template_content, ensure_ascii=False) if template_content else None))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_first_doc():
    """获取第一个智能表格记录（用于后续操作）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT doc_id FROM docs LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    return row['doc_id'] if row else None

def insert_user(userid, name):
    """插入或忽略用户，返回id"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (userid, name) VALUES (?, ?)
    ''', (userid, name))
    conn.commit()
    cursor.execute('SELECT id FROM users WHERE userid = ?', (userid,))
    row = cursor.fetchone()
    conn.close()
    return row['id']

def insert_log(operator_id, target_id, operation_type, target_type, detail=None, error_msg=None):
    # 将 detail 转换为 JSON 字符串（如果是 dict 或 list）
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    # 同样处理 error_msg（虽然通常为字符串）
    if error_msg is not None and not isinstance(error_msg, str):
        error_msg = json.dumps(error_msg, ensure_ascii=False)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO logs (operator_id, target_id, operation_type, target_type, detail, error_msg)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (operator_id, target_id, operation_type, target_type, detail, error_msg))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_template(template_id):
    """根据 id 获取模板记录（含 template_content 解析后的 dict）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM templates WHERE id = ?', (template_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        if result.get("template_content"):
            result["template_content"] = json.loads(result["template_content"])
        return result
    return None

def get_first_template():
    """获取第一条模板记录（含 template_content 解析后的 dict），用于批量创建工作表"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM templates ORDER BY id LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        if result.get("template_content"):
            result["template_content"] = json.loads(result["template_content"])
        return result
    return None

def insert_sheet(doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, created_by):
    """插入普通工作表记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sheets (doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, created_by))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_templates(doc_id=None):
    """获取模板列表，可按 doc_id 过滤"""
    conn = get_connection()
    cursor = conn.cursor()
    if doc_id:
        cursor.execute('SELECT * FROM templates WHERE doc_id = ? ORDER BY id', (doc_id,))
    else:
        cursor.execute('SELECT * FROM templates ORDER BY id')
    rows = cursor.fetchall()
    conn.close()
    results = []
    for row in rows:
        item = dict(row)
        if item.get("template_content"):
            item["template_content"] = json.loads(item["template_content"])
        results.append(item)
    return results