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
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours')),
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
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours')),
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
            is_buffer INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours')),
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
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
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
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours')),
            FOREIGN KEY (operator_id) REFERENCES users(id)
        )
    ''')

    # 迁移：为 templates 表添加 template_content 列（存储模板内容 JSON）
    cursor.execute("PRAGMA table_info(templates)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if "template_content" not in existing_columns:
        cursor.execute("ALTER TABLE templates ADD COLUMN template_content TEXT")
        logging.info("数据库迁移：templates 表新增 template_content 列")

    # 迁移：为 sheets 表添加 is_buffer 列（标记是否属于 buffer 范围）
    cursor.execute("PRAGMA table_info(sheets)")
    existing_sheets_columns = [row[1] for row in cursor.fetchall()]
    if "is_buffer" not in existing_sheets_columns:
        cursor.execute("ALTER TABLE sheets ADD COLUMN is_buffer INTEGER DEFAULT 0")
        logging.info("数据库迁移：sheets 表新增 is_buffer 列")
        # 迁移已有数据：按当前时间的 buffer 范围标记（今天-7天 ~ 今天+3个月）
        cursor.execute('''
            UPDATE sheets
            SET is_buffer = 1
            WHERE sheet_date BETWEEN date(datetime('now', '+8 hours'), '-7 days')
                                 AND date(datetime('now', '+8 hours'), '+3 months')
        ''')
        updated = cursor.rowcount
        logging.info(f"数据库迁移：已将 {updated} 条 sheets 记录标记为 buffer")

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

def insert_sheet(doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, created_by, is_buffer: int = 0):
    """插入普通工作表记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sheets (doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, is_buffer, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (doc_id, sheet_id, sheet_name, sheet_date, session_type, weekday, template_id, is_buffer, created_by))
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


def sheet_name_exists(sheet_name: str) -> bool:
    """检查指定的工作表名称是否已存在（用于防重复）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM sheets WHERE sheet_name = ? LIMIT 1', (sheet_name,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_sheets_by_date(sheet_date: str, doc_id: str = None) -> list:
    """查询指定日期的工作表列表（用于检查某日期下哪些 session_type 已存在）"""
    conn = get_connection()
    cursor = conn.cursor()
    if doc_id:
        cursor.execute(
            'SELECT * FROM sheets WHERE sheet_date = ? AND doc_id = ? ORDER BY id',
            (sheet_date, doc_id)
        )
    else:
        cursor.execute(
            'SELECT * FROM sheets WHERE sheet_date = ? ORDER BY id',
            (sheet_date,)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_existing_sheet_names(names: list) -> list:
    """批量查询已存在的 sheet_name，返回已存在的列表（用于一次查询多个名字）"""
    if not names:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(names))
    cursor.execute(
        f'SELECT sheet_name FROM sheets WHERE sheet_name IN ({placeholders})',
        names
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["sheet_name"] for r in rows]


# ================= 删除相关 =================
def get_sheet_by_name(sheet_name: str) -> dict:
    """按 sheet_name 查询单条工作表记录，不存在返回 None"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sheets WHERE sheet_name = ? LIMIT 1', (sheet_name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_sheet_by_id(sheet_id: str) -> dict:
    """按 sheet_id 查询单条工作表记录，不存在返回 None"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sheets WHERE sheet_id = ? LIMIT 1', (sheet_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_sheet_by_date_and_session(sheet_date: str, session_type: str, doc_id: str = None) -> dict:
    """按日期 + 场次定位唯一工作表（同一个 doc 下 date + session_type 是唯一键）
    session_type: 'lunch' 或 'dinner'（传入时已标准化）
    sheet_date: 'YYYY-MM-DD'（传入时已标准化）
    doc_id: 可选，若不指定则查第一个 doc
    不存在返回 None"""
    conn = get_connection()
    cursor = conn.cursor()
    if doc_id:
        cursor.execute(
            'SELECT * FROM sheets WHERE sheet_date = ? AND session_type = ? AND doc_id = ? LIMIT 1',
            (sheet_date, session_type, doc_id)
        )
    else:
        cursor.execute(
            'SELECT * FROM sheets WHERE sheet_date = ? AND session_type = ? LIMIT 1',
            (sheet_date, session_type)
        )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_sheets_by_doc(doc_id: str) -> list:
    """查询指定文档下所有普通工作表（不含模板），用于排序计算
    返回 [{id, sheet_id, sheet_name, sheet_date, session_type}, ...]
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, sheet_id, sheet_name, sheet_date, session_type '
        'FROM sheets WHERE doc_id = ?',
        (doc_id,)
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def delete_sheet_by_id(sheet_id: str) -> int:
    """按 sheet_id 删除工作表记录，返回被删除的行数"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sheets WHERE sheet_id = ?', (sheet_id,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    return deleted


def is_template_sheet(sheet_id: str) -> bool:
    """检查指定 sheet_id 是否为模板工作表"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM templates WHERE sheet_id = ? LIMIT 1', (sheet_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


# ==================== buffer 自动管理相关 ====================

def update_buffer_flags(buffer_start: str, buffer_end: str) -> int:
    """
    根据 buffer 时间范围批量更新 is_buffer 字段：
    - sheet_date 在 [buffer_start, buffer_end] 之间 → is_buffer=1
    - 不在范围内 → is_buffer=0
    返回被更新的行数
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE sheets SET is_buffer = 1 WHERE sheet_date BETWEEN ? AND ?',
        (buffer_start, buffer_end)
    )
    marked = cursor.rowcount
    cursor.execute(
        'UPDATE sheets SET is_buffer = 0 WHERE sheet_date NOT BETWEEN ? AND ?',
        (buffer_start, buffer_end)
    )
    unmarked = cursor.rowcount
    conn.commit()
    conn.close()
    return marked + unmarked


def get_expired_discrete_sheets(cutoff_date: str) -> list:
    """
    获取需要删除的过期离散工作表列表：
    - sheet_date < cutoff_date（严格小于今天）
    - AND is_buffer = 0
    返回 [dict(sheet_id, sheet_name, sheet_date)]
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT sheet_id, sheet_name, sheet_date FROM sheets WHERE sheet_date < ? AND is_buffer = 0',
        (cutoff_date,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_buffer_max_date() -> str:
    """
    获取数据库中 buffer 实际上界（is_buffer=1 的记录中最大的 sheet_date）。
    如果没有 buffer 记录，返回 None。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(sheet_date) AS md FROM sheets WHERE is_buffer = 1")
    row = cursor.fetchone()
    conn.close()
    return row["md"] if row else None


def count_sheets_and_templates() -> int:
    """统计智能表格中已有的总子表数：sheets记录数 + templates记录数（用于255限额检查）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sheets")
    s = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM templates")
    t = cursor.fetchone()[0]
    conn.close()
    return s + t
