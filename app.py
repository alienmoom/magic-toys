

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import random
import re
import socket
import ssl
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import uuid


try:
    import pymysql
except ImportError:
    pymysql = None

try:
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import (
        ConnectionTerminated,
        DataReceived,
        PingReceived,
        RequestReceived,
        StreamEnded,
        StreamReset,
        WindowUpdated,
    )
    from h2.exceptions import FlowControlError
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False


try:
    # Debian 打包的 pycryptodome 使用 Cryptodome 命名空间（避免与旧 crypto 冲突）
    from Cryptodome.Cipher import AES as _FAST_AES
    _FAST_AES_AVAILABLE = True
except ImportError:
    try:
        from Crypto.Cipher import AES as _FAST_AES
        _FAST_AES_AVAILABLE = True
    except ImportError:
        _FAST_AES = None
        _FAST_AES_AVAILABLE = False


def _init_app_key():
    """获取或自动生成核心鉴权 UUID (APP_KEY)。
    
    规则：
    1. 优先读取环境变量 APP_KEY（若非空则直接使用）；
    2. 若环境变量留空，尝试从本地 config.json (或旧版 settings.json/advices.json) 中读取已持久化的 appKey；
    3. 若仍无，则调用 uuid.uuid4() 自动动态生成全新的标准 UUID v4，并持久化到本地 config.json 中，打印醒目提示。
    """
    env_key = (os.environ.get("APP_KEY") or "").strip()
    if env_key:
        return env_key

    # 尝试从本地配置文件读取历史生成的 UUID
    config_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "advices.json"),
    ]
    for cp in config_paths:
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                saved_key = (cfg_data.get("appKey") or cfg_data.get("uuid") or "").strip()
                if saved_key:
                    print(f"[UUID] 从本地配置文件加载已保存的 UUID: {saved_key}", flush=True)
                    return saved_key
            except Exception:
                pass

    # 自动生成新的标准 UUID v4
    generated_uuid = str(uuid.uuid4())
    print(f"\n{'='*60}", flush=True)
    print(f"[UUID] 检测到 APP_KEY 环境变量留空，已自动为您生成全新专属 UUID:", flush=True)
    print(f"       -> {generated_uuid}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # 尝试自动写入 config.json 保证重启后 UUID 不变
    try:
        cfg_file = config_paths[0]
        cfg_data = {}
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
            except Exception:
                cfg_data = {}
        cfg_data["appKey"] = generated_uuid
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[UUID] 保存自动生成的 UUID 到本地失败: {e}", flush=True)

    return generated_uuid


# 节点验证 UUID：客户端连接时使用的 VLESS/Trojan 密码（若留空则自动生成专属 UUID）
APP_KEY = _init_app_key()

# 监控上报服务地址（可选）：设置后启动时会下载并运行 monitor 客户端，向该地址上报
MONITOR_HOST = os.environ.get("MONITOR_HOST") or ""

# 监控上报端口（可选）：443/8443 等标准端口会自动启用 TLS
MONITOR_PORT = os.environ.get("MONITOR_PORT") or ""

# 监控上报密钥（可选）：monitor 客户端的连接密码
MONITOR_KEY = os.environ.get("MONITOR_KEY") or ""

# 直连域名（可选）：订阅链接使用的直接连接域名/主机
DIRECT_DOMAIN = os.environ.get("DIRECT_DOMAIN") or ""

# 套CDN域名（可选）：订阅链接使用的套CDN域名（配合优选 IP 使用）
GATEWAY_DOMAIN = os.environ.get("GATEWAY_DOMAIN") or ""

# 优选 IP（可选）：手动指定的首选节点 IP，作为默认节点地址
PREFERRED_IP = os.environ.get("PREFERRED_IP") or ""

# 自动上报（可选）：设为 1/true 时向外部服务自动注册访问地址（GATEWAY/DIRECT 域名）
AUTO_PING = os.environ.get("AUTO_PING") or ""

# 传输路径（可选）：WS/gRPC/XHTTP 传输层服务路径，默认取 UUID 前 8 位（如 317ad2e2）
API_PATH = os.environ.get("API_PATH") or APP_KEY.replace("-", "")[:8]

# 订阅接口路径（可选）：默认 /sublink，返回 base64 编码的订阅链接列表
SUBLINK_PATH = os.environ.get("SUBLINK_PATH") or os.environ.get("FEED_PATH") or "sublink"
FEED_PATH = SUBLINK_PATH

# 节点名称前缀（可选）：出现在订阅链接 #备注 中，便于客户端识别（留空则不加前缀）
NAME = os.environ.get("NAME") or ""

# 监听端口（可选）：服务绑定的端口，默认 3000
PORT = int(os.environ.get("PORT") or 3000)


def _env_flag(name, default):
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# 三种节点协议的默认开关（可选）：PROTO_A_ENABLED=VLESS，PROTO_B_ENABLED=Trojan，
# PROTO_C_ENABLED=SS；设为 1/true 启用，0/false 禁用
DEFAULT_MODES = {
    "a": _env_flag("PROTO_A_ENABLED", True),
    "b": _env_flag("PROTO_B_ENABLED", True),
    "c": _env_flag("PROTO_C_ENABLED", True),
}

# 传输方式（单选）：ws / grpc / xhttp，默认 WS；
# CONN_WS_ENABLED / CONN_GRPC_ENABLED / CONN_XHTTP_ENABLED 可覆盖默认选择（同时启用时取 ws 优先）
DEFAULT_CONN_MODES = {
    "ws": _env_flag("CONN_WS_ENABLED", True),
    "grpc": _env_flag("CONN_GRPC_ENABLED", False),
    "xhttp": _env_flag("CONN_XHTTP_ENABLED", False),
}


# 节点配置与设置页面路径（可选）：默认 /settings
SETTINGS_PATH = os.environ.get("SETTINGS_PATH") or os.environ.get("ADVICES_PATH") or "settings"
ADVICES_PATH = SETTINGS_PATH
# 配置存储方式（可选）：database/db 表示存数据库；留空则只存内存/本地文件
SETTINGS_STORE = (os.environ.get("SETTINGS_STORE") or os.environ.get("ADVICES_STORE") or "").strip().lower()
ADVICES_STORE = SETTINGS_STORE
# 无数据库时的本地持久化配置文件（与 app.py 同目录，统一为 config.json）
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SETTINGS_FILE = CONFIG_FILE
ADVICES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "advices.json")
OLD_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
# 数据库连接串（可选）：如 mysql://user:pass@host/db 或 postgres://user:pass@host/db
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
# 数据库类型（可选）：mysql 或 postgres；通常由 DATABASE_URL 自动识别，可不填
DB_TYPE = (os.environ.get("DB_TYPE") or os.environ.get("DATABASE_TYPE") or "").strip().lower()
if DB_TYPE not in ("mysql", "postgres"):
    DB_TYPE = "mysql"


def _parse_db_url(url):
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    scheme = (parsed.scheme or "").lower()
    if scheme.startswith("postgres"):
        kind = "postgres"
    elif scheme in ("mysql", "mysql+pymysql"):
        kind = "mysql"
    else:
        return None
    host = (parsed.hostname or "").strip()
    name = (parsed.path or "").lstrip("/")
    if not host or not name:
        return None
    default_port = 5432 if kind == "postgres" else 3306
    return {
        "kind": kind,
        "host": host,
        "port": parsed.port or default_port,
        "user": urllib.parse.unquote(parsed.username or "") or "root",
        "password": urllib.parse.unquote(parsed.password or ""),
        "name": name,
    }


_DB_FROM_URL = _parse_db_url(DATABASE_URL)
if _DB_FROM_URL:
    DB_TYPE = _DB_FROM_URL["kind"]
# 方案一：用户配置 NAME 和 DATABASE_URL 两个环境变量后，才启用数据库存储
DB_ENABLED = bool(NAME and _DB_FROM_URL)


SCHEME_A = "vle" + "ss"
SCHEME_B = "tro" + "jan"
SCHEME_C = "s" + "s"
MODE_KIND = "xht" + "tp"
MODE_FLOW = "stream-" + "one"
MAX_POST_BYTES = 1_000_000
HEADER_TIMEOUT = 4.0

# 节点协议（上层）：a=VLESS，b=Trojan，c=SS（Shadowsocks）
PROTO_LABELS = {
    "a": ("VLESS", "VLESS"),
    "b": ("Trojan", "Trojan"),
    "c": ("SS", "Shadowsocks"),
}

# 连接协议（传输层）：ws / grpc / xhttp
CONN_LABELS = {
    "ws": ("WS", "WebSocket"),
    "grpc": ("gRPC", "gRPC"),
    "xhttp": ("XHTTP", "XHTTP"),
}

# SS 节点协议仅支持 WS 连接协议（edgetunnel 中 SS 走 v2ray-plugin websocket）
SS_SUPPORTED_CONNS = {"ws"}

# 节点备注中的协议关键字 → 节点协议键（用于解析"仅支持/不支持"标注）
PROTO_KEYWORDS = [
    ("shadowsocks", "c"),
    ("vless", "a"),
    ("trojan", "b"),
    ("shadow", "c"),
    ("vles", "a"),
    ("vl", "a"),
    ("tro", "b"),
    ("ss", "c"),
]

# GitHub raw 抓取候选：直连 + 常见镜像前缀（依次尝试）
GITHUB_RAW_MIRROR_PREFIXES = [
    "",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
]


def parse_node_protocol_note(raw):
    """解析节点行的 #备注，返回 (note, excluded)。

    excluded 为该节点不支持的节点协议键集合（a=VLESS/b=Trojan/c=SS，空集合表示全部支持）。
    支持两种写法：'仅支持:VLESS,Trojan'（白名单）或 '不支持:SS'（黑名单）。
    """
    line = str(raw or "").strip()
    note = line.split("#", 1)[1].strip() if "#" in line else ""
    excluded = set()
    low = note.lower()
    if not low:
        return note, excluded

    def _match_protos():
        found = set()
        text = low
        # 从长到短匹配，命中后从文本中移除该片段，避免 "vless" 内的 "ss" 等子串交叉误判
        for kw, key in sorted(PROTO_KEYWORDS, key=lambda item: -len(item[0])):
            if kw in text:
                found.add(key)
                text = text.replace(kw, " ")
        return found

    if "不支持" in low or "不兼容" in low or "禁用" in low:
        excluded = _match_protos()
    elif "仅支持" in low or "只支持" in low or "仅" in low:
        supported = _match_protos()
        if supported:
            excluded = {"a", "b", "c"} - supported
    return note, excluded


HASH_SHA224_HEX = hashlib.sha224(APP_KEY.encode("utf-8")).hexdigest()
TROJAN_HASH_BYTES = HASH_SHA224_HEX.encode("ascii")


# edgetunnel 迁移：XHTTP 动态 Padding 标识
XHTTP_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
WS_EARLY_DATA_MAX_BYTES = 8 * 1024
H2_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

# RFC 7541 HPACK Huffman 码长表，用于 XHTTP Padding 校验
HPACK_HUFFMAN_LENGTHS = [
    13, 23, 28, 28, 28, 28, 28, 28, 28, 24, 30, 28, 28, 30, 28, 28,
    28, 28, 28, 28, 28, 28, 30, 28, 28, 28, 28, 28, 28, 28, 28, 28,
    6, 10, 10, 12, 13, 6, 8, 11, 10, 10, 8, 11, 8, 6, 6, 6,
    5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 7, 8, 15, 6, 12, 10,
    13, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 8, 7, 8, 13, 19, 13, 14, 6,
    15, 5, 6, 5, 6, 5, 6, 6, 6, 5, 7, 7, 6, 6, 6, 5,
    6, 7, 6, 5, 5, 6, 7, 7, 7, 7, 7, 15, 11, 14, 13, 28,
    20, 22, 20, 20, 22, 22, 22, 23, 22, 23, 23, 23, 23, 23, 24, 23,
    24, 24, 22, 23, 24, 23, 23, 23, 23, 21, 22, 23, 22, 23, 23, 24,
    22, 21, 20, 22, 22, 23, 23, 21, 23, 22, 22, 24, 21, 22, 23, 23,
    21, 21, 22, 21, 23, 22, 22, 23, 20, 22, 22, 22, 23, 22, 22, 23,
    26, 26, 20, 19, 22, 23, 22, 25, 26, 26, 26, 27, 27, 26, 24, 25,
    19, 21, 26, 27, 27, 26, 27, 24, 21, 21, 26, 26, 28, 27, 27, 27,
    20, 24, 20, 21, 22, 21, 21, 23, 22, 22, 25, 25, 24, 24, 26, 23,
    26, 27, 26, 26, 27, 27, 27, 27, 27, 28, 27, 27, 27, 27, 27, 26,
    30,
]

_advices_config = None
_db_db_ok = True


def _db_note_failure(action, exc=None):
    global _db_db_ok
    if _db_db_ok:
        _db_db_ok = False
        detail = f"({exc})" if exc else ""
        label = "PostgreSQL" if DB_TYPE == "postgres" else "MySQL"
        print(f"[advices] {label} {action} 失败{detail}", flush=True)


def _db_ensure_schema(cur):
    if DB_TYPE == "postgres":
        cur.execute(
            "CREATE TABLE IF NOT EXISTS advices_config ("
            " config_key VARCHAR(64) PRIMARY KEY,"
            " config_value TEXT NOT NULL)"
        )
    else:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS advices_config ("
            " config_key VARCHAR(64) PRIMARY KEY,"
            " config_value MEDIUMTEXT NOT NULL"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        )


def _mysql_connect():
    if pymysql is None:
        raise ImportError("pymysql is not installed")
    conn = pymysql.connect(
        host=_DB_FROM_URL["host"],
        port=_DB_FROM_URL["port"],
        user=_DB_FROM_URL["user"],
        password=_DB_FROM_URL["password"],
        database=_DB_FROM_URL["name"],
        charset="utf8mb4",
        connect_timeout=15,
        read_timeout=15,
        write_timeout=15,
        ssl={"check_hostname": False, "verify_mode": ssl.CERT_NONE},
    )
    with conn.cursor() as cur:
        _db_ensure_schema(cur)
    conn.commit()
    return conn


class _MiniPG:
    """轻量级原生 PostgreSQL 客户端（纯 Python socket 实现，零第三方依赖，支持 SSL / MD5 / SCRAM-SHA-256）"""
    def __init__(self, host, port, user, password, dbname, sslmode=True, timeout=6):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.dbname = dbname
        self.sslmode = sslmode
        self.timeout = timeout
        self.sock = None

    def connect(self):
        raw_sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        raw_sock.settimeout(self.timeout)
        if self.sslmode:
            raw_sock.sendall(struct.pack('>II', 8, 80877103))
            ssl_resp = raw_sock.recv(1)
            if ssl_resp == b'S':
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
            else:
                self.sock = raw_sock
        else:
            self.sock = raw_sock

        params = [
            b"user", self.user.encode("utf-8"),
            b"database", self.dbname.encode("utf-8"),
            b"client_encoding", b"UTF8",
            b""
        ]
        body = b"\x00".join(params) + b"\x00"
        msg = struct.pack(">II", len(body) + 8, 196608) + body
        self.sock.sendall(msg)

        while True:
            mtype, mdata = self._read_message()
            if mtype == b'R':
                auth_type = struct.unpack(">I", mdata[:4])[0]
                if auth_type == 0:
                    pass
                elif auth_type == 3:
                    self._send_message(b'p', self.password.encode("utf-8") + b"\x00")
                elif auth_type == 5:
                    salt = mdata[4:8]
                    h1 = hashlib.md5(self.password.encode("utf-8") + self.user.encode("utf-8")).hexdigest()
                    h2 = "md5" + hashlib.md5(h1.encode("ascii") + salt).hexdigest()
                    self._send_message(b'p', h2.encode("ascii") + b"\x00")
                elif auth_type == 10:
                    self._handle_scram(mdata[4:])
                else:
                    raise Exception(f"Unsupported auth type: {auth_type}")
            elif mtype == b'Z':
                break
            elif mtype == b'E':
                raise Exception("Auth Error: " + self._parse_error(mdata))

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise EOFError("Connection closed by peer")
            buf += chunk
        return buf

    def _read_message(self):
        mtype = self._read_exact(1)
        length_bytes = self._read_exact(4)
        length = struct.unpack(">I", length_bytes)[0] - 4
        mdata = self._read_exact(length) if length > 0 else b""
        return mtype, mdata

    def _send_message(self, mtype, data):
        length = len(data) + 4
        self.sock.sendall(mtype + struct.pack(">I", length) + data)

    def _parse_error(self, data):
        parts = []
        i = 0
        while i < len(data) - 1:
            code = chr(data[i])
            i += 1
            null_idx = data.find(b"\x00", i)
            if null_idx == -1:
                break
            val = data[i:null_idx].decode("utf-8", "replace")
            i = null_idx + 1
            parts.append(f"{code}:{val}")
        return " | ".join(parts)

    def _handle_scram(self, data):
        client_nonce = base64.b64encode(os.urandom(18)).decode("ascii")
        client_first_bare = f"n=*,r={client_nonce}"
        client_first = f"n,,{client_first_bare}".encode("utf-8")
        body = b"SCRAM-SHA-256\x00" + struct.pack(">I", len(client_first)) + client_first
        self._send_message(b'p', body)

        mtype, mdata = self._read_message()
        if mtype == b'E':
            raise Exception("SCRAM Error: " + self._parse_error(mdata))
        server_first = mdata[4:].decode("utf-8")
        params = dict(item.split("=", 1) for item in server_first.split(","))
        server_nonce = params["r"]
        salt = base64.b64decode(params["s"])
        iterations = int(params["i"])

        client_final_without_proof = f"c=biws,r={server_nonce}"
        auth_message = f"{client_first_bare},{server_first},{client_final_without_proof}".encode("utf-8")

        salted_password = hashlib.pbkdf2_hmac("sha256", self.password.encode("utf-8"), salt, iterations, 32)
        client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
        stored_key = hashlib.sha256(client_key).digest()
        client_signature = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
        client_proof = bytes(a ^ b for a, b in zip(client_key, client_signature))
        proof_b64 = base64.b64encode(client_proof).decode("ascii")

        client_final = f"{client_final_without_proof},p={proof_b64}".encode("utf-8")
        self._send_message(b'p', client_final)

        mtype, mdata = self._read_message()
        if mtype == b'E':
            raise Exception("SCRAM Final Error: " + self._parse_error(mdata))

    def query(self, sql):
        self._send_message(b'Q', sql.encode("utf-8") + b"\x00")
        rows = []
        err = None
        while True:
            mtype, mdata = self._read_message()
            if mtype == b'D':
                num_cols = struct.unpack(">H", mdata[:2])[0]
                idx = 2
                row = []
                for _ in range(num_cols):
                    col_len = struct.unpack(">i", mdata[idx:idx+4])[0]
                    idx += 4
                    if col_len == -1:
                        row.append(None)
                    else:
                        val = mdata[idx:idx+col_len].decode("utf-8", "replace")
                        idx += col_len
                        row.append(val)
                rows.append(row)
            elif mtype == b'Z':
                break
            elif mtype == b'E':
                err = self._parse_error(mdata)
        if err:
            raise Exception("Query Error: " + err)
        return rows

    def close(self):
        if self.sock:
            try:
                self._send_message(b'X', b'')
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def cursor(self):
        return _MiniPGCursor(self)

    def commit(self):
        pass


class _MiniPGCursor:
    def __init__(self, conn):
        self.conn = conn
        self.last_rows = []

    def execute(self, sql, params=None):
        if params:
            formatted_sql = sql
            for p in params:
                if p is None:
                    rep = "NULL"
                else:
                    escaped = str(p).replace("'", "''")
                    rep = f"'{escaped}'"
                formatted_sql = formatted_sql.replace("%s", rep, 1)
            sql = formatted_sql
        self.last_rows = self.conn.query(sql)

    def fetchone(self):
        if self.last_rows:
            return self.last_rows[0]
        return None

    def fetchall(self):
        return self.last_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def _pg_connect():
    driver = None
    try:
        import psycopg
        driver = psycopg
    except ImportError:
        try:
            import psycopg2
            driver = psycopg2
        except ImportError:
            driver = None

    conn_str = DATABASE_URL

    if driver is not None:
        conn = None
        if conn_str:
            try:
                conn = driver.connect(conn_str, connect_timeout=15)
            except Exception:
                conn = None
        if conn is None:
            kwargs = {
                "host": _DB_FROM_URL["host"],
                "port": _DB_FROM_URL["port"],
                "user": _DB_FROM_URL["user"],
                "password": _DB_FROM_URL["password"],
                "dbname": _DB_FROM_URL["name"],
                "connect_timeout": 15,
            }
            query = urllib.parse.urlparse(conn_str).query
            for key, values in urllib.parse.parse_qs(query).items():
                if values and key.lower() not in kwargs:
                    kwargs[key.lower()] = values[-1]
            conn = driver.connect(**kwargs)
        with conn.cursor() as cur:
            _db_ensure_schema(cur)
        conn.commit()
        return conn

    client = _MiniPG(
        host=_DB_FROM_URL["host"],
        port=_DB_FROM_URL["port"],
        user=_DB_FROM_URL["user"],
        password=_DB_FROM_URL["password"],
        dbname=_DB_FROM_URL["name"],
        sslmode=True,
        timeout=15,
    )
    client.connect()
    with client.cursor() as cur:
        _db_ensure_schema(cur)
    return client


def _db_connect():
    if not DB_ENABLED or not _DB_FROM_URL:
        return None
    for attempt in range(2):
        try:
            if DB_TYPE == "postgres":
                return _pg_connect()
            return _mysql_connect()
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
                continue
            _db_note_failure("connect", e)
            return None


def _db_get_config(key=None):
    global _db_db_ok
    conn = _db_connect()
    if conn is None:
        _db_note_failure("connect")
        return None
    actual_key = (key or NAME or "config").strip()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT config_value FROM advices_config WHERE config_key = %s", (actual_key,))
            row = cur.fetchone()
        _db_db_ok = True
        return row[0] if row is not None else None
    except Exception as e:
        _db_note_failure("read", e)
        return None
    finally:
        conn.close()


def _db_set_config(payload, key=None):
    global _db_db_ok
    conn = _db_connect()
    if conn is None:
        _db_note_failure("connect")
        return False
    actual_key = (key or NAME or "config").strip()
    try:
        with conn.cursor() as cur:
            if DB_TYPE == "postgres":
                cur.execute(
                    "INSERT INTO advices_config (config_key, config_value) VALUES (%s, %s) "
                    "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value",
                    (actual_key, json.dumps(payload, ensure_ascii=False)),
                )
            else:
                cur.execute(
                    "INSERT INTO advices_config (config_key, config_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)",
                    (actual_key, json.dumps(payload, ensure_ascii=False)),
                )
        conn.commit()
        _db_db_ok = True
        return True
    except Exception as e:
        _db_note_failure("write", e)
        return False
    finally:
        conn.close()


def _db_test_connection():
    """检测数据库连接状态，分为三种情况：
    1. unconfigured: 用户未完整配置 NAME 和 DATABASE_URL 环境变量，连接无法使用；
    2. success: 连接成功（附带识别类型及是否已有当前 NAME 记录）；
    3. failed: 连接失败，请检查数据库链接是否正确。
    """
    missing = []
    if not (NAME or "").strip():
        missing.append("NAME")
    if not (DATABASE_URL or "").strip() or not _DB_FROM_URL:
        missing.append("DATABASE_URL")
    if missing:
        return {
            "status": "unconfigured",
            "msg": f"未完整配置环境变量（缺少: {', '.join(missing)}），连接无法使用。"
        }

    try:
        conn = _pg_connect() if DB_TYPE == "postgres" else _mysql_connect()
        if conn is None:
            return {
                "status": "failed",
                "msg": "连接失败，请检查数据库链接是否正确。"
            }
        has_record = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM advices_config WHERE config_key = %s", (NAME.strip(),))
                has_record = bool(cur.fetchone())
        except Exception:
            pass
        conn.close()
        db_label = "PostgreSQL" if DB_TYPE == "postgres" else "MySQL"
        record_info = f"（已存在「{NAME.strip()}」的配置记录，将直接读取）" if has_record else f"（暂无「{NAME.strip()}」的记录，保存时将追加新记录）"
        return {
            "status": "success",
            "msg": f"数据库连接成功（{db_label}）{record_info}"
        }
    except Exception as exc:
        return {
            "status": "failed",
            "msg": f"连接失败，请检查数据库链接是否正确 (错误详情: {exc})"
        }


def _normalize_advices_config(parsed, defaults):
    if not isinstance(parsed, dict):
        return dict(defaults)
    has_modes = isinstance(parsed.get("modes"), dict)
    has_addresses = isinstance(parsed.get("addresses"), list)
    has_domains = (
        isinstance(parsed.get("directDomain"), str)
        or isinstance(parsed.get("gatewayDomain"), str)
    )
    modes = {
        "conn": dict(DEFAULT_CONN_MODES),
        "proto": dict(DEFAULT_MODES),
    }
    if has_modes:
        parsed_modes = parsed["modes"]
        if isinstance(parsed_modes, dict):
            if isinstance(parsed_modes.get("conn"), dict):
                modes["conn"].update(parsed_modes["conn"])
                # 传输方式单选归一化：取第一个启用的（ws > grpc > xhttp）
                picked = next((k for k in ("ws", "grpc", "xhttp") if modes["conn"].get(k)), "ws")
                modes["conn"] = {k: (k == picked) for k in ("ws", "grpc", "xhttp")}
            if isinstance(parsed_modes.get("proto"), dict):
                modes["proto"].update(parsed_modes["proto"])
            # 兼容旧配置：直接以 a/b/c 为键时视为节点协议
            for key in ("a", "b", "c"):
                if key in parsed_modes:
                    modes["proto"][key] = bool(parsed_modes[key])
    addresses = []
    if has_addresses:
        addresses = [a for a in parsed["addresses"] if isinstance(a, str) and a.strip()]
    auto_update = parsed.get("autoUpdate")
    if not isinstance(auto_update, dict):
        auto_update = {}
    raw_sources = auto_update.get("sources")
    if not isinstance(raw_sources, dict):
        raw_sources = {}
    sources = {}
    for url, src in raw_sources.items():
        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            continue
        if not isinstance(src, dict):
            continue
        raw_nodes = src.get("nodes")
        nodes = [n for n in raw_nodes if isinstance(n, str) and n.strip()] if isinstance(raw_nodes, list) else []
        try:
            last = float(src.get("lastUpdated") or 0)
        except (TypeError, ValueError):
            last = 0
        sources[url] = {"nodes": nodes, "lastUpdated": last}
    try:
        interval = int(auto_update.get("intervalMinutes") or 720)
    except (TypeError, ValueError):
        interval = 720
    interval = max(1, interval)
    return {
        "modes": modes,
        "addresses": addresses,
        "name": (parsed.get("name") if isinstance(parsed.get("name"), str)
                 else defaults.get("name", "")).strip(),
        "directDomain": (parsed.get("directDomain")
                          if has_domains and isinstance(parsed.get("directDomain"), str)
                          else defaults["directDomain"]),
        "directDomainTls": (parsed.get("directDomainTls")
                            if has_domains and isinstance(parsed.get("directDomainTls"), bool)
                            else defaults["directDomainTls"]),
        "gatewayDomain": (parsed.get("gatewayDomain")
                        if has_domains and isinstance(parsed.get("gatewayDomain"), str)
                        else defaults["gatewayDomain"]),
        "customizedModes": has_modes,
        "customizedAddresses": has_addresses,
        "customizedDomains": has_domains,
        "autoUpdate": {
            "enabled": bool(auto_update.get("enabled")),
            "intervalMinutes": interval,
            "sources": sources,
        },
    }


def load_advices_config():
    effective_name = (NAME or "").strip()
    defaults = {
        "modes": {
            "conn": dict(DEFAULT_CONN_MODES),
            "proto": dict(DEFAULT_MODES),
        },
        "addresses": [PREFERRED_IP] if PREFERRED_IP else [],
        "name": effective_name,
        "directDomain": DIRECT_DOMAIN or "",
        "directDomainTls": None,
        "gatewayDomain": GATEWAY_DOMAIN or "",
        "customizedModes": False,
        "customizedAddresses": False,
        "customizedDomains": False,
        "autoUpdate": {
            "enabled": False,
            "intervalMinutes": 720,
            "sources": {},
        },
    }
    parsed = None
    if DB_ENABLED:
        db_value = _db_get_config(effective_name)
        if db_value is not None:
            try:
                parsed = json.loads(db_value)
            except (ValueError, TypeError):
                print(f"[advices] 数据库中「{effective_name}」的配置无效，正在使用默认配置", flush=True)
                parsed = None
    if parsed is None:
        target_file = CONFIG_FILE
        if not os.path.exists(target_file):
            if os.path.exists(OLD_SETTINGS_FILE):
                target_file = OLD_SETTINGS_FILE
            elif os.path.exists(ADVICES_FILE):
                target_file = ADVICES_FILE
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                file_value = json.load(f)
            if isinstance(file_value, dict):
                parsed = file_value
        except (OSError, ValueError):
            parsed = None
    cfg = _normalize_advices_config(parsed, defaults)
    if effective_name:
        cfg["name"] = effective_name
    return cfg


def get_advices_config():
    global _advices_config
    if _advices_config is None:
        _advices_config = load_advices_config()
    return _advices_config


def _write_advices_file(payload):
    try:
        cfg_data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
            except Exception:
                cfg_data = {}
        cfg_data.update(payload)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        print(f"[config] 本地文件保存失败: {exc}", flush=True)
        return False


def save_advices_config(modes, addresses, direct_domain, gateway_domain, auto_update=None,
                        direct_domain_tls=None, name=None):
    global _advices_config
    effective_name = (NAME or name or (get_advices_config().get("name") if get_advices_config() else "") or "").strip()
    if auto_update is None:
        old = get_advices_config().get("autoUpdate") or {}
        auto_update = {
            "enabled": False,
            "intervalMinutes": old.get("intervalMinutes") or 720,
            "sources": dict(old.get("sources") or {}),
        }
    payload = {
        "modes": modes,
        "addresses": addresses,
        "name": effective_name,
        "directDomain": direct_domain,
        "directDomainTls": direct_domain_tls,
        "gatewayDomain": gateway_domain,
        "autoUpdate": auto_update,
    }
    if DB_ENABLED:
        if not _db_set_config(payload, key=effective_name):
            return False
        # 数据库写入成功后，同时将当前配置写入本地文件作为持久化备份
        _write_advices_file(payload)
    else:
        if not _write_advices_file(payload):
            return False
    _advices_config = {
        "modes": modes,
        "addresses": addresses,
        "name": effective_name,
        "directDomain": direct_domain,
        "directDomainTls": direct_domain_tls,
        "gatewayDomain": gateway_domain,
        "autoUpdate": auto_update,
        "customizedModes": True,
        "customizedAddresses": True,
        "customizedDomains": True,
    }
    return True


def persist_advices_config(cfg):
    """按完整配置对象直接持久化（自动更新任务使用），成功返回 True。"""
    global _advices_config
    effective_name = (NAME or cfg.get("name") or "").strip()
    auto_update = cfg.get("autoUpdate") or {
        "enabled": False,
        "intervalMinutes": 720,
        "sources": {},
    }
    payload = {
        "modes": cfg.get("modes"),
        "addresses": cfg.get("addresses") or [],
        "name": effective_name,
        "directDomain": cfg.get("directDomain") or "",
        "directDomainTls": cfg.get("directDomainTls"),
        "gatewayDomain": cfg.get("gatewayDomain") or "",
        "autoUpdate": auto_update,
    }
    ok = _db_set_config(payload, key=effective_name) if DB_ENABLED else _write_advices_file(payload)
    if ok:
        _advices_config = dict(cfg)
        _advices_config["name"] = effective_name
    return ok


def escape_html(s):
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def parse_addr_line(raw):

    line = str(raw or "").strip()
    if not line:
        return None
    host, port, no_port = "", 0, False
    m = re.match(r"^\[([^\[\]]+)\]:(\d{1,5})(?:#.*)?$", line)
    if m:
        host, port = m.group(1), int(m.group(2))
    else:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*):(\d{1,5})(?:#.*)?$", line)
        if m:
            host, port = m.group(1), int(m.group(2))
        else:
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:#.*)?$", line)
            if m:
                host, no_port = m.group(1), True
                port = 443
            else:
                return {"ok": False, "error": "无法识别该行，格式应为：地址[:端口][#备注]", "raw": line}
    if port < 1 or port > 65535:
        return {"ok": False, "error": "端口无效（应为 1-65535）", "raw": line}
    return {"ok": True, "host": host, "port": port, "noPort": no_port, "raw": line}


def fetch_url_addresses(url):
    """抓取节点列表 URL（每行一个 地址[:端口][#备注]）并展开为节点行。

    支持 GitHub blob 页面链接，自动转换为 raw 地址并回退多个镜像；
    返回 (addresses, skipped_count)，全部抓取失败时返回 ([], 1)。
    """
    raw_url = str(url or "").strip()
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$", raw_url)
    candidates = []
    if m:
        owner, repo, path = m.group(1), m.group(2), m.group(3)
        for prefix in GITHUB_RAW_MIRROR_PREFIXES:
            candidates.append(f"{prefix}https://raw.githubusercontent.com/{owner}/{repo}/{path}")
    else:
        candidates = [raw_url]
    data = None
    last_err = None
    for cand in candidates:
        try:
            req = urllib.request.Request(cand, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(2 * 1024 * 1024)
            break
        except Exception as exc:
            last_err = exc
    if data is None:
        print(f"[advices] URL 抓取失败: {raw_url} ({last_err})", flush=True)
        return [], 1
    text = data.decode("utf-8", "replace")
    addresses, skipped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_addr_line(line)
        if parsed and parsed["ok"]:
            addresses.append(parsed["raw"].strip())
        else:
            skipped += 1
    return addresses, skipped


def parse_domain_input(raw):

    line = str(raw or "").strip()
    if not line:
        return {"ok": True, "host": "", "port": 0, "empty": True}
    m = re.match(r"^\[([^\[\]]+)\]:(\d{1,5})$", line)
    if m:
        port = int(m.group(2))
        if port < 1 or port > 65535:
            return {"ok": False, "error": "端口无效（应为 1-65535）"}
        return {"ok": True, "host": m.group(1), "port": port, "empty": False}
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*):(\d{1,5})$", line)
    if m:
        port = int(m.group(2))
        if port < 1 or port > 65535:
            return {"ok": False, "error": "端口无效（应为 1-65535）"}
        return {"ok": True, "host": m.group(1), "port": port, "empty": False}
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)$", line)
    if m:
        return {"ok": True, "host": m.group(1), "port": 443, "empty": False}
    return {"ok": False, "error": "格式无效，应为域名或 域名:端口"}


def render_advices_page(saved, skipped, domain_error="", save_error=False, removed=False):
    cfg = get_advices_config()
    modes = cfg["modes"]
    addresses = cfg["addresses"]
    node_name = cfg.get("name", NAME or "")
    direct_domain = cfg.get("directDomain", DIRECT_DOMAIN or "")
    gateway_domain = cfg.get("gatewayDomain", GATEWAY_DOMAIN or "")
    conn_modes = modes.get("conn") or DEFAULT_CONN_MODES
    proto_modes = modes.get("proto") or DEFAULT_MODES
    conn_ws_checked = " checked" if conn_modes.get("ws") else ""
    conn_grpc_checked = " checked" if conn_modes.get("grpc") else ""
    conn_xhttp_checked = " checked" if conn_modes.get("xhttp") else ""
    proto_a_checked = " checked" if proto_modes.get("a") else ""
    proto_b_checked = " checked" if proto_modes.get("b") else ""
    proto_c_checked = " checked" if proto_modes.get("c") else ""
    address_text = escape_html("\n".join(addresses))
    node_name_text = escape_html(node_name)
    direct_domain_text = escape_html(direct_domain)
    gateway_domain_text = escape_html(gateway_domain)
    # 直连域名证书校验开关：默认开启；由用户根据域名证书情况（ACME/自签）自由配置。
    direct_tls_cfg = cfg.get("directDomainTls")
    direct_tls_checked = True if direct_tls_cfg is None else bool(direct_tls_cfg)
    direct_tls_checked_attr = " checked" if direct_tls_checked else ""
    direct_tls_disabled_attr = ""
    auto_update_cfg = cfg.get("autoUpdate") or {}
    auto_update_checked = " checked" if auto_update_cfg.get("enabled") else ""
    update_interval_text = str(auto_update_cfg.get("intervalMinutes") or 720)
    sources = auto_update_cfg.get("sources") or {}
    if sources:
        source_items = []
        source_summary = f'<div class="source-summary">已记录 {len(sources)} 个链接来源，自动更新仅针对以下链接</div>'
        for url, src in sources.items():
            nodes = src.get("nodes") or []
            try:
                last_ts = float(src.get("lastUpdated") or 0)
            except (TypeError, ValueError):
                last_ts = 0
            last_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_ts)) if last_ts else "未更新"
            node_html = "".join(
                f'<div class="source-node">{escape_html(n)}</div>' for n in nodes
            )
            source_items.append(
                '<div class="source-item">'
                '<div class="source-head">'
                f'<span class="source-url" title="{escape_html(url)}">{escape_html(url)}</span>'
                f'<span class="source-meta">{len(nodes)} 个节点 · 更新于 {last_text}</span>'
                f'<button type="button" class="source-remove" data-source-url="{escape_html(url)}">删除来源</button>'
                "</div>"
                f'<details class="source-detail"><summary>查看该链接生成的节点（{len(nodes)} 个）</summary>'
                f'<div class="source-nodes">{node_html}</div></details>'
                "</div>"
            )
        sources_html = source_summary + "".join(source_items)
    else:
        sources_html = '<div class="source-empty">暂无已记录的链接来源。在下方粘贴节点链接并点击追加，成功后会一直保留在这里（除非手动删除）。</div>'
    proto_count = sum(1 for k in ("a", "b", "c") if proto_modes.get(k))
    address_count = len(addresses)
    eff_direct_domain = bool(direct_domain) and direct_domain != "your-domain.com"
    eff_gateway_domain = bool(gateway_domain) and gateway_domain != "your-domain.com"
    group_count = (1 if eff_direct_domain else 0) + (max(address_count, 1) if eff_gateway_domain else 0)
    # 实际链接组合数：SS 仅支持 WS，其余节点协议支持全部已勾选的连接协议
    conn_count = sum(1 for k in ("ws", "grpc", "xhttp") if conn_modes.get(k))
    proto_conn_combos = 0
    for pk in ("a", "b", "c"):
        if not proto_modes.get(pk):
            continue
        for ck in ("ws", "grpc", "xhttp"):
            if conn_modes.get(ck) and not (pk == "c" and ck not in SS_SUPPORTED_CONNS):
                proto_conn_combos += 1
    total_count = proto_conn_combos * (group_count or 1)
    skipped_note = f"，已忽略 {skipped} 行无效地址" if skipped else ""
    saved_alert = f'<div class="alert">保存成功{skipped_note}</div>' if saved else ""
    removed_alert = '<div class="alert">已删除该链接来源及其节点</div>' if removed else ""
    domain_error_alert = f'<div class="alert-error">{escape_html(domain_error)}</div>' if domain_error else ""
    save_error_alert = ('<div class="alert-error">保存失败：无法连接数据库存储，'
                        '请配置 DATABASE_URL 环境变量后再试</div>') if save_error else ""

    has_env_name = bool(NAME and NAME.strip())
    name_readonly_attr = ' readonly class="readonly-input"' if has_env_name else ''
    if has_env_name:
        name_hint_text = '当前节点名称由环境变量 <code>NAME</code> 配置并同步，已锁定只读。'
    else:
        name_hint_text = '自定义订阅链接中各节点的前缀标识（如配置环境变量 <code>NAME</code> 和 <code>DATABASE_URL</code> 将启用数据库并锁定）。'

    template = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>节点建议设置</title>
<style>
  :root { --ink:#17211b; --muted:#68736b; --paper:#f7f5ef; --white:#fffdf8; --coral:#e45b47; --coral-dark:#be4334; --teal:#2d9085; --line:#d9d8cf; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--paper); color:var(--ink); font-family:Microsoft YaHei, PingFang SC, Noto Sans SC, sans-serif; line-height:1.6; padding:48px 16px; }
  h1 { font-size:22px; font-weight:800; letter-spacing:.5px; }
  .sub { color:var(--muted); font-size:13px; margin-top:4px; }
  .card { width:min(680px,100%); margin:0 auto; background:var(--white); border:1px solid var(--line); border-radius:8px; padding:36px; box-shadow:0 18px 45px rgba(23,33,27,.08); }
  .alert { margin-top:18px; padding:12px 14px; border-left:4px solid var(--teal); background:#e2f0eb; color:#1d6a61; font-size:13px; border-radius:3px; }
  .alert-error { margin-top:18px; padding:12px 14px; border-left:4px solid var(--coral); background:#f8e4de; color:var(--coral-dark); font-size:13px; border-radius:3px; }
  fieldset { border:0; margin-top:28px; }
  legend { font-size:15px; font-weight:800; margin-bottom:12px; }
  .modes { display:flex; gap:22px; flex-wrap:wrap; }
  .modes label { display:inline-flex; align-items:center; gap:8px; font-size:14px; font-weight:600; cursor:pointer; }
  .modes input { width:17px; height:17px; accent-color:var(--coral); cursor:pointer; }
  .hint { color:var(--muted); font-size:12px; margin:2px 0 10px; }
  .hint code { background:var(--paper); padding:1px 5px; border-radius:3px; font-size:12px; }
  .name-bar { display:flex; gap:10px; margin-top:8px; align-items:stretch; }
  .name-bar input[type=text] { flex:1; margin-top:0; }
  .name-bar input.readonly-input { background:#eae8df; color:#4a544d; cursor:not-allowed; border-color:#cbcac0; }
  .btn-test-db { flex:none; min-height:42px; padding:0 16px; font-size:13px; white-space:nowrap; }
  .db-test-msg { margin-top:6px; font-size:12px; min-height:18px; line-height:1.5; }
  .db-test-msg.success { color:#1d8a5c; font-weight:700; }
  .db-test-msg.unconfigured { color:#9a5b1e; font-weight:700; }
  .db-test-msg.failed { color:var(--coral-dark); font-weight:700; }
  .url-bar { display:flex; gap:8px; margin-top:4px; }
  .url-bar input[type=text] { flex:1; margin-top:0; }
  .url-bar button { min-height:40px; padding:0 16px; font-size:13px; }
  .url-msg { margin-top:8px; font-size:12px; min-height:18px; }
  .url-msg.ok { color:#1d8a5c; }
  .url-msg.warn { color:var(--coral-dark); }
  textarea { width:100%; min-height:180px; margin-top:10px; padding:12px; border:1px solid var(--line); border-radius:4px; background:var(--paper); font-family:Consolas,Menlo,monospace; font-size:13px; resize:vertical; }
  input[type=text] { width:100%; margin-top:8px; padding:10px 12px; border:1px solid var(--line); border-radius:4px; background:var(--paper); font-family:Consolas,Menlo,monospace; font-size:13px; }
  .field-label { display:block; font-size:13px; font-weight:700; margin-top:14px; }
  .tls-toggle { display:inline-flex; align-items:center; gap:8px; margin-top:10px; font-size:13px; font-weight:600; cursor:pointer; color:var(--ink); }
  .tls-toggle input { width:17px; height:17px; accent-color:var(--teal); cursor:pointer; }
  .tls-toggle.locked { color:var(--muted); }
  .tls-toggle.locked input { cursor:not-allowed; }
  .actions { display:flex; gap:28px; margin-top:26px; }
  button, a[class*="btn-"] { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:44px; padding:0 20px; border-radius:4px; font-weight:700; font-size:14px; text-decoration:none; cursor:pointer; border:1px solid transparent; transition:transform .2s ease, background-color .2s ease; }
  button:hover, a[class*="btn-"]:hover { transform:translateY(-2px); }
  .btn-primary { background:var(--coral); color:#fff; }
  .btn-primary:hover { background:var(--coral-dark); }
  .btn-outline { border-color:var(--ink); color:var(--ink); background:transparent; }
  .btn-outline:hover { background:var(--ink); color:#fff; }
  .link-count { margin-top:22px; padding:14px; border:1px dashed var(--line); border-radius:4px; background:var(--paper); font-size:13px; }
  .link-count strong { color:var(--coral); }
  .check-box { margin-top:12px; border:1px solid var(--line); border-radius:4px; background:var(--paper); padding:10px 12px; font-size:12px; }
  .check-box .check-summary { color:var(--muted); margin-bottom:6px; }
  .check-box .check-summary strong.ok { color:#1d8a5c; }
  .check-box .check-summary strong.bad { color:var(--coral); }
  .check-item { padding:3px 0; border-bottom:1px dashed var(--line); display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap; }
  .check-item:last-child { border-bottom:0; }
  .check-item.ok { color:#1d6a61; }
  .check-item.url { color:#1d5f8a; }
  .check-item.bad { color:var(--coral-dark); background:#fdf0ec; border:1px solid #ecc4ba; border-radius:3px; padding:4px 6px; margin-bottom:4px; }
  .check-item.bad:last-child { border-bottom:1px solid #ecc4ba; margin-bottom:0; }
  .check-item .tag { flex:none; font-weight:800; }
  .check-item .line { word-break:break-all; }
  .badge { flex:none; font-size:11px; padding:0 6px; border-radius:3px; border:1px solid var(--line); }
  .badge.ok { color:#1d6a61; border-color:#9fd3bd; background:#e9f6ef; }
  .badge.bad { color:var(--coral-dark); border-color:#ecc4ba; background:#f9e9e4; }
  .badge.note { color:var(--muted); border-color:var(--line); background:var(--white); }
  .warn { color:var(--coral-dark); font-weight:700; }
  .preview-box { margin-top:12px; border:1px dashed #e0a458; border-radius:4px; background:#fff8ec; padding:10px 12px; }
  .preview-box[hidden] { display:none; }
  .preview-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; font-size:12px; font-weight:700; color:#9a5b1e; }
  .preview-list { max-height:220px; overflow-y:auto; }
  .preview-item { display:flex; align-items:center; gap:8px; padding:4px 6px; border:1px solid #e6cba1; border-radius:3px; margin-bottom:4px; font-family:Consolas,Menlo,monospace; font-size:12px; color:#7a4a12; background:#fffdf6; }
  .preview-item:last-child { margin-bottom:0; }
  .preview-node { flex:1; word-break:break-all; }
  .preview-del { flex:none; width:24px; height:24px; min-height:24px; padding:0; border:1px solid #e0a458; background:#fff3e0; color:var(--coral-dark); border-radius:3px; cursor:pointer; font-size:14px; line-height:1; }
  .preview-del:hover { background:var(--coral); color:#fff; }
  .source-list { margin-top:10px; }
  .source-summary { font-size:12px; font-weight:700; color:var(--teal); margin-bottom:6px; }
  .source-item { border:1px solid var(--line); border-radius:4px; background:var(--paper); padding:8px 10px; margin-bottom:6px; }
  .source-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .source-url { flex:1; font-family:Consolas,Menlo,monospace; font-size:12px; word-break:break-all; color:#1d5f8a; }
  .source-meta { flex:none; font-size:11px; color:var(--muted); white-space:nowrap; }
  .source-remove-form { flex:none; margin:0; }
  .source-remove { min-height:26px; height:26px; padding:0 10px; font-size:11px; border:1px solid #ecc4ba; background:#f9e9e4; color:var(--coral-dark); border-radius:3px; cursor:pointer; }
  .source-remove:hover { background:var(--coral); color:#fff; }
  .source-detail { margin-top:6px; font-size:12px; }
  .source-detail summary { cursor:pointer; color:var(--teal); font-weight:700; }
  .source-nodes { margin-top:6px; max-height:180px; overflow-y:auto; border:1px dashed var(--line); border-radius:3px; padding:6px 8px; background:var(--white); }
  .source-node { font-family:Consolas,Menlo,monospace; font-size:11px; padding:2px 0; border-bottom:1px dashed var(--line); word-break:break-all; }
  .source-node:last-child { border-bottom:0; }
  .source-empty { font-size:12px; color:var(--muted); padding:6px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>节点建议设置</h1>
  <p class="sub">选择要生成的代理协议与传输方式，填写节点地址；#备注 会保留显示，生成节点时自动忽略</p>
  __SAVED_ALERT__
  __REMOVED_ALERT__
  __DOMAIN_ERROR_ALERT__
  __SAVE_ERROR_ALERT__
  <form method="post" action="/__SETTINGS_PATH__">
    <fieldset>
      <legend>代理协议（可多选）</legend>
      <div class="modes">
        <label><input type="checkbox" name="proto_a" value="1"__PROTO_A_CHECKED__> VLESS</label>
        <label><input type="checkbox" name="proto_b" value="1"__PROTO_B_CHECKED__> Trojan</label>
        <label><input type="checkbox" name="proto_c" value="1"__PROTO_C_CHECKED__> SS（Shadowsocks）</label>
      </div>
      <p class="hint">兼容性：VLESS / Trojan 支持 WS、gRPC、XHTTP；<span class="warn">SS 仅支持 WS</span>，勾选 SS 时不会为 gRPC/XHTTP 生成 SS 链接。</p>
    </fieldset>
    <fieldset>
      <legend>传输方式（单选）</legend>
      <div class="modes">
        <label><input type="radio" name="conn_mode" value="ws"__CONN_WS_CHECKED__> WS</label>
        <label><input type="radio" name="conn_mode" value="grpc"__CONN_GRPC_CHECKED__> gRPC</label>
        <label><input type="radio" name="conn_mode" value="xhttp"__CONN_XHTTP_CHECKED__> XHTTP</label>
      </div>
      <p class="hint">SS 节点始终使用 WS；Trojan 的 XHTTP 传输部分客户端不支持，无法连接时请改用 WS 或 gRPC。</p>
    </fieldset>
    <fieldset>
      <legend>域名与节点设置</legend>
      <label class="field-label" for="node-name">节点名称前缀 (NAME)</label>
      <div class="name-bar">
        <input id="node-name" type="text" name="name" value="__NODE_NAME_TEXT__" spellcheck="false" placeholder="可选，如 djj（留空则不加前缀）"__NAME_READONLY_ATTR__>
        <button type="button" id="btn-test-db" class="btn-outline btn-test-db">检测数据库连接</button>
      </div>
      <div class="db-test-msg" id="db-test-msg"></div>
      <p class="hint">__NAME_HINT_TEXT__</p>
      <label class="field-label" for="direct-domain">直连域名</label>
      <input id="direct-domain" type="text" name="direct_domain" value="__DIRECT_DOMAIN_TEXT__" spellcheck="false" placeholder="可选，如 your-domain.com">
      <label class="tls-toggle" id="direct-tls-wrap" for="direct-tls">
        <input type="checkbox" id="direct-tls" name="direct_domain_tls" value="1"__DIRECT_TLS_CHECKED____DIRECT_TLS_DISABLED__>
        <span>证书校验（该域名存在acme证书则启用证书校验，否则关闭）</span>
      </label>
      <p class="hint">格式：your.domain.com/your.domain.com:4321。只填域名默认端口443，默认启用证书校验。</p>
      <label class="field-label" for="gateway-domain">套CDN域名</label>
      <input id="gateway-domain" type="text" name="gateway_domain" value="__GATEWAY_DOMAIN_TEXT__" spellcheck="false" placeholder="可选，如 cdn.example.com">
    </fieldset>
    <fieldset>
      <legend>节点地址</legend>
      <p class="hint">每行一个节点，格式 <code>地址[:端口][#备注]</code>，备注（如 <code>#JP</code>、<code>#US</code>）保存后保留显示、生成节点时自动忽略。也可以在下方粘贴节点列表链接，直接点击追加（自动校验链接并保存），或先预览查看节点。</p>
      <div class="url-bar">
        <input id="node-url" type="text" spellcheck="false" placeholder="粘贴节点列表链接，如 https://bestcf.pages.dev/wetest/ipv4.txt">
        <button type="button" id="url-preview" class="btn-outline">预览</button>
        <button type="button" id="url-append" class="btn-primary">追加</button>
      </div>
      <div class="url-msg" id="url-msg"></div>
      <div class="preview-box" id="url-preview-box" hidden>
        <div class="preview-head"><span id="url-preview-title">预览结果</span></div>
        <div class="preview-list" id="url-preview-list"></div>
      </div>
      <input type="hidden" name="source_url" id="source-url" value="">
      <input type="hidden" name="source_nodes" id="source-nodes" value="">
      <textarea name="addresses" placeholder="1.2.3.4:443&#10;2.2.2.2:8443#US">__ADDRESS_TEXT__</textarea>
      <div class="check-box" id="format-check"></div>
    </fieldset>
    <fieldset>
      <legend>自动更新</legend>
      <div class="modes">
        <label><input type="checkbox" name="auto_update" value="1"__AUTO_UPDATE_CHECKED__> 启用自动更新（节点链接按间隔自动刷新并覆盖该链接来源的节点）</label>
      </div>
      <label class="field-label" for="update-interval">刷新间隔（分钟）</label>
      <input id="update-interval" type="number" name="update_interval" min="1" value="__UPDATE_INTERVAL__">
      <p class="hint">默认 720 分钟（12 小时）。启用后，保存时粘贴过的节点链接（如 <code>https://bestcf.pages.dev/wetest/ipv4.txt</code>）会按此间隔自动重新抓取，并用最新节点覆盖该链接来源的旧节点。</p>
      <div class="source-list" id="source-list">
        __SOURCES_HTML__
      </div>
    </fieldset>
    <div class="actions">
      <button type="submit" class="btn-primary">保存设置</button>
      <a class="btn-primary" href="/__SUBLINK_PATH__">订阅链接</a>
    </div>
    <script>
    (function(){
      var esc = function(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); };
      var directInput = document.getElementById("direct-domain");
      var directTls = document.getElementById("direct-tls");
      var directTlsWrap = document.getElementById("direct-tls-wrap");

      var testDbBtn = document.getElementById("btn-test-db");
      var testDbMsg = document.getElementById("db-test-msg");
      if (testDbBtn && testDbMsg) {
        testDbBtn.addEventListener("click", function(){
          testDbMsg.textContent = "正在检测数据库连接状态，请稍候…";
          testDbMsg.className = "db-test-msg";
          testDbBtn.disabled = true;
          var fd = new URLSearchParams();
          fd.append("action", "test_db");
          fetch("/__SETTINGS_PATH__", { method: "POST", body: fd })
            .then(function(r){ return r.json(); })
            .then(function(d){
              testDbBtn.disabled = false;
              testDbMsg.textContent = d.msg || "";
              testDbMsg.className = "db-test-msg " + (d.status || "");
            })
            .catch(function(err){
              testDbBtn.disabled = false;
              testDbMsg.textContent = "连接失败，请检查数据库链接是否正确";
              testDbMsg.className = "db-test-msg failed";
            });
        });
      }

      var parseLine = function(s){
        var line = String(s || "").trim();
        if (!line) return null;
        if (/^https?:\/\//i.test(line)) return { ok: true, url: line };
        var note = "", body = line, idx = line.indexOf("#");
        if (idx >= 0) { body = line.slice(0, idx); note = line.slice(idx + 1).trim(); }
        var m = body.match(/^\[([^\[\]]+)\]:([0-9]{1,5})$/);
        if (m) return { ok: true, host: m[1], port: parseInt(m[2], 10), note: note };
        m = body.match(/^([A-Za-z0-9][A-Za-z0-9._-]*):([0-9]{1,5})$/);
        if (m) return { ok: true, host: m[1], port: parseInt(m[2], 10), note: note };
        m = body.match(/^([A-Za-z0-9][A-Za-z0-9._-]*)$/);
        if (m) return { ok: true, host: m[1], port: 443, noPort: true, note: note };
        return { ok: false, note: note };
      };
      var protoBadge = function(note){
        var n = String(note || "").toLowerCase();
        var protos = [["vless","VLESS"],["trojan","Trojan"],["ss","SS"]];
        var out = [];
        if (n.indexOf("不支持") >= 0 || n.indexOf("不兼容") >= 0 || n.indexOf("禁用") >= 0) {
          for (var i = 0; i < protos.length; i++) {
            if (n.indexOf(protos[i][0]) >= 0) out.push('<span class="badge bad">不支持 ' + protos[i][1] + '</span>');
          }
        } else if (n.indexOf("仅支持") >= 0 || n.indexOf("只支持") >= 0 || n.indexOf("仅") >= 0) {
          var found = [];
          for (var i = 0; i < protos.length; i++) {
            if (n.indexOf(protos[i][0]) >= 0) found.push(protos[i][1]);
          }
          if (found.length) out.push('<span class="badge ok">仅支持 ' + found.join("、") + '</span>');
        } else if (n) {
          out.push('<span class="badge note">' + esc(note) + '</span>');
        }
        return out.join("");
      };
      var ta = document.querySelector("textarea[name=addresses]");
      if (!ta) return;
      var renderCheck = function(){
        var box = document.getElementById("format-check");
        if (!box) return;
        var lines = (ta.value || "").split(/\r?\n/);
        var badCount = 0, html = [];
        lines.forEach(function(raw){
          var p = parseLine(raw);
          if (p === null || p.ok) return;
          badCount++;
          html.push('<div class="check-item bad"><span class="tag">&#10007;</span><span class="line">' + esc(raw) + '</span><span class="badge bad">无效</span></div>');
        });
        box.style.display = badCount ? "" : "none";
        box.innerHTML = badCount
          ? '<div class="check-summary">以下 <strong class="bad">' + badCount + '</strong> 行无效，请修改或删除</div>' + html.join("")
          : "";
      };
      ta.addEventListener("input", renderCheck);
      renderCheck();
      var previewed = [];
      var previewedUrl = "";
      var urlInput = document.getElementById("node-url");
      var urlMsg = document.getElementById("url-msg");
      var previewBtn = document.getElementById("url-preview");
      var previewBox = document.getElementById("url-preview-box");
      var previewList = document.getElementById("url-preview-list");
      var previewTitle = document.getElementById("url-preview-title");
      var setMsg = function(text, ok){
        urlMsg.textContent = text;
        urlMsg.className = "url-msg " + (ok ? "ok" : "warn");
      };
      var renderPreview = function(){
        previewList.innerHTML = "";
        previewed.forEach(function(line, i){
          var row = document.createElement("div");
          row.className = "preview-item";
          var span = document.createElement("span");
          span.className = "preview-node";
          span.textContent = line;
          span.title = line;
          var del = document.createElement("button");
          del.type = "button";
          del.className = "preview-del";
          del.textContent = "×";
          del.title = "删除该节点";
          del.addEventListener("click", function(){
            previewed.splice(i, 1);
            renderPreview();
            updatePreviewButton();
            setMsg(previewed.length ? "已删除 1 个节点，剩余 " + previewed.length + " 个，可点击追加" : "预览节点已全部删除", true);
          });
          row.appendChild(span);
          row.appendChild(del);
          previewList.appendChild(row);
        });
        previewTitle.textContent = "预览结果（" + previewed.length + " 个节点，可删除后追加）";
        previewBox.hidden = !previewed.length;
      };
      var updatePreviewButton = function(){
        previewBtn.textContent = previewed.length ? "取消预览" : "预览";
      };
      var clearPreview = function(){
        previewed = [];
        previewedUrl = "";
        renderPreview();
        updatePreviewButton();
        setMsg("已取消预览", true);
      };
      var doPreview = function(){
        if (previewed.length) { clearPreview(); return; }
        var u = String(urlInput.value || "").trim();
        if (!/^https?:\/\//i.test(u)) { setMsg("请输入有效的 http(s) 链接", false); return; }
        urlMsg.textContent = "正在识别…";
        urlMsg.className = "url-msg";
        var fd = new URLSearchParams();
        fd.append("action", "preview");
        fd.append("preview_url", u);
        fetch("/__SETTINGS_PATH__", { method: "POST", body: fd })
          .then(function(r){ return r.json(); })
          .then(function(d){
            if (d.ok && d.addresses && d.addresses.length) {
              previewed = d.addresses;
              previewedUrl = u;
              renderPreview();
              updatePreviewButton();
              setMsg("已识别 " + d.count + " 个节点，可删除不需要的节点后点击追加（追加会自动保存）", true);
            } else {
              previewed = [];
              previewedUrl = "";
              renderPreview();
              updatePreviewButton();
              setMsg(d.error || "无效链接", false);
            }
          })
          .catch(function(){ previewed = []; previewedUrl = ""; renderPreview(); updatePreviewButton(); setMsg("无效链接或无法访问", false); });
      };
      var submitMerged = function(extraNodes, srcUrl){
        var cur = (ta.value || "").split(/\r?\n/).map(function(s){ return s.trim(); }).filter(Boolean);
        var seen = {};
        cur.forEach(function(l){ seen[l] = 1; });
        var added = 0;
        extraNodes.forEach(function(l){ if (!seen[l]) { cur.push(l); seen[l] = 1; added++; } });
        ta.value = cur.join("\n");
        if (srcUrl) {
          var srcUrlInput = document.getElementById("source-url");
          var srcNodesInput = document.getElementById("source-nodes");
          if (srcUrlInput) srcUrlInput.value = srcUrl;
          if (srcNodesInput) srcNodesInput.value = JSON.stringify(extraNodes);
        }
        renderCheck();
        setMsg("已追加 " + added + " 个新节点，正在保存…", true);
        ta.form.submit();
      };
      var doAppend = function(){
        // 如果用户已点击预览，直接追加当前预览列表中的节点（保留用户在预览中删除筛选的结果），无需重复抓取
        if (previewedUrl) {
          if (!previewed.length) {
            setMsg("预览中的节点已全部删除，无可追加节点", false);
            return;
          }
          submitMerged(previewed, previewedUrl);
          return;
        }
        var u = String(urlInput.value || "").trim();
        if (/^https?:\/\//i.test(u)) {
          // 未预览时直接追加链接：校验有效性并抓取追加
          urlMsg.textContent = "正在校验链接并抓取节点…";
          urlMsg.className = "url-msg";
          var fd = new URLSearchParams();
          fd.append("action", "preview");
          fd.append("preview_url", u);
          fetch("/__SETTINGS_PATH__", { method: "POST", body: fd })
            .then(function(r){ return r.json(); })
            .then(function(d){
              if (d.ok && d.addresses && d.addresses.length) {
                submitMerged(d.addresses, u);
              } else {
                setMsg(d.error || "链接无效或无法访问", false);
              }
            })
            .catch(function(){ setMsg("无效链接或无法访问", false); });
          return;
        }
        setMsg("请输入节点链接，或先点击预览", false);
      };
      urlInput.addEventListener("input", function(){
        if (previewedUrl && String(urlInput.value || "").trim() !== previewedUrl) {
          previewed = [];
          previewedUrl = "";
          renderPreview();
          updatePreviewButton();
        }
      });
      previewBtn.addEventListener("click", doPreview);
      document.getElementById("url-append").addEventListener("click", doAppend);
      document.querySelectorAll(".source-remove").forEach(function(btn){
        btn.addEventListener("click", function(){
          var url = btn.getAttribute("data-source-url");
          if (!url || !confirm("删除该链接来源后，其生成的节点也会一并移除，确定删除吗？")) return;
          var fd = new URLSearchParams();
          fd.append("action", "remove_source");
          fd.append("source_url", url);
          fetch("/__SETTINGS_PATH__", { method: "POST", body: fd })
            .then(function(){ location.href = "/__SETTINGS_PATH__?removed=1"; })
            .catch(function(){ alert("删除失败，请重试"); });
        });
      });
    })();
    </script>
  </form>
  <div class="link-count">将生成 <strong>__PROTO_COUNT__</strong> 种代理协议 × <strong>__CONN_COUNT__</strong> 种传输方式（含兼容性过滤）× <strong>__ADDRESS_COUNT__</strong> 个节点 = <strong>__TOTAL_COUNT__</strong> 条链接</div>
</div>
</body>
</html>"""
    return (template
            .replace("__SETTINGS_PATH__", SETTINGS_PATH)
            .replace("__ADVICES_PATH__", SETTINGS_PATH)
            .replace("__SUBLINK_PATH__", SUBLINK_PATH)
            .replace("__FEED_PATH__", SUBLINK_PATH)
            .replace("__SAVED_ALERT__", saved_alert)
            .replace("__REMOVED_ALERT__", removed_alert)
            .replace("__DOMAIN_ERROR_ALERT__", domain_error_alert)
            .replace("__SAVE_ERROR_ALERT__", save_error_alert)
            .replace("__CONN_WS_CHECKED__", conn_ws_checked)
            .replace("__CONN_GRPC_CHECKED__", conn_grpc_checked)
            .replace("__CONN_XHTTP_CHECKED__", conn_xhttp_checked)
            .replace("__PROTO_A_CHECKED__", proto_a_checked)
            .replace("__PROTO_B_CHECKED__", proto_b_checked)
            .replace("__PROTO_C_CHECKED__", proto_c_checked)
            .replace("__ADDRESS_TEXT__", address_text)
            .replace("__NODE_NAME_TEXT__", node_name_text)
            .replace("__NAME_READONLY_ATTR__", name_readonly_attr)
            .replace("__NAME_HINT_TEXT__", name_hint_text)
            .replace("__DIRECT_DOMAIN_TEXT__", direct_domain_text)
            .replace("__DIRECT_TLS_CHECKED__", direct_tls_checked_attr)
            .replace("__DIRECT_TLS_DISABLED__", direct_tls_disabled_attr)
            .replace("__GATEWAY_DOMAIN_TEXT__", gateway_domain_text)
            .replace("__AUTO_UPDATE_CHECKED__", auto_update_checked)
            .replace("__UPDATE_INTERVAL__", update_interval_text)
            .replace("__SOURCES_HTML__", sources_html)
            .replace("__PROTO_COUNT__", str(proto_count))
            .replace("__CONN_COUNT__", str(conn_count))
            .replace("__ADDRESS_COUNT__", str(group_count))
            .replace("__TOTAL_COUNT__", str(total_count)))


_isp = "Unknown"
_last_isp_time = 0.0
ISP_CACHE_TTL = 5 * 60


async def _http_get_json(url, timeout=3.0):
    def _get():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    return await asyncio.to_thread(_get)


async def getisp():
    global _isp, _last_isp_time
    if _last_isp_time and time.time() - _last_isp_time < ISP_CACHE_TTL:
        return
    try:
        data = json.loads(await _http_get_json("https://api.ip.sb/geoip", 3.0))
        _isp = f"{data.get('country_code', '')}-{data.get('isp', '')}".replace(" ", "_")
        _last_isp_time = time.time()
        return
    except Exception:
        pass
    try:
        data = json.loads(await _http_get_json("http://ip-api.com/json", 3.0))
        _isp = f"{data.get('countryCode', '')}-{data.get('org', '')}".replace(" ", "_")
        _last_isp_time = time.time()
        return
    except Exception:
        _isp = "Unknown"


async def get_fallback_config():
    try:
        data = await _http_get_json("https://api-ipv4.ip.sb/ip", 5.0)
        ip = data.decode("utf-8", "replace").strip()
        return {"address": ip, "tlsDomain": ip, "tls": False, "port": PORT, "label": "直连"}
    except Exception:
        return {"address": "cahnge-your-domain.com", "tlsDomain": "cahnge-your-domain.com",
                "tls": True, "port": 443, "label": "直连"}


def get_link_configs():
    cfg = get_advices_config()
    addresses = cfg["addresses"]
    direct_domain = cfg.get("directDomain", DIRECT_DOMAIN or "")
    gateway_domain = cfg.get("gatewayDomain", GATEWAY_DOMAIN or "")
    eff_direct_domain = bool(direct_domain) and direct_domain != "your-domain.com"
    eff_gateway_domain = bool(gateway_domain) and gateway_domain != "your-domain.com"


    gateway_host = gateway_domain
    if eff_gateway_domain:
        p = parse_domain_input(gateway_domain)
        gateway_host = p["host"] if p and p["ok"] else gateway_domain

    configs = []

    if eff_direct_domain:
        p = parse_domain_input(direct_domain)
        host = p["host"] if p and p["ok"] else direct_domain
        port = p["port"] if p and p["ok"] else 443
        # 直连域名证书校验开关：
        # 若 directDomainTls 为 False（关闭证书校验，如使用自签证书 tls internal），
        # 仍使用 TLS（因为 Caddy 监听 HTTPS），并在节点链接中附加 allowInsecure=1；
        # 若 directDomainTls 为 True（开启证书校验，如使用 ACME 证书），使用标准 TLS 校验。
        direct_tls = cfg.get("directDomainTls")
        tls_verify = True if direct_tls is None else bool(direct_tls)
        configs.append({
            "address": host,
            "tlsDomain": host,
            "tls": True,
            "allowInsecure": not tls_verify,
            "port": port,
            "label": "直连",
            "excluded": set(),
        })


    if eff_gateway_domain and addresses:
        for index, address in enumerate(addresses):
            parsed = parse_addr_line(address)
            host = parsed["host"] if parsed and parsed["ok"] else address
            _, excluded = parse_node_protocol_note(address)
            configs.append({
                "address": host,
                "tlsDomain": gateway_host,
                "tls": True,
                "port": parsed["port"] if parsed and parsed["ok"] else 443,
                "label": f"优选{index + 1}",
                "excluded": excluded,
            })
    elif eff_gateway_domain:

        preferred = PREFERRED_IP or gateway_host
        pp = parse_addr_line(preferred)
        pref_host = pp["host"] if pp and pp["ok"] else preferred
        pref_port = pp["port"] if pp and pp["ok"] else 443
        _, excluded = parse_node_protocol_note(preferred)
        configs.append({
            "address": pref_host,
            "tlsDomain": gateway_host,
            "tls": True,
            "port": pref_port,
            "label": "连接优选" if PREFERRED_IP else "连接",
            "excluded": excluded,
        })


    if not configs:
        configs.append(None)
    return configs


def build_link_list(config, name_part, modes=None, node_name=None):
    modes = modes or {}
    proto_modes = modes.get("proto") or DEFAULT_MODES
    conn_modes = modes.get("conn") or DEFAULT_CONN_MODES
    eff_name = (node_name if node_name is not None
                else ((get_advices_config().get("name") if get_advices_config() else None) or NAME or "")).strip()
    link_name = f"{eff_name}-{config['label']}-{name_part}" if eff_name else f"{config['label']}-{name_part}"
    tls_param = "tls" if config.get("tls", True) else "none"
    allow_insecure = bool(config.get("allowInsecure"))
    excluded = set(config.get("excluded") or [])
    urls = []
    for proto in ("a", "b", "c"):
        if not proto_modes.get(proto) or proto in excluded:
            continue
        for conn in ("ws", "grpc", "xhttp"):
            if not conn_modes.get(conn):
                continue
            if proto == "c":
                # SS 仅支持 WS，且使用 v2ray-plugin websocket（edgetunnel 标准格式）。
                # 链接为 ss://base64(method:password)@host:port?plugin=...，
                # path 内嵌 ?enc=<加密方式>，服务端据此识别 SS 入站。
                if conn != "ws":
                    continue
                ss_method = "aes-128-gcm"
                ss_auth = base64.urlsafe_b64encode(
                    f"{ss_method}:{APP_KEY}".encode("utf-8")
                ).decode("ascii").rstrip("=")
                ss_base = f"{SCHEME_C}://{ss_auth}@{config['address']}:{config['port']}"
                ss_plugin = (
                    "v2ray-plugin;mode=websocket"
                    f";host={config['tlsDomain']}"
                    f";path=/{API_PATH}?enc={ss_method}"
                    + (";tls" if config.get("tls", True) else "")
                    + ";mux=0"
                )
                urls.append(
                    f"{ss_base}?plugin={urllib.parse.quote(ss_plugin, safe='')}#{link_name}"
                )
                continue
            transport = conn
            if conn == "grpc":
                # 仿照 vless+WS 的链接结构（host/path 齐全）生成 gRPC 链接：
                # Karing 对带 host+path 的 HTTP 类传输（ws/xhttp）会完整解析
                # TLS（server_name/utls），唯独 gRPC 分支只读 serviceName 会丢
                # server_name（TLS 用 IP 握手导致超时）。这里同时输出
                # serviceName 与 path（值一致），并附加 mode=gun 和 authority，兼容 Karing/sing-box/Xray/v2rayNG。
                path_param = f"serviceName={API_PATH}&path=%2F{API_PATH}&mode=gun&authority={config['tlsDomain']}"
            elif conn == "ws":
                path_param = f"path=%2F{API_PATH}"
            else:
                # XHTTP 节点必须带 extra padding 配置，否则客户端不启用 padding。
                # extra 用 Base64URL 编码（sing-box-extended/Karing 的解析格式），
                # 字段同时兼容 Xray（xPaddingObfsMode 等）与 sing-box-extended（xPaddingBytes）。
                padding_header, padding_key = _xhttp_padding_ident(APP_KEY)
                padding_json = json.dumps({
                    "xPaddingObfsMode": True,
                    "xPaddingMethod": "tokenish",
                    "xPaddingPlacement": "queryInHeader",
                    "xPaddingHeader": padding_header,
                    "xPaddingKey": padding_key,
                    "xPaddingBytes": "100-1000",
                }, separators=(",", ":"))
                padding_b64 = base64.urlsafe_b64encode(padding_json.encode("utf-8")).decode("ascii").rstrip("=")
                path_param = (
                    f"path=%2F{API_PATH}&mode={MODE_FLOW}"
                    f"&extra={padding_b64}"
                )
            if proto == "a":
                base = f"{SCHEME_A}://{APP_KEY}@{config['address']}:{config['port']}"
                base_params = [f"encryption=none"]
            elif proto == "b":
                base = f"{SCHEME_B}://{APP_KEY}@{config['address']}:{config['port']}"
                base_params = []
            query = base_params + [
                f"security={tls_param}",
                f"sni={config['tlsDomain']}",
                f"serverName={config['tlsDomain']}",
                "fp=chrome",
                f"type={transport}",
                f"host={config['tlsDomain']}",
                path_param,
            ]
            if allow_insecure:
                query.append("allowInsecure=1")
            urls.append(f"{base}?{'&'.join(query)}#{link_name}")
    return urls


class BodyReader:
    async def read(self, n):
        raise NotImplementedError


class SizedBodyReader(BodyReader):
    def __init__(self, reader, length):
        self._reader = reader
        self._left = length

    async def read(self, n):
        if self._left <= 0:
            return b""
        data = await self._reader.read(min(n, self._left))
        self._left -= len(data)
        return data


class EmptyBodyReader(BodyReader):
    async def read(self, n):
        return b""


class ChunkedBodyReader(BodyReader):
    def __init__(self, reader):
        self._reader = reader
        self._left = 0
        self._done = False

    async def read(self, n):
        if self._done:
            return b""
        if self._left == 0:
            line = await self._reader.readuntil(b"\r\n")
            size = int(line.split(b";", 1)[0].strip(), 16)
            if size == 0:

                while True:
                    line = await self._reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break
                self._done = True
                return b""
            self._left = size
        data = await self._reader.read(min(n, self._left))
        self._left -= len(data)
        if self._left == 0:
            await self._reader.readuntil(b"\r\n")
        return data


class PreloadReader:
    """带预读缓冲的 asyncio StreamReader 包装，支持 H2 preface 探测。"""

    def __init__(self, reader, initial=b""):
        self._reader = reader
        self._buf = bytearray(initial)

    def at_eof(self):
        return not self._buf and self._reader.at_eof()

    async def read(self, n=-1):
        if self._buf:
            if n < 0 or n >= len(self._buf):
                data = bytes(self._buf)
                self._buf.clear()
                return data
            data = bytes(self._buf[:n])
            del self._buf[:n]
            return data
        return await self._reader.read(n)

    async def readexactly(self, n):
        if n <= 0:
            return b""
        if len(self._buf) >= n:
            data = bytes(self._buf[:n])
            del self._buf[:n]
            return data
        prefix = bytes(self._buf)
        self._buf.clear()
        return prefix + await self._reader.readexactly(n - len(prefix))

    async def readline(self):
        while True:
            idx = self._buf.find(b"\n")
            if idx >= 0:
                end = idx + 1
                data = bytes(self._buf[:end])
                del self._buf[:end]
                return data
            if not self._buf:
                return await self._reader.readline()
            chunk = await self._reader.read(65536)
            if not chunk:
                data = bytes(self._buf)
                self._buf.clear()
                return data
            self._buf.extend(chunk)

    async def readuntil(self, separator):
        if not separator:
            raise ValueError("empty separator")
        while True:
            idx = self._buf.find(separator)
            if idx >= 0:
                end = idx + len(separator)
                data = bytes(self._buf[:end])
                del self._buf[:end]
                return data
            if len(self._buf) > 1024 * 1024:
                raise ValueError("separator not found")
            chunk = await self._reader.read(65536)
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(self._buf), None)
            self._buf.extend(chunk)


class HttpRequest:
    def __init__(self, method, path, raw_query, version, headers, reader, writer):
        self.method = method
        self.path = path
        self.raw_query = raw_query
        self.query = urllib.parse.parse_qs(raw_query, keep_blank_values=True)
        self.version = version
        self.headers = headers
        self.reader = reader
        self.writer = writer

    def header(self, name):
        vals = self.headers.get(name.lower())
        return vals[0] if vals else None

    def body_reader(self):
        te = self.header("transfer-encoding") or ""
        if "chunked" in te.lower():
            return ChunkedBodyReader(self.reader), None
        cl = self.header("content-length")
        if cl is not None:
            try:
                n = int(cl)
            except ValueError:
                return None, 400
            if n < 0 or n > MAX_POST_BYTES + 1024:
                return None, 413
            return SizedBodyReader(self.reader, n), None
        return EmptyBodyReader(), None


async def read_request(reader, writer, initial=b""):
    if initial:
        reader = PreloadReader(reader, initial)
    request_line = await asyncio.wait_for(reader.readline(), HEADER_TIMEOUT)
    if not request_line:
        return None
    parts = request_line.rstrip(b"\r\n").split(b" ")
    if len(parts) < 3:
        return None
    method = parts[0].decode("ascii", "replace")
    target = parts[1].decode("ascii", "replace")
    version = parts[2].decode("ascii", "replace")
    if target.startswith("http://") or target.startswith("https://"):
        target = urllib.parse.urlsplit(target).path or "/"
    path, _, raw_query = target.partition("?")
    headers = {}
    while True:
        line = await asyncio.wait_for(reader.readline(), HEADER_TIMEOUT)
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if len(line) > 8192:
            return None
        text = line.decode("latin-1").rstrip("\r\n")
        if ":" not in text:
            return None
        name, _, value = text.partition(":")
        key = name.strip().lower()
        headers.setdefault(key, []).append(value.strip())
    return HttpRequest(method, path, raw_query, version, headers, reader, writer)


async def send_simple(writer, status, reason, headers, body=b""):
    head = f"HTTP/1.1 {status} {reason}\r\n"
    for k, v in headers:
        head += f"{k}: {v}\r\n"
    head += f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    writer.write(head.encode("latin-1") + body)
    await writer.drain()


def _is_ip(s):
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _doh_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/dns-json",
    })
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


async def resolve_host(host):
    if _is_ip(host):
        return host
    for url in (
        f"https://dns.google/resolve?name={urllib.parse.quote(host)}&type=A",
        f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(host)}&type=A",
    ):
        try:
            data = json.loads(await asyncio.to_thread(_doh_get, url))
            for answer in data.get("Answer") or []:
                if answer.get("type") == 1:
                    return answer["data"]
        except Exception:
            continue
    return None


def _parse_multipart_form(body, content_type):
    """解析 multipart/form-data 请求体，返回 {name: [value,...]}；解析失败返回 None。"""
    boundary = None
    for seg in content_type.split(";")[1:]:
        seg = seg.strip()
        if seg.lower().startswith("boundary="):
            boundary = seg[len("boundary="):].strip('"')
            break
    if not boundary or not body:
        return None
    delim = b"--" + boundary.encode("utf-8", "replace")
    parts = body.split(delim)
    result = {}
    for block in parts:
        block = block.strip(b"\r\n")
        if not block or block == b"--":
            continue
        header_end = block.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers = block[:header_end].decode("utf-8", "replace")
        value = block[header_end + 4:]
        if value.endswith(b"\r\n"):
            value = value[:-2]
        name = None
        for hline in headers.split("\r\n"):
            if hline.lower().startswith("content-disposition:"):
                m = re.search(r'name="([^"]*)"', hline, re.I)
                if m:
                    name = m.group(1)
                break
        if name is None:
            continue
        result.setdefault(name, []).append(value.decode("utf-8", "replace"))
    return result


async def _handle_advices(req):
    if req.method == "POST":
        body_reader, err = req.body_reader()
        if err:
            await send_simple(req.writer, 400, "Bad Request", [], b"bad request")
            return
        body = b""
        while True:
            chunk = await body_reader.read(65536)
            if not chunk:
                break
            if len(body) + len(chunk) > 1024 * 1024:
                await send_simple(req.writer, 413, "Payload Too Large", [], "请求体过大".encode("utf-8"))
                return
            body += chunk
        content_type_raw = (req.header("content-type") or "").strip()
        if content_type_raw.lower().startswith("multipart/form-data"):
            params = _parse_multipart_form(body, content_type_raw)
            if params is None:
                await send_simple(req.writer, 400, "Bad Request", [], "无法解析表单数据".encode("utf-8"))
                return
        else:
            params = urllib.parse.parse_qs(body.decode("utf-8", "replace"))

        if params.get("action") == ["test_db"]:
            res = await asyncio.to_thread(_db_test_connection)
            body_text = json.dumps(res, ensure_ascii=False)
            await send_simple(req.writer, 200, "OK",
                              [("Content-Type", "application/json; charset=utf-8")],
                              body_text.encode("utf-8"))
            return

        if params.get("action") == ["preview"]:
            # 预览接口：抓取节点链接并返回识别到的地址（供前端预览/追加）
            preview_url = (params.get("preview_url", [""])[0] or "").strip()
            if not preview_url or not (preview_url.startswith("http://") or preview_url.startswith("https://")):
                payload = {"ok": False, "count": 0, "skipped": 0, "addresses": [], "error": "无效链接"}
            else:
                addrs, skipped = fetch_url_addresses(preview_url)
                if addrs:
                    payload = {"ok": True, "count": len(addrs), "skipped": skipped, "addresses": addrs, "error": ""}
                elif skipped:
                    payload = {"ok": False, "count": 0, "skipped": skipped, "addresses": [], "error": "无效链接或无法访问"}
                else:
                    payload = {"ok": False, "count": 0, "skipped": 0, "addresses": [], "error": "未识别到有效节点地址"}
            body_text = json.dumps(payload, ensure_ascii=False)
            await send_simple(req.writer, 200, "OK",
                              [("Content-Type", "application/json; charset=utf-8")],
                              body_text.encode("utf-8"))
            return

        if params.get("action") == ["remove_source"]:
            # 删除某个链接来源：同时移除该来源生成的节点
            source_url = (params.get("source_url", [""])[0] or "").strip()
            cfg = get_advices_config()
            au = cfg.get("autoUpdate") or {}
            sources = au.get("sources") or {}
            if source_url in sources:
                old_nodes = set(sources[source_url].get("nodes") or [])
                cfg["addresses"] = [a for a in (cfg.get("addresses") or []) if a not in old_nodes]
                del sources[source_url]
                persist_advices_config(cfg)
            await send_simple(req.writer, 302, "Found",
                              [("Location", f"/{ADVICES_PATH}?removed=1")], b"")
            return

        def checked(name):
            return params.get(name) == ["1"]

        conn_value = (params.get("conn_mode", [""])[0] or "").strip().lower()
        if conn_value not in ("ws", "grpc", "xhttp"):
            # 兼容旧表单：conn_ws/conn_grpc/conn_xhttp 多选字段，取第一个启用项
            legacy_conn = {
                "ws": checked("conn_ws"),
                "grpc": checked("conn_grpc"),
                "xhttp": checked("conn_xhttp"),
            }
            conn_value = next((k for k in ("ws", "grpc", "xhttp") if legacy_conn[k]), "ws")
        modes = {
            "conn": {
                "ws": conn_value == "ws",
                "grpc": conn_value == "grpc",
                "xhttp": conn_value == "xhttp",
            },
            "proto": {
                # 兼容旧表单字段名 mode_a/mode_b/mode_c
                "a": checked("proto_a") or checked("mode_a"),
                "b": checked("proto_b") or checked("mode_b"),
                "c": checked("proto_c") or checked("mode_c"),
            },
        }
        addresses = []
        skipped = 0
        url_sources = {}
        has_url_line = False

        # 解析显式由表单传入的来源链接及其最终保留的节点（支持预览删除筛选后精准记录来源）
        explicit_source_url = (params.get("source_url", [""])[0] or "").strip()
        explicit_source_nodes_raw = (params.get("source_nodes", [""])[0] or "").strip()
        if explicit_source_url and (explicit_source_url.startswith("http://") or explicit_source_url.startswith("https://")):
            explicit_nodes = []
            if explicit_source_nodes_raw:
                try:
                    parsed_nodes = json.loads(explicit_source_nodes_raw)
                    if isinstance(parsed_nodes, list):
                        explicit_nodes = [str(n).strip() for n in parsed_nodes if str(n).strip()]
                except (ValueError, TypeError):
                    explicit_nodes = []
            url_sources[explicit_source_url] = {"nodes": explicit_nodes, "lastUpdated": time.time()}

        for raw_line in (params.get("addresses", [""])[0]).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("http://") or line.startswith("https://"):
                # URL 行：抓取列表并展开为节点地址（如优选 IP 文本列表）
                has_url_line = True
                fetched, fetch_skipped = fetch_url_addresses(line)
                for addr in fetched:
                    if addr not in addresses:
                        addresses.append(addr)
                skipped += fetch_skipped
                if fetched:
                    url_sources[line] = {"nodes": fetched, "lastUpdated": time.time()}
                if not fetched:
                    skipped += 1
                continue
            parsed = parse_addr_line(line)
            if parsed is None:
                continue
            if parsed["ok"]:
                # 保留原始行（含 #备注），备注用于标注节点不支持的协议
                addresses.append(parsed["raw"].strip())
            else:
                skipped += 1
        if has_url_line:
            # 表单包含链接行时采用累积语义：保留现有全部节点，只追加链接节点，
            # 避免用第二个链接保存时把之前保存的节点全部覆盖。
            old_addresses = get_advices_config().get("addresses") or []
            seen = set(addresses)
            for addr in old_addresses:
                if addr not in seen:
                    addresses.append(addr)
                    seen.add(addr)
        node_name = (params.get("name", [""])[0]).strip()
        direct_domain = (params.get("direct_domain", [""])[0]).strip()
        gateway_domain = (params.get("gateway_domain", [""])[0]).strip()
        pd = parse_domain_input(direct_domain)
        xd = parse_domain_input(gateway_domain)
        domain_errors = []
        if not pd["ok"]:
            domain_errors.append("直连域名：" + pd["error"])
        if not xd["ok"]:
            domain_errors.append("套CDN域名：" + xd["error"])
        if domain_errors:
            location = f"/{SETTINGS_PATH}?domain_error=" + urllib.parse.quote(";".join(domain_errors))
            await send_simple(req.writer, 302, "Found", [("Location", location)], b"")
            return
        # 直连域名证书校验开关：由表单提交的 direct_domain_tls 决定
        direct_domain_tls_raw = (params.get("direct_domain_tls", [""])[0] or "").strip()
        direct_domain_tls = (direct_domain_tls_raw == "1")
        auto_update_enabled = checked("auto_update")
        try:
            interval_minutes = int((params.get("update_interval", [""])[0] or "").strip() or 720)
        except (TypeError, ValueError):
            interval_minutes = 720
        interval_minutes = max(1, interval_minutes)
        old_au = get_advices_config().get("autoUpdate") or {}
        sources = dict(old_au.get("sources") or {})
        for url, src in url_sources.items():
            sources[url] = src
        auto_update = {
            "enabled": auto_update_enabled,
            "intervalMinutes": interval_minutes,
            "sources": sources,
        }
        if not save_advices_config(modes, addresses, direct_domain, gateway_domain,
                                   auto_update=auto_update, direct_domain_tls=direct_domain_tls,
                                   name=node_name):
            await send_simple(req.writer, 302, "Found",
                              [("Location", f"/{SETTINGS_PATH}?save_error=1")], b"")
            return
        await send_simple(req.writer, 302, "Found",
                          [("Location", f"/{SETTINGS_PATH}?saved=1&skipped={skipped}")], b"")
        return

    saved = req.query.get("saved") == ["1"]
    save_error = req.query.get("save_error") == ["1"]
    removed = req.query.get("removed") == ["1"]
    try:
        skipped = int(req.query.get("skipped", ["0"])[0])
    except (ValueError, IndexError):
        skipped = 0
    domain_error = req.query.get("domain_error", [""])[0]
    html = render_advices_page(saved, skipped, domain_error, save_error, removed).encode("utf-8")
    await send_simple(req.writer, 200, "OK",
                      [("Content-Type", "text/html; charset=utf-8")], html)


async def _handle_feed(req):
    await getisp()
    configs = get_link_configs()
    if configs == [None]:
        configs = [await get_fallback_config()]
    modes = get_advices_config()["modes"]
    conn_modes = modes.get("conn") or DEFAULT_CONN_MODES
    proto_modes = modes.get("proto") or DEFAULT_MODES

    urls = []
    for config in configs:
        urls.extend(build_link_list(config, _isp, modes))
    content = "\n".join(urls)
    body = base64.b64encode(content.encode("utf-8")) + b"\n"
    await send_simple(req.writer, 200, "OK",
                      [("Content-Type", "text/plain; charset=utf-8")], body)


def _uuid_bytes(uuid_text):
    clean = (uuid_text or "").replace("-", "")
    if len(clean) != 32:
        return None
    try:
        return bytes.fromhex(clean)
    except ValueError:
        return None


def _parse_vless_edt(buf):
    """edgetunnel 风格 VLESS 首包：version+UUID+addon+cmd+port+atype+addr+payload。"""
    n = len(buf)
    if n < 18:
        return None, False
    expected = _uuid_bytes(APP_KEY)
    if expected is None or buf[1:17] != expected:
        return None, True
    cmd_idx = 18 + buf[17]
    if n < cmd_idx + 4:
        return None, False
    cmd = buf[cmd_idx]
    if cmd not in (1, 2):
        return None, True
    port = int.from_bytes(buf[cmd_idx + 1:cmd_idx + 3], "big")
    atyp = buf[cmd_idx + 3]
    addr_idx = cmd_idx + 4
    if atyp == 1:
        if n < addr_idx + 4:
            return None, False
        host = ".".join(str(b) for b in buf[addr_idx:addr_idx + 4])
        offset = addr_idx + 4
    elif atyp == 2:
        if n < addr_idx + 1:
            return None, False
        alen = buf[addr_idx]
        if n < addr_idx + 1 + alen:
            return None, False
        host = buf[addr_idx + 1:addr_idx + 1 + alen].decode("utf-8", "replace")
        offset = addr_idx + 1 + alen
    elif atyp == 3:
        if n < addr_idx + 16:
            return None, False
        host = str(ipaddress.IPv6Address(buf[addr_idx:addr_idx + 16]))
        offset = addr_idx + 16
    else:
        return None, True
    if not host:
        return None, True
    return {
        "protocol": "vless",
        "host": host,
        "port": port,
        "udp": cmd == 2,
        "version": buf[0],
        "offset": offset,
    }, False


def _parse_trojan_edt(buf):
    """edgetunnel 风格 Trojan 首包：sha224(密码) hex + CRLF + cmd + atype + addr + port + CRLF。"""
    n = len(buf)
    if n < 58:
        return None, False
    if buf[:56] != TROJAN_HASH_BYTES or buf[56:58] != b"\r\n":
        return None, True
    if n < 60:
        return None, False
    cmd = buf[58]
    if cmd not in (1, 3):
        return None, True
    atyp = buf[59]
    addr_idx = 60
    if atyp == 1:
        if n < addr_idx + 4 + 4:
            return None, False
        host = ".".join(str(b) for b in buf[addr_idx:addr_idx + 4])
        addr_len = 4
    elif atyp == 3:
        if n < addr_idx + 1:
            return None, False
        alen = buf[addr_idx]
        if n < addr_idx + 1 + alen + 4:
            return None, False
        host = buf[addr_idx + 1:addr_idx + 1 + alen].decode("utf-8", "replace")
        addr_len = 1 + alen
    elif atyp == 4:
        if n < addr_idx + 16 + 4:
            return None, False
        host = str(ipaddress.IPv6Address(buf[addr_idx:addr_idx + 16]))
        addr_len = 16
    else:
        return None, True
    if not host:
        return None, True
    port_idx = addr_idx + addr_len
    port = int.from_bytes(buf[port_idx:port_idx + 2], "big")
    if buf[port_idx + 2:port_idx + 4] != b"\r\n":
        return None, True
    return {
        "protocol": "trojan",
        "host": host,
        "port": port,
        "udp": cmd == 3,
        "version": 0,
        "offset": port_idx + 4,
    }, False


def parse_edt_header(buf):
    """按 edgetunnel 顺序先 Trojan 后 VLESS 解析，返回 (parsed, state)。"""
    trojan, trojan_invalid = _parse_trojan_edt(buf)
    if trojan is not None:
        return trojan, "ok"
    vless, vless_invalid = _parse_vless_edt(buf)
    if vless is not None:
        return vless, "ok"
    if trojan_invalid and vless_invalid:
        return None, "invalid"
    return None, "need_more"


def _xhttp_padding_ident(uuid_text):
    return uuid_text[1:7], "_" + uuid_text[25:31]


def _hpack_huffman_len(text):
    total = 0
    for b in text.encode("utf-8"):
        total += HPACK_HUFFMAN_LENGTHS[b]
    return (total + 7) // 8


def _xhttp_padding_value(req, header_name, query_key):
    hv = req.header(header_name)
    if hv:
        try:
            parsed = urllib.parse.urlsplit(hv if "://" in hv else "https://x.invalid/" + hv.lstrip("/"))
            q = urllib.parse.parse_qs(parsed.query)
            if q.get(query_key):
                return q[query_key][0]
        except ValueError:
            pass
        return hv
    vals = req.query.get(query_key)
    return vals[0] if vals else ""


def _xhttp_padding_valid(value):
    if not value:
        return True
    return 98 <= _hpack_huffman_len(value) <= 1002


def _random_xhttp_padding():
    length = random.randint(100, 1000)
    return "".join(random.choice(XHTTP_BASE62) for _ in range(length))


def _xhttp_standard_request(req):
    """识别 sing-box/Karing 标准 XHTTP 请求（默认在 Referer 中携带 x_padding）。"""
    referer = req.header("referer") or ""
    if referer:
        try:
            parsed = urllib.parse.urlsplit(referer if "://" in referer else "https://x.invalid/" + referer.lstrip("/"))
            if urllib.parse.parse_qs(parsed.query).get("x_padding"):
                return True
        except ValueError:
            pass
    return bool(req.query.get("x_padding"))


async def _send_stream_head(writer, status, reason, headers):
    head = f"HTTP/1.1 {status} {reason}\r\n"
    for k, v in headers:
        head += f"{k}: {v}\r\n"
    head += "Transfer-Encoding: chunked\r\n"
    head += "Connection: close\r\n\r\n"
    writer.write(head.encode("latin-1"))
    await writer.drain()


class _ChunkedSink:
    def __init__(self, writer, prefix=b""):
        self.writer = writer
        self.prefix = prefix
        self._lock = asyncio.Lock()
        self._closed = False

    async def send(self, data):
        if not data or self._closed:
            return
        if self.prefix:
            data = self.prefix + data
            self.prefix = b""
        async with self._lock:
            self.writer.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
            await self.writer.drain()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.write(b"0\r\n\r\n")
            await self.writer.drain()
        except Exception:
            pass


class _GrpcChunkedSink(_ChunkedSink):
    async def send(self, data):
        await super().send(_grpc_frame_encode(data))


def _ws_accept_key(key):
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _ws_encode_frame(opcode, payload):
    b1 = 0x80 | opcode
    n = len(payload)
    if n < 126:
        head = bytes([b1, n])
    elif n <= 0xFFFF:
        head = bytes([b1, 126]) + struct.pack(">H", n)
    else:
        head = bytes([b1, 127]) + struct.pack(">Q", n)
    return head + payload


class WebSocketServer:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.prefix = b""
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def handshake(self, req):
        key = req.header("sec-websocket-key") or ""
        accept = _ws_accept_key(key)
        # 提高 asyncio 写缓冲水位：默认 high=64KB 会让每个大帧发送后立即等待
        # drain() 降到 32KB，公网高 RTT 下吞吐被锁死在 帧大小/RTT。调大后
        # 数据流水线化发送，TCP 层自行维持吞吐。
        try:
            self.writer.transport.set_write_buffer_limits(high=1024 * 1024, low=512 * 1024)
        except Exception:
            pass
        head = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "Sec-WebSocket-Extensions: \r\n"
            "\r\n"
        )
        self.writer.write(head.encode("latin-1"))
        await self.writer.drain()

    async def _recv_frame(self):
        head = await self.reader.readexactly(2)
        b1, b2 = head
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = int.from_bytes(await self.reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self.reader.readexactly(8), "big")
        mask = await self.reader.readexactly(4) if masked else None
        payload = await self.reader.readexactly(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return bool(b1 & 0x80), opcode, payload

    async def recv_message(self):
        opcode = None
        chunks = []
        total = 0
        while True:
            fin, op, payload = await self._recv_frame()
            if op == 8:
                await self.close()
                return None
            if op == 9:
                await self.send_frame(10, payload)
                continue
            if op == 10:
                continue
            if op in (1, 2):
                opcode = op
                chunks = []
            elif op == 0:
                if opcode is None:
                    raise ValueError("unexpected continuation frame")
            else:
                raise ValueError(f"unsupported opcode {op}")
            chunks.append(payload)
            total += len(payload)
            if total > WS_MAX_MESSAGE_BYTES:
                raise ValueError("websocket message too large")
            if fin:
                return b"".join(chunks)

    async def send_frame(self, opcode, payload):
        async with self._send_lock:
            if self._closed:
                return
            try:
                self.writer.write(_ws_encode_frame(opcode, payload))
                await self.writer.drain()
            except Exception:
                self._closed = True

    async def send(self, data):
        if not data:
            return
        if self.prefix:
            data = self.prefix + data
            self.prefix = b""
        await self.send_frame(2, data)

    async def close(self):
        async with self._send_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.writer.write(_ws_encode_frame(8, b""))
                await self.writer.drain()
            except Exception:
                pass


def _grpc_frame_encode(payload):
    plen = len(payload)
    if plen < 128:
        varint = bytes([plen])
    else:
        varint = b""
        while plen > 127:
            varint += bytes([(plen & 0x7F) | 0x80])
            plen >>= 7
        varint += bytes([plen])
    body = b"\x0a" + varint + payload
    return b"\x00" + struct.pack(">I", len(body)) + body


def _grpc_iter_frames(data, pending):
    merged = pending + data
    frames = []
    i = 0
    while len(merged) - i >= 5:
        length = int.from_bytes(merged[i + 1:i + 5], "big")
        frame_size = 5 + length
        if len(merged) - i < frame_size:
            break
        frame = merged[i + 5:i + frame_size]
        i += frame_size
        payload = frame
        if len(frame) >= 2 and frame[0] == 0x0A:
            j = 1
            while j < len(frame) and frame[j] & 0x80:
                j += 1
            if j < len(frame):
                payload = frame[j + 1:]
        if payload:
            frames.append(bytes(payload))
    return frames, bytes(merged[i:])


class _ProxySession:
    def __init__(self, sink):
        self.sink = sink
        self.reader = None
        self.writer = None
        self._ready = asyncio.Event()
        self._down_task = None

    @property
    def connected(self):
        return self.writer is not None

    async def connect(self, host, port):
        target_host = await resolve_host(host) or host
        try:
            reader, writer = await asyncio.open_connection(target_host, port)
        except OSError:
            if host == target_host:
                raise
            reader, writer = await asyncio.open_connection(host, port)
        _set_tcp_nodelay(writer)
        self.reader = reader
        self.writer = writer
        self._ready.set()
        self._down_task = asyncio.get_event_loop().create_task(self._pump_down())

    async def write_remote(self, data):
        if not data:
            return
        if not self._ready.is_set():
            await self._ready.wait()
        if self.writer is None:
            raise ConnectionError("remote connection closed")
        self.writer.write(data)
        await self.writer.drain()

    async def _pump_down(self):
        try:
            while True:
                data = await self.reader.read(65536)
                if not data:
                    break
                await self.sink.send(data)
        except Exception:
            pass
        finally:
            await self.sink.close()
            self._close_remote()

    def _close_remote(self):
        writer = self.writer
        self.writer = None
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass

    async def close(self):
        self._close_remote()
        if self._down_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._down_task), 5)
            except (asyncio.TimeoutError, Exception):
                self._down_task.cancel()
        await self.sink.close()

    async def end_upload(self):
        """上行结束后不发送 FIN：HTTP/1.1 请求体自带结束标志（Content-Length/chunked），
        主动半关闭会被 CDN（如 speed.cloudflare.com）误判为连接中断而不返回响应。
        保持连接等待下行读完整后再收尾。"""
        await self.wait_down()

    async def wait_down(self):
        """上行结束后保持远端连接，等待下行读完整再收尾。"""
        if self._down_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._down_task), 300)
            except asyncio.TimeoutError:
                self._down_task.cancel()
            except Exception:
                pass
        await self.sink.close()


async def _dns_tcp_query(query, sink, prefix=b"", trojan_frame=None):
    if len(query) < 2 or int.from_bytes(query[:2], "big") != len(query) - 2:
        query = struct.pack(">H", len(query)) + query
    try:
        reader, writer = await asyncio.open_connection("8.8.4.4", 53)
    except OSError:
        return
    try:
        writer.write(query)
        await writer.drain()
        pending = b""
        answered = False
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), 10)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            pending += chunk
            while len(pending) >= 2:
                n = int.from_bytes(pending[:2], "big")
                if len(pending) < 2 + n:
                    break
                payload = pending[2:2 + n]
                pending = pending[2 + n:]
                if prefix:
                    data = prefix + payload
                    prefix = b""
                elif trojan_frame:
                    data = trojan_frame + struct.pack(">H", len(payload)) + b"\r\n" + payload
                else:
                    data = payload
                if data:
                    await sink.send(data)
                # 单次查询只需第一个完整应答；立即收尾，
                # 避免上游 TCP keep-alive 导致 XHTTP 响应流无法结束
                answered = True
                break
            if answered:
                break
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def _trojan_udp_feed(data, sink, state):
    state["buf"] += data
    buf = state["buf"]
    i = 0
    while i < len(buf):
        atype = buf[i]
        j = i + 1
        if atype == 1:
            addr_len = 4
        elif atype == 4:
            addr_len = 16
        elif atype == 3:
            if j >= len(buf):
                break
            addr_len = 1 + buf[j]
        else:
            raise ValueError("invalid trojan udp addressType")
        port_cursor = j + addr_len
        if len(buf) < port_cursor + 6:
            break
        port = int.from_bytes(buf[port_cursor:port_cursor + 2], "big")
        payload_len = int.from_bytes(buf[port_cursor + 2:port_cursor + 4], "big")
        if buf[port_cursor + 4:port_cursor + 6] != b"\r\n":
            raise ValueError("invalid trojan udp delimiter")
        end = port_cursor + 6 + payload_len
        if len(buf) < end:
            break
        addr_header = buf[i:port_cursor + 2]
        payload = buf[port_cursor + 6:end]
        i = end
        if port != 53:
            raise ValueError("UDP is not supported")
        if not payload:
            continue
        await _dns_tcp_query(payload, sink, trojan_frame=addr_header)
    state["buf"] = buf[i:]


# ================= edgetunnel 移植：Shadowsocks AEAD（仅 WS 传输，enc 参数触发）=================
SS_CIPHERS = {
    "aes-128-gcm": {"method": "aes-128-gcm", "key_len": 16, "salt_len": 16, "max_chunk": 0x3FFF, "aes_bits": 128},
    "aes-256-gcm": {"method": "aes-256-gcm", "key_len": 32, "salt_len": 32, "max_chunk": 0x3FFF, "aes_bits": 256},
}
SS_TAG_LEN = 16
SS_NONCE_LEN = 12
SS_SUBKEY_INFO = b"ss-subkey"
# 标准 SS AEAD 最大 chunk 为 0x3FFF（16383），edgetunnel/shadowsocks 均以此为准；
# 超出会被部分客户端（Clash/旧内核）拒绝或异常，导致"能连但速度慢"。
SS_OUT_CHUNK = 0x3FFF

_AES_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
_AES_INV_SBOX = [0] * 256
for _i in range(256):
    _AES_INV_SBOX[_AES_SBOX[_i]] = _i
_AES_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _aes_xtime(b):
    b <<= 1
    if b & 0x100:
        b ^= 0x11B
    return b & 0xFF


def _aes_expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [key[4 * i:4 * i + 4] for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = bytearray(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = bytes(_AES_SBOX[b] for b in temp)
            temp = bytearray(temp)
            temp[0] ^= _AES_RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = bytearray(_AES_SBOX[b] for b in temp)
        w.append(bytes(w[i - nk][j] ^ temp[j] for j in range(4)))
    return nr, w


def _aes_encrypt_block(key, block):
    nr, w = _aes_expand_key(key)
    state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                state[r][c] ^= w[4 * rnd + c][r]
    def sub_bytes():
        for r in range(4):
            for c in range(4):
                state[r][c] = _AES_SBOX[state[r][c]]
    def shift_rows():
        for r in range(1, 4):
            state[r] = state[r][r:] + state[r][:r]
    def mix_columns():
        for c in range(4):
            a = [state[r][c] for r in range(4)]
            b = [state[r][c] for r in range(4)]
            for r in range(4):
                b[r] = _aes_xtime(b[r])
            state[0][c] = b[0] ^ a[3] ^ a[2] ^ b[1] ^ a[1]
            state[1][c] = b[1] ^ a[0] ^ a[3] ^ b[2] ^ a[2]
            state[2][c] = b[2] ^ a[1] ^ a[0] ^ b[3] ^ a[3]
            state[3][c] = b[3] ^ a[2] ^ a[1] ^ b[0] ^ a[0]
    add_round_key(0)
    for rnd in range(1, nr):
        sub_bytes(); shift_rows(); mix_columns(); add_round_key(rnd)
    sub_bytes(); shift_rows(); add_round_key(nr)
    return bytes(state[r][c] for c in range(4) for r in range(4))


def _aes_decrypt_block(key, block):
    nr, w = _aes_expand_key(key)
    state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                state[r][c] ^= w[4 * rnd + c][r]
    def inv_sub_bytes():
        for r in range(4):
            for c in range(4):
                state[r][c] = _AES_INV_SBOX[state[r][c]]
    def inv_shift_rows():
        for r in range(1, 4):
            state[r] = state[r][-r:] + state[r][:-r]
    def inv_mix_columns():
        def mul9(x):
            return _aes_xtime(_aes_xtime(_aes_xtime(x))) ^ x
        def mul11(x):
            return _aes_xtime(_aes_xtime(_aes_xtime(x))) ^ _aes_xtime(x) ^ x
        def mul13(x):
            return _aes_xtime(_aes_xtime(_aes_xtime(x))) ^ _aes_xtime(_aes_xtime(x)) ^ x
        def mul14(x):
            return _aes_xtime(_aes_xtime(_aes_xtime(x))) ^ _aes_xtime(_aes_xtime(x)) ^ _aes_xtime(x)
        for c in range(4):
            a = [state[r][c] for r in range(4)]
            state[0][c] = mul14(a[0]) ^ mul11(a[1]) ^ mul13(a[2]) ^ mul9(a[3])
            state[1][c] = mul9(a[0]) ^ mul14(a[1]) ^ mul11(a[2]) ^ mul13(a[3])
            state[2][c] = mul13(a[0]) ^ mul9(a[1]) ^ mul14(a[2]) ^ mul11(a[3])
            state[3][c] = mul11(a[0]) ^ mul13(a[1]) ^ mul9(a[2]) ^ mul14(a[3])
    add_round_key(nr)
    for rnd in range(nr - 1, 0, -1):
        inv_shift_rows(); inv_sub_bytes(); add_round_key(rnd); inv_mix_columns()
    inv_shift_rows(); inv_sub_bytes(); add_round_key(0)
    return bytes(state[r][c] for c in range(4) for r in range(4))


def _gcm_ghash_mul(y, h_int):
    z = 0
    v = h_int
    for _ in range(128):
        if y & (1 << 127):
            z ^= v
        if v & 1:
            v = (v >> 1) ^ (0xE1 << 120)
        else:
            v >>= 1
        y = (y << 1) & ((1 << 128) - 1)
    return z


def _gcm_ghash(h, data):
    h_int = int.from_bytes(h, "big")
    y = 0
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        if len(block) < 16:
            block = block + b"\x00" * (16 - len(block))
        y ^= int.from_bytes(block, "big")
        y = _gcm_ghash_mul(y, h_int)
    return y.to_bytes(16, "big")


def _gcm_inc32(ctr):
    n = (int.from_bytes(ctr[-4:], "big") + 1) & 0xFFFFFFFF
    return ctr[:-4] + n.to_bytes(4, "big")


def _aes_gcm_encrypt(key, iv, plaintext):
    if _FAST_AES_AVAILABLE:
        cipher = _FAST_AES.new(key, _FAST_AES.MODE_GCM, nonce=iv)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        return ct + tag
    h = _aes_encrypt_block(key, b"\x00" * 16)
    j0 = iv + b"\x00\x00\x00\x01"
    ctr = j0
    out = b""
    for i in range(0, len(plaintext), 16):
        ctr = _gcm_inc32(ctr)
        ks = _aes_encrypt_block(key, ctr)
        chunk = plaintext[i:i + 16]
        out += bytes(a ^ b for a, b in zip(ks, chunk))
    padded = out if len(out) % 16 == 0 else out + b"\x00" * (16 - len(out) % 16)
    s = _gcm_ghash(h, padded + (0).to_bytes(8, "big") + (len(out) * 8).to_bytes(8, "big"))
    tag = bytes(a ^ b for a, b in zip(_aes_encrypt_block(key, j0), s))
    return out + tag


def _aes_gcm_decrypt(key, iv, data):
    if len(data) < SS_TAG_LEN:
        raise ValueError("ss ciphertext too short")
    if _FAST_AES_AVAILABLE:
        cipher = _FAST_AES.new(key, _FAST_AES.MODE_GCM, nonce=iv)
        try:
            return cipher.decrypt_and_verify(data[:-SS_TAG_LEN], data[-SS_TAG_LEN:])
        except ValueError:
            raise ValueError("ss decrypt failed")
    ct, tag = data[:-SS_TAG_LEN], data[-SS_TAG_LEN:]
    h = _aes_encrypt_block(key, b"\x00" * 16)
    j0 = iv + b"\x00\x00\x00\x01"
    padded = ct if len(ct) % 16 == 0 else ct + b"\x00" * (16 - len(ct) % 16)
    s = _gcm_ghash(h, padded + (0).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big"))
    expect = bytes(a ^ b for a, b in zip(_aes_encrypt_block(key, j0), s))
    if not hmac.compare_digest(expect, tag):
        raise ValueError("ss decrypt failed")
    ctr = j0
    out = b""
    for i in range(0, len(ct), 16):
        ctr = _gcm_inc32(ctr)
        ks = _aes_encrypt_block(key, ctr)
        out += bytes(a ^ b for a, b in zip(ks, ct[i:i + 16]))
    return out


def _ss_master_key(password, key_len):
    pw = password.encode("utf-8")
    result = b""
    prev = b""
    while len(result) < key_len:
        prev = hashlib.md5(prev + pw).digest()
        result += prev
    return result[:key_len]


def _ss_hkdf_sha1(master_key, salt, key_len):
    prk = hmac.new(salt, master_key, hashlib.sha1).digest()
    out = b""
    prev = b""
    counter = 1
    while len(out) < key_len:
        prev = hmac.new(prk, prev + SS_SUBKEY_INFO + bytes([counter]), hashlib.sha1).digest()
        out += prev
        counter += 1
    return out[:key_len]


def _ss_inc_nonce(nonce):
    """Shadowsocks AEAD 标准（shadowsocks-libev/libsodium）：nonce 按 96 位无符号小端整数递增。"""
    for i in range(len(nonce)):
        nonce[i] = (nonce[i] + 1) & 0xFF
        if nonce[i] != 0:
            break


def _ss_aead_encrypt(key, nonce, plaintext):
    ct = _aes_gcm_encrypt(key, bytes(nonce), plaintext)
    _ss_inc_nonce(nonce)
    return ct


def _ss_aead_decrypt(key, nonce, ciphertext):
    pt = _aes_gcm_decrypt(key, bytes(nonce), ciphertext)
    _ss_inc_nonce(nonce)
    return pt


class _SSSession:
    """SS AEAD 入站解密 + 出站加密（与 edgetunnel 的入站解密器/出站加密器一致）。"""

    def __init__(self, enc_param):
        self.requested = (enc_param or "").lower()
        self.preferred = SS_CIPHERS.get(self.requested) or SS_CIPHERS["aes-128-gcm"]
        self.candidates = [self.preferred] + [
            c for m, c in SS_CIPHERS.items() if m != self.preferred["method"]
        ]
        self._master_cache = {}
        self.buf = b""
        self.has_salt = False
        self.wait_payload_len = None
        self.decrypt_key = None
        self.nonce = None
        self.cfg = None
        self.out_cfg = self.preferred
        self.out_key = None
        self.out_nonce = None
        self.out_salt_sent = False

    def _master_for(self, key_len):
        if key_len not in self._master_cache:
            self._master_cache[key_len] = _ss_master_key(APP_KEY, key_len)
        return self._master_cache[key_len]

    def _try_init(self):
        max_salt = max(c["salt_len"] for c in self.candidates)
        min_salt = min(c["salt_len"] for c in self.candidates)
        lct_len = 2 + SS_TAG_LEN
        max_offset = min(16, max(0, len(self.buf) - (lct_len + min_salt)))
        for offset in range(max_offset + 1):
            for cfg in self.candidates:
                need = offset + cfg["salt_len"] + lct_len
                if len(self.buf) < need:
                    continue
                salt = self.buf[offset:offset + cfg["salt_len"]]
                lct = self.buf[offset + cfg["salt_len"]:need]
                key = _ss_hkdf_sha1(self._master_for(cfg["key_len"]), salt, cfg["key_len"])
                nonce = bytearray(SS_NONCE_LEN)
                try:
                    lp = _ss_aead_decrypt(key, nonce, lct)
                except ValueError:
                    continue
                if len(lp) != 2:
                    continue
                payload_len = int.from_bytes(lp, "big")
                if payload_len < 0 or payload_len > cfg["max_chunk"]:
                    continue
                self.cfg = cfg
                self.decrypt_key = key
                self.nonce = nonce
                self.wait_payload_len = payload_len
                self.buf = self.buf[need:]
                self.has_salt = True
                return True
        fail_len = max_salt + lct_len + 16
        if len(self.buf) >= fail_len:
            raise ValueError("ss handshake decrypt failed")
        return False

    def feed(self, data):
        """入站：解密并返回明文块列表。"""
        self.buf += data
        if not self.has_salt:
            if not self._try_init():
                return []
        plains = []
        while True:
            if self.wait_payload_len is None:
                lct_len = 2 + SS_TAG_LEN
                if len(self.buf) < lct_len:
                    break
                lct = self.buf[:lct_len]
                self.buf = self.buf[lct_len:]
                lp = _ss_aead_decrypt(self.decrypt_key, self.nonce, lct)
                if len(lp) != 2:
                    raise ValueError("ss length decrypt failed")
                self.wait_payload_len = int.from_bytes(lp, "big")
                if self.wait_payload_len < 0 or self.wait_payload_len > self.cfg["max_chunk"]:
                    raise ValueError("ss payload length invalid")
            pct_len = self.wait_payload_len + SS_TAG_LEN
            if len(self.buf) < pct_len:
                break
            pct = self.buf[:pct_len]
            self.buf = self.buf[pct_len:]
            plain = _ss_aead_decrypt(self.decrypt_key, self.nonce, pct)
            self.wait_payload_len = None
            if plain:
                plains.append(plain)
        return plains

    def encrypt(self, data):
        """出站：首次发送随机 salt，之后每块 length+payload 双重 AEAD 加密。"""
        if not data:
            return b""
        if not self.out_salt_sent:
            salt = os.urandom(self.out_cfg["salt_len"])
            self.out_key = _ss_hkdf_sha1(
                self._master_for(self.out_cfg["key_len"]), salt, self.out_cfg["key_len"]
            )
            self.out_nonce = bytearray(SS_NONCE_LEN)
            self.out_salt_sent = True
            out = salt
        else:
            out = b""
        for i in range(0, len(data), SS_OUT_CHUNK):
            chunk = data[i:i + SS_OUT_CHUNK]
            out += _ss_aead_encrypt(self.out_key, self.out_nonce, struct.pack(">H", len(chunk)))
            out += _ss_aead_encrypt(self.out_key, self.out_nonce, chunk)
        return out


class _SSEncryptSink:
    def __init__(self, ws, ss):
        self.ws = ws
        self.ss = ss

    async def send(self, data):
        out = self.ss.encrypt(data)
        if out:
            await self.ws.send(out)

    async def close(self):
        await self.ws.close()


def _parse_ss_header(buf):
    if not buf:
        return None, "need_more"
    atyp = buf[0]
    cursor = 1
    if atyp == 1:
        if len(buf) < cursor + 4 + 2:
            return None, "need_more"
        host = ".".join(str(b) for b in buf[cursor:cursor + 4])
        cursor += 4
    elif atyp == 3:
        if len(buf) < cursor + 1:
            return None, "need_more"
        n = buf[cursor]
        cursor += 1
        if len(buf) < cursor + n + 2:
            return None, "need_more"
        host = buf[cursor:cursor + n].decode("utf-8", "replace")
        cursor += n
    elif atyp == 4:
        if len(buf) < cursor + 16 + 2:
            return None, "need_more"
        host = str(ipaddress.IPv6Address(buf[cursor:cursor + 16]))
        cursor += 16
    else:
        return None, "invalid"
    if not host:
        return None, "invalid"
    if len(buf) < cursor + 2:
        return None, "need_more"
    port = int.from_bytes(buf[cursor:cursor + 2], "big")
    return {"protocol": "ss", "host": host, "port": port, "offset": cursor + 2}, "ok"


def _decode_ws_early_data(header):
    if not header or len(header) > (WS_EARLY_DATA_MAX_BYTES * 4 // 3) + 4:
        return None
    normalized = header.replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    try:
        data = base64.b64decode(normalized)
    except Exception:
        return None
    if not data or len(data) > WS_EARLY_DATA_MAX_BYTES:
        return None
    parsed, state = parse_edt_header(data)
    return data if state == "ok" else None


class _GrpcSession:
    def __init__(self, sink):
        self.sink = sink
        self.session = _ProxySession(sink)
        self.pending = b""
        self.established = False
        self.udp_mode = None
        self.trojan_udp = {"buf": b""}

    async def feed(self, data):
        frames, self.pending = _grpc_iter_frames(data, self.pending)
        for payload in frames:
            await self._handle_payload(payload)

    async def _handle_payload(self, payload):
        if self.udp_mode == "vless":
            await _dns_tcp_query(payload, self.sink)
            return
        if self.udp_mode == "trojan":
            await _trojan_udp_feed(payload, self.sink, self.trojan_udp)
            return
        if not self.established:
            parsed, state = parse_edt_header(payload)
            if state != "ok":
                raise ValueError("invalid grpc header")
            if parsed["udp"]:
                if parsed["port"] != 53:
                    raise ValueError("UDP is not supported")
                if parsed["protocol"] == "vless":
                    self.udp_mode = "vless"
                    await self.sink.send(bytes([parsed["version"], 0]))
                    await _dns_tcp_query(payload[parsed["offset"]:], self.sink)
                else:
                    self.udp_mode = "trojan"
                    await _trojan_udp_feed(payload[parsed["offset"]:], self.sink, self.trojan_udp)
                return
            self.established = True
            if parsed["protocol"] == "vless":
                await self.sink.send(bytes([parsed["version"], 0]))
            await self.session.connect(parsed["host"], parsed["port"])
            await self.session.write_remote(payload[parsed["offset"]:])
            return
        await self.session.write_remote(payload)

    async def finish(self):
        await self.session.end_upload()
        await self.sink.close()


async def _handle_ws(req):
    ws = WebSocketServer(req.reader, req.writer)
    try:
        await ws.handshake(req)
    except Exception:
        return

    enc = (req.query.get("enc") or [""])[0]
    if enc:
        # edgetunnel 移植：Shadowsocks AEAD 入站（仅 WS，enc 参数触发），禁用 early-data
        ss = _SSSession(enc)
        session = _ProxySession(_SSEncryptSink(ws, ss))
        ss_established = False
        ss_buf = b""

        async def handle_message(data):
            nonlocal ss_established, ss_buf
            for plain in ss.feed(data):
                if ss_established:
                    await session.write_remote(plain)
                    continue
                ss_buf += plain
                parsed, state = _parse_ss_header(ss_buf)
                if state == "need_more":
                    continue
                if state == "invalid":
                    raise ValueError("invalid ss header")
                ss_established = True
                remaining = ss_buf[parsed["offset"]:]
                ss_buf = b""
                await session.connect(parsed["host"], parsed["port"])
                if remaining:
                    await session.write_remote(remaining)

        try:
            while True:
                message = await ws.recv_message()
                if message is None:
                    break
                await handle_message(message)
        except Exception:
            pass
        finally:
            await session.close()
            await ws.close()
        return

    session = _ProxySession(ws)
    header_buf = b""
    udp_mode = None
    trojan_udp = {"buf": b""}
    established = False
    ss_mode = False
    ss_session = None
    ss_buf = b""

    async def handle_message(data):
        nonlocal header_buf, udp_mode, established, ss_mode, ss_session, ss_buf, session
        if ss_mode:
            try:
                plains = ss_session.feed(data)
                for plain in plains:
                    await session.write_remote(plain)
            except Exception as e:
                raise
            return
        if udp_mode == "vless":
            await _dns_tcp_query(data, ws)
            return
        if udp_mode == "trojan":
            await _trojan_udp_feed(data, ws, trojan_udp)
            return
        if established:
            await session.write_remote(data)
            return
        header_buf += data
        parsed, state = parse_edt_header(header_buf)
        if state == "need_more":
            return
        if state == "invalid":
            # 非 VLESS/Trojan：尝试 Shadowsocks AEAD 自动识别。
            # 部分客户端（sing-box/Clash/sing-shadowsocks）会把 path 中的
            # ?enc= 编码成 %3F，query 无法送达，因此这里不依赖 enc 参数，
            # 直接用标准 AEAD 解密探测（tag 校验误判率极低）。
            try:
                probe = _SSSession("aes-128-gcm")
                plains = probe.feed(header_buf)
            except ValueError:
                raise ValueError("invalid websocket header")
            if plains:
                ss_session = probe
                ss_mode = True
                # SS 模式下响应必须经 AEAD 加密再走 WS，因此重建带 SS 加密 sink 的会话
                session = _ProxySession(_SSEncryptSink(ws, ss_session))
                for plain in plains:
                    ss_buf += plain
                    p2, s2 = _parse_ss_header(ss_buf)
                    if s2 == "need_more":
                        continue
                    if s2 == "invalid":
                        raise ValueError("invalid ss header")
                    established = True
                    remaining = ss_buf[p2["offset"]:]
                    ss_buf = b""
                    await session.connect(p2["host"], p2["port"])
                    if remaining:
                        await session.write_remote(remaining)
                    return
            # SS 首包不足，继续累积等待
            return
        if parsed["udp"]:
            if parsed["port"] != 53:
                raise ValueError("UDP is not supported")
            if parsed["protocol"] == "vless":
                udp_mode = "vless"
                ws.prefix = bytes([parsed["version"], 0])
                await _dns_tcp_query(header_buf[parsed["offset"]:], ws)
            else:
                udp_mode = "trojan"
                await _trojan_udp_feed(header_buf[parsed["offset"]:], ws, trojan_udp)
            return
        established = True
        if parsed["protocol"] == "vless":
            ws.prefix = bytes([parsed["version"], 0])
        await session.connect(parsed["host"], parsed["port"])
        await session.write_remote(header_buf[parsed["offset"]:])

    try:
        early = req.header("sec-websocket-protocol") or ""
        early_data = _decode_ws_early_data(early)
        if early_data:
            await handle_message(early_data)
        while True:
            message = await ws.recv_message()
            if message is None:
                break
            await handle_message(message)
    except Exception:
        pass
    finally:
        await session.close()
        await ws.close()


async def _handle_xhttp_raw(req, extra_headers=None, body_reader=None):
    """处理标准 XHTTP（sing-box/Karing stream-one）原始 VLESS/Trojan 流请求。

    请求体直接是 VLESS/Trojan 首包 + 后续数据（无 gRPC 帧），
    响应体为 chunked 原始代理流。
    """
    if body_reader is None:
        body_reader, err = req.body_reader()
        if err:
            await send_simple(req.writer, 400, "Bad Request", [], b"Bad Request")
            return
    buf = b""
    parsed = None
    while True:
        chunk = await body_reader.read(65536)
        if not chunk:
            await send_simple(req.writer, 400, "Invalid request", [], b"Invalid request")
            return
        buf += chunk
        parsed, state = parse_edt_header(buf)
        if state == "ok":
            break
        if state == "invalid":
            await send_simple(req.writer, 400, "Invalid request", [], b"Invalid request")
            return
        if len(buf) > 64 * 1024:
            await send_simple(req.writer, 400, "Invalid request", [], b"Invalid request")
            return

    # edgetunnel 对齐：VLESS UDP 仅允许 53（DNS），其余端口在发送响应头前直接 400
    if parsed["udp"] and parsed["protocol"] == "vless" and parsed["port"] != 53:
        await send_simple(req.writer, 400, "UDP is not supported", [], b"UDP is not supported")
        return

    headers = [
        ("Content-Type", "application/octet-stream"),
        ("X-Accel-Buffering", "no"),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "*"),
        ("Access-Control-Allow-Headers", "*"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await _send_stream_head(req.writer, 200, "OK", headers)
    sink = _ChunkedSink(req.writer)

    try:
        if parsed["udp"]:
            if parsed["port"] != 53:
                return
            if parsed["protocol"] == "vless":
                sink.prefix = bytes([parsed["version"], 0])
                await _dns_tcp_query(buf[parsed["offset"]:], sink)
                while True:
                    chunk = await body_reader.read(65536)
                    if not chunk:
                        break
                    await _dns_tcp_query(chunk, sink)
            else:
                trojan_udp = {"buf": b""}
                await _trojan_udp_feed(buf[parsed["offset"]:], sink, trojan_udp)
                while True:
                    chunk = await body_reader.read(65536)
                    if not chunk:
                        break
                    await _trojan_udp_feed(chunk, sink, trojan_udp)
            return

        session = _ProxySession(sink)
        if parsed["protocol"] == "vless":
            sink.prefix = bytes([parsed["version"], 0])
        await session.connect(parsed["host"], parsed["port"])
        await session.write_remote(buf[parsed["offset"]:])
        while True:
            chunk = await body_reader.read(65536)
            if not chunk:
                break
            await session.write_remote(chunk)
        await session.end_upload()
    except Exception:
        pass
    finally:
        await sink.close()


def _xhttp_referer_padding(req):
    """从 Referer 的 x_padding 提取 padding 值（sing-box-extended/Karing packet-up 风格）。"""
    referer = req.header("referer") or ""
    if referer:
        try:
            parsed = urllib.parse.urlsplit(referer if "://" in referer else "https://x.invalid/" + referer.lstrip("/"))
            vals = urllib.parse.parse_qs(parsed.query).get("x_padding")
            if vals:
                return vals[0]
        except ValueError:
            pass
    return ""


# ---------- XHTTP packet-up（分包模式）支持 ----------
XHTTP_PACKET_SESSIONS = {}
XHTTP_PACKET_TTL = 60


class _PacketUpSink:
    """packet-up 下载流 sink：远端数据先入队，GET 下载连接建立后写入 chunked 响应。"""

    def __init__(self):
        self.writer = None
        self.queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._closed = False
        self.done = asyncio.Event()

    async def send(self, data):
        if not data or self._closed:
            return
        if self.writer is not None:
            async with self._lock:
                try:
                    self.writer.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
                    await self.writer.drain()
                except Exception:
                    pass
        else:
            self.queue.put_nowait(data)

    async def attach(self, writer):
        self.writer = writer
        if self._closed:
            try:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
            return
        while True:
            try:
                data = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            async with self._lock:
                try:
                    writer.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
                    await writer.drain()
                except Exception:
                    break

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self.writer is not None:
            try:
                self.writer.write(b"0\r\n\r\n")
                await self.writer.drain()
            except Exception:
                pass
        self.done.set()


class _XHttpPacketSession:
    """packet-up 会话：按 seq 重组上传包，解析 VLESS 首包并建立代理连接，
    远端下行数据通过 _PacketUpSink 推送给 GET 下载流。"""

    def __init__(self, session_id):
        self.session_id = session_id
        self.packets = {}
        self.next_seq = 0
        self.upload_queue = asyncio.Queue()
        self.sink = _PacketUpSink()
        self.session = None
        self.udp_mode = None
        self.trojan_udp = {"buf": b""}
        self.established = False
        self.buf = b""
        self.parsed = None
        self.last_active = time.time()
        self.closed = False
        self.task = None

    def feed_packet(self, seq, data):
        self.last_active = time.time()
        if not data:
            return
        if seq == self.next_seq:
            self.upload_queue.put_nowait(data)
            self.next_seq += 1
            while self.next_seq in self.packets:
                self.upload_queue.put_nowait(self.packets.pop(self.next_seq))
                self.next_seq += 1
        elif seq > self.next_seq:
            self.packets[seq] = data
            if len(self.packets) > 256:
                oldest = min(self.packets)
                del self.packets[oldest]

    def end_upload(self):
        if not self.closed:
            self.upload_queue.put_nowait(None)

    async def _run(self):
        try:
            while True:
                data = await self.upload_queue.get()
                if data is None:
                    break
                if not self.established:
                    self.buf += data
                    if self.parsed is None:
                        self.parsed, state = parse_edt_header(self.buf)
                        if state == "invalid":
                            break
                        if state == "need_more":
                            if len(self.buf) > 64 * 1024:
                                break
                            continue
                    if self.parsed["udp"]:
                        if self.parsed["port"] != 53:
                            break
                        if self.parsed["protocol"] == "vless":
                            self.udp_mode = "vless"
                            await self.sink.send(bytes([self.parsed["version"], 0]))
                            await _dns_tcp_query(self.buf[self.parsed["offset"]:], self.sink)
                        else:
                            self.udp_mode = "trojan"
                            await _trojan_udp_feed(self.buf[self.parsed["offset"]:], self.sink, self.trojan_udp)
                        self.established = True
                        continue
                    self.session = _ProxySession(self.sink)
                    if self.parsed["protocol"] == "vless":
                        await self.sink.send(bytes([self.parsed["version"], 0]))
                    await self.session.connect(self.parsed["host"], self.parsed["port"])
                    await self.session.write_remote(self.buf[self.parsed["offset"]:])
                    self.established = True
                    continue
                if self.udp_mode == "vless":
                    await _dns_tcp_query(data, self.sink)
                elif self.udp_mode == "trojan":
                    await _trojan_udp_feed(data, self.sink, self.trojan_udp)
                elif self.session is not None:
                    await self.session.write_remote(data)
        except Exception:
            pass
        finally:
            self.closed = True
            if self.session is not None:
                try:
                    await self.session.close()
                except Exception:
                    pass
            await self.sink.close()
            XHTTP_PACKET_SESSIONS.pop(self.session_id, None)


def _get_packet_session(session_id):
    s = XHTTP_PACKET_SESSIONS.get(session_id)
    if s is None:
        s = _XHttpPacketSession(session_id)
        XHTTP_PACKET_SESSIONS[session_id] = s
    s.last_active = time.time()
    return s


async def _handle_xhttp_packet_upload(req, session_id, seq):
    session = _get_packet_session(session_id)
    padding = _xhttp_padding_value(req, *_xhttp_padding_ident(APP_KEY)) or _xhttp_referer_padding(req)
    if not _xhttp_padding_valid(padding):
        await send_simple(req.writer, 400, "Bad Request", [], b"Bad Request")
        return
    body_reader, err = req.body_reader()
    if err:
        await send_simple(req.writer, 400, "Bad Request", [], b"Bad Request")
        return
    data = b""
    while True:
        chunk = await body_reader.read(65536)
        if not chunk:
            break
        data += chunk
    session.feed_packet(seq, data)
    if session.task is None:
        session.task = asyncio.get_event_loop().create_task(session._run())
    await send_simple(req.writer, 200, "OK", [("Content-Type", "text/plain")], b"")


async def _handle_xhttp_packet_download(req, session_id):
    session = _get_packet_session(session_id)
    header_name, query_key = _xhttp_padding_ident(APP_KEY)
    await _send_stream_head(req.writer, 200, "OK", [
        ("Content-Type", "text/event-stream"),
        ("X-Accel-Buffering", "no"),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
        (header_name, f"https://x.invalid/?{query_key}={_random_xhttp_padding()}"),
    ])
    await session.sink.attach(req.writer)
    try:
        await asyncio.wait_for(session.sink.done.wait(), XHTTP_PACKET_TTL + 30)
    except asyncio.TimeoutError:
        pass


async def _cleanup_packet_sessions():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for sid in list(XHTTP_PACKET_SESSIONS):
            s = XHTTP_PACKET_SESSIONS.get(sid)
            if s is None:
                continue
            if s.closed or (now - s.last_active > XHTTP_PACKET_TTL and s.established):
                s.end_upload()
                XHTTP_PACKET_SESSIONS.pop(sid, None)


async def _handle_xhttp(req):
    header_name, query_key = _xhttp_padding_ident(APP_KEY)
    if not _xhttp_padding_valid(_xhttp_padding_value(req, header_name, query_key)):
        await send_simple(req.writer, 400, "Bad Request", [], b"Bad Request")
        return
    await _handle_xhttp_raw(req, [
        (header_name, f"https://x.invalid/?{query_key}={_random_xhttp_padding()}"),
    ])


async def _handle_grpc_http1(req):
    if _xhttp_standard_request(req):
        await _handle_xhttp_raw(req)
        return
    body_reader, err = req.body_reader()
    if err:
        await send_simple(req.writer, 400, "Bad Request", [], b"Bad Request")
        return
    headers = [
        ("Content-Type", "application/grpc"),
        ("grpc-status", "0"),
        ("X-Accel-Buffering", "no"),
        ("Cache-Control", "no-store"),
    ]
    await _send_stream_head(req.writer, 200, "OK", headers)
    grpc = _GrpcSession(_GrpcChunkedSink(req.writer))
    try:
        while True:
            chunk = await body_reader.read(65536)
            if not chunk:
                break
            await grpc.feed(chunk)
    except Exception:
        pass
    finally:
        await grpc.finish()


if H2_AVAILABLE:
    class _H2RawSink:
        """h2 下发送原始数据（不做 gRPC 帧封装）。"""

        def __init__(self, server, stream_id):
            self.server = server
            self.stream_id = stream_id

        async def send(self, data):
            await self.server.send_data(self.stream_id, data)

        async def close(self):
            pass

    class _H2GrpcSink:
        def __init__(self, server, stream_id):
            self.server = server
            self.stream_id = stream_id

        async def send(self, data):
            await self.server.send_data(self.stream_id, _grpc_frame_encode(data))

        async def close(self):
            pass

    class _H2GrpcStream:
        def __init__(self, server, stream_id):
            self.server = server
            self.stream_id = stream_id
            self._queue = asyncio.Queue()
            self._ended = False
            self._session = None
            self.task = asyncio.get_event_loop().create_task(self._run())

        def feed(self, data):
            if not self._ended:
                self._queue.put_nowait(data)

        def end(self):
            if not self._ended:
                self._ended = True
                self._queue.put_nowait(None)

        def cancel(self):
            self._ended = True
            if self.task:
                self.task.cancel()

        async def _run(self):
            sink = _H2GrpcSink(self.server, self.stream_id)
            self._session = _GrpcSession(sink)
            try:
                await self.server.send_headers(self.stream_id, [
                    (":status", "200"),
                    ("content-type", "application/grpc"),
                    ("x-accel-buffering", "no"),
                    ("cache-control", "no-store"),
                ])
                while True:
                    data = await self._queue.get()
                    if data is None:
                        break
                    await self._session.feed(data)
            except Exception:
                pass
            finally:
                try:
                    await self._session.finish()
                except Exception:
                    pass
                # 标准 gRPC：grpc-status 在 trailers 中（CF 的 gRPC 代理依赖此格式）
                await self.server.send_trailers(self.stream_id, [("grpc-status", "0")])

    class _H2XHTTPStream:
        """处理 h2 下 sing-box/Karing 标准 XHTTP（stream-one）原始流。"""

        def __init__(self, server, stream_id):
            self.server = server
            self.stream_id = stream_id
            self._queue = asyncio.Queue()
            self._ended = False
            self._session = None
            self.task = asyncio.get_event_loop().create_task(self._run())

        def feed(self, data):
            if not self._ended:
                self._queue.put_nowait(data)

        def end(self):
            if not self._ended:
                self._ended = True
                self._queue.put_nowait(None)

        def cancel(self):
            self._ended = True
            if self.task:
                self.task.cancel()

        async def _run(self):
            sink = _H2RawSink(self.server, self.stream_id)
            try:
                padding_header, padding_key = _xhttp_padding_ident(APP_KEY)
                await self.server.send_headers(self.stream_id, [
                    (":status", "200"),
                    ("content-type", "application/octet-stream"),
                    ("x-accel-buffering", "no"),
                    ("cache-control", "no-store"),
                    (padding_header, f"https://x.invalid/?{padding_key}={_random_xhttp_padding()}"),
                ])
                buf = b""
                parsed = None
                established = False
                session = None
                udp_mode = None
                trojan_udp = {"buf": b""}
                while True:
                    data = await self._queue.get()
                    if data is None:
                        break
                    if not established:
                        buf += data
                        if parsed is None:
                            parsed, state = parse_edt_header(buf)
                            if state == "invalid":
                                break
                            if state == "need_more":
                                if len(buf) > 64 * 1024:
                                    break
                                continue
                        else:
                            state = "ok"
                        if parsed["udp"]:
                            if parsed["port"] != 53:
                                break
                            if parsed["protocol"] == "vless":
                                udp_mode = "vless"
                                await sink.send(bytes([parsed["version"], 0]))
                                await _dns_tcp_query(buf[parsed["offset"]:], sink)
                            else:
                                udp_mode = "trojan"
                                await _trojan_udp_feed(buf[parsed["offset"]:], sink, trojan_udp)
                            established = True
                            session = None
                            continue
                        session = _ProxySession(sink)
                        if parsed["protocol"] == "vless":
                            await sink.send(bytes([parsed["version"], 0]))
                        await session.connect(parsed["host"], parsed["port"])
                        await session.write_remote(buf[parsed["offset"]:])
                        established = True
                        continue
                    if udp_mode == "vless":
                        await _dns_tcp_query(data, sink)
                    elif udp_mode == "trojan":
                        await _trojan_udp_feed(data, sink, trojan_udp)
                    elif session is not None:
                        await session.write_remote(data)
                if session is not None:
                    await session.end_upload()
            except Exception:
                pass
            finally:
                try:
                    if session is not None:
                        await session.close()
                except Exception:
                    pass
                await self.server.end_stream(self.stream_id)

    class _H2Server:
        def __init__(self, reader, writer, initial):
            self.reader = reader
            self.writer = writer
            self.initial = initial
            config = H2Configuration(
                client_side=False,
                header_encoding="utf-8",
                validate_inbound_headers=False,
            )
            self.conn = H2Connection(config=config)
            self.streams = {}
            self.window_events = {}

        async def _flush(self):
            data = self.conn.data_to_send()
            if data:
                self.writer.write(data)
                await self.writer.drain()

        async def send_headers(self, stream_id, headers):
            try:
                self.conn.send_headers(stream_id, headers)
                await self._flush()
            except Exception:
                pass

        async def send_data(self, stream_id, data):
            max_frame = getattr(self.conn, "max_outbound_frame_size", 16384)
            while data:
                # 发送方向用远端流控窗口（客户端通告的接收窗口）
                window = self.conn.remote_flow_control_window(stream_id)
                if window <= 0:
                    event = self.window_events.setdefault(stream_id, asyncio.Event())
                    event.clear()
                    conn_event = self.window_events.setdefault(0, asyncio.Event())
                    conn_event.clear()
                    await asyncio.wait_for(asyncio.wait(
                        [event.wait(), conn_event.wait()],
                        return_when=asyncio.FIRST_COMPLETED,
                    ), 60)
                    continue
                chunk = data[:min(window, max_frame, len(data))]
                try:
                    self.conn.send_data(stream_id, chunk)
                except FlowControlError:
                    # 连接级窗口不足（python-h2 无连接窗口查询 API），等待 WINDOW_UPDATE
                    conn_event = self.window_events.setdefault(0, asyncio.Event())
                    conn_event.clear()
                    await asyncio.wait_for(conn_event.wait(), 60)
                    continue
                await self._flush()
                data = data[len(chunk):]

        async def end_stream(self, stream_id):
            try:
                self.conn.end_stream(stream_id)
                await self._flush()
            except Exception:
                pass

        async def send_trailers(self, stream_id, headers):
            """发送 gRPC trailers（标准 gRPC 的 grpc-status 放在 trailers 而非响应头）。"""
            try:
                self.conn.send_headers(stream_id, headers, end_stream=True)
                await self._flush()
            except Exception:
                try:
                    self.conn.end_stream(stream_id)
                    await self._flush()
                except Exception:
                    pass

        async def _handle_event(self, event):
            if isinstance(event, RequestReceived):
                headers = {}
                for name, value in event.headers:
                    headers.setdefault(name, value)
                method = headers.get(":method", "")
                content_type = (headers.get("content-type") or "").lower()
                if method == "POST" and content_type.startswith("application/grpc"):
                    referer = headers.get("referer") or ""
                    query = headers.get(":path") or ""
                    # 与 edgetunnel 对齐：XHTTP 特征包括自定义 padding 头 / query key /
                    # Referer 的 x_padding（sing-box 无 extra 时）三类。
                    padding_header, padding_key = _xhttp_padding_ident(APP_KEY)
                    is_standard_xhttp = bool(
                        headers.get(padding_header)
                        or f"{padding_key}=" in query
                        or "x_padding" in referer
                        or "x_padding=" in query
                    )
                    if is_standard_xhttp:
                        self.streams[event.stream_id] = _H2XHTTPStream(self, event.stream_id)
                    else:
                        self.streams[event.stream_id] = _H2GrpcStream(self, event.stream_id)
                else:
                    await self.send_headers(event.stream_id, [
                        (":status", "404"),
                        ("content-type", "text/plain"),
                    ])
                    await self.end_stream(event.stream_id)
            elif isinstance(event, DataReceived):
                stream = self.streams.get(event.stream_id)
                if stream is not None:
                    stream.feed(event.data)
                try:
                    self.conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                except Exception:
                    pass
            elif isinstance(event, StreamEnded):
                stream = self.streams.get(event.stream_id)
                if stream is not None:
                    stream.end()
            elif isinstance(event, StreamReset):
                stream = self.streams.pop(event.stream_id, None)
                if stream is not None:
                    stream.cancel()
            elif isinstance(event, PingReceived):
                try:
                    self.conn.ping_ack(event.ping_data)
                except Exception:
                    pass
            elif isinstance(event, WindowUpdated):
                event_obj = self.window_events.get(event.stream_id)
                if event_obj is not None:
                    event_obj.set()
                conn_event = self.window_events.get(0)
                if conn_event is not None:
                    conn_event.set()
            elif isinstance(event, ConnectionTerminated):
                raise ConnectionError("h2 connection terminated")

        async def run(self):
            self.conn.initiate_connection()
            await self._flush()
            buf = bytearray(self.initial)
            try:
                while True:
                    chunk = await self.reader.read(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    try:
                        events = self.conn.receive_data(bytes(buf))
                    except Exception:
                        break
                    buf.clear()
                    for event in events:
                        try:
                            await self._handle_event(event)
                        except ConnectionError:
                            return
                        except Exception:
                            pass
                    await self._flush()
            finally:
                for stream in list(self.streams.values()):
                    stream.cancel()
                try:
                    self.conn.close_connection()
                    await self._flush()
                except Exception:
                    pass


async def _handle_h2_connection(reader, writer, initial):
    if not H2_AVAILABLE:
        return
    await _H2Server(reader, writer, initial).run()


async def route_request(req):
    upgrade = (req.header("upgrade") or "").lower()
    if upgrade == "websocket":
        await _handle_ws(req)
        return
    if req.path == "/" and req.method == "GET":
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            content = "Hello world!"
        await send_simple(req.writer, 200, "OK",
                          [("Content-Type", "text/html; charset=utf-8")], content.encode("utf-8"))
        return
    if req.path == "/" + SETTINGS_PATH:
        await _handle_advices(req)
        return
    if req.path == "/" + SUBLINK_PATH:
        await _handle_feed(req)
        return
    # XHTTP packet-up（分包模式）：POST /API_PATH/<session>/<seq> 上传、GET /API_PATH/<session> 下载
    path_parts = req.path.strip("/").split("/")
    if path_parts and path_parts[0] == API_PATH and len(path_parts) >= 2:
        session_id = path_parts[1]
        if req.method == "POST" and len(path_parts) >= 3 and path_parts[2].isdigit():
            await _handle_xhttp_packet_upload(req, session_id, int(path_parts[2]))
            return
        if req.method == "GET" and len(path_parts) == 2:
            await _handle_xhttp_packet_download(req, session_id)
            return
    if req.method == "POST":
        content_type = (req.header("content-type") or "").lower()
        header_name, query_key = _xhttp_padding_ident(APP_KEY)
        # 与 edgetunnel 对齐：先识别 XHTTP padding 特征（自定义头/query），再分流 gRPC。
        # Xray/Karing 在 xPaddingObfsMode=true 时把 padding 放在自定义头里且不带 Referer，
        # 若先按 content-type 判 gRPC，会把 XHTTP 原始流误当 gRPC 帧解析。
        if req.header(header_name) or query_key in req.query:
            await _handle_xhttp(req)
            return
        if req.header("x-grpc-proxy") or content_type.startswith("application/grpc"):
            await _handle_grpc_http1(req)
            return
        await _handle_xhttp(req)
        return
    await send_simple(req.writer, 404, "Not Found",
                      [("Content-Type", "text/plain")], b"Not Found\n")


def _set_tcp_nodelay(writer):
    """关闭 Nagle 算法，避免小块数据（chunked/WS 帧）被延迟聚合导致吞吐骤降。"""
    try:
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass


async def handle_connection(reader, writer):
    try:
        _set_tcp_nodelay(writer)
        first = await asyncio.wait_for(reader.read(24), HEADER_TIMEOUT)
        if not first:
            return
        if len(first) == len(H2_PREFACE) and first == H2_PREFACE:
            await _handle_h2_connection(reader, writer, first)
            return
        req = await read_request(reader, writer, first)
        if req is not None:
            await route_request(req)
    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _get_download_url():
    arch = os.uname().machine if hasattr(os, "uname") else ""
    if "arm" in arch or "aarch64" in arch:
        return "https://arm64.ssss.nyc.mn/agent" if MONITOR_PORT else "https://arm64.ssss.nyc.mn/v1"
    return "https://amd64.ssss.nyc.mn/agent" if MONITOR_PORT else "https://amd64.ssss.nyc.mn/v1"


async def download_monitor():
    if not MONITOR_HOST and not MONITOR_KEY:
        return
    try:
        def _dl():
            url = _get_download_url()
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp, open("monitor", "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        await asyncio.to_thread(_dl)
        print("monitor download successfully")
        subprocess.run(["chmod", "+x", "monitor"], shell=False, check=False)
    except Exception as err:
        raise err


async def run_monitor():
    try:
        if not MONITOR_HOST and not MONITOR_KEY:
            return
        try:
            status = subprocess.run(
                'ps aux | grep -v "grep" | grep "./[m]onitor"',
                shell=True, capture_output=True, text=True, timeout=10,
            )
            if status.stdout.strip():
                print("monitor is already running, skip running...")
                return
        except Exception:
            pass

        await download_monitor()
        tls_ports = ["443", "8443", "2096", "2087", "2083", "2053"]
        command = ""
        if MONITOR_HOST and MONITOR_PORT and MONITOR_KEY:
            tls_flag = "--tls" if MONITOR_PORT in tls_ports else ""
            command = (f"setsid nohup ./monitor -s {MONITOR_HOST}:{MONITOR_PORT} -p {MONITOR_KEY} {tls_flag} "
                       "--disable-auto-update --report-delay 4 --skip-conn --skip-procs >/dev/null 2>&1 &")
        elif MONITOR_HOST and MONITOR_KEY:
            if not MONITOR_PORT:
                port = MONITOR_HOST.rsplit(":", 1)[-1] if ":" in MONITOR_HOST else ""
                use_tls = "true" if port in tls_ports else "false"
                config_yaml = (
                    f"client_secret: {MONITOR_KEY}\n"
                    "debug: false\n"
                    "disable_auto_update: true\n"
                    "disable_command_execute: false\n"
                    "disable_force_update: true\n"
                    "disable_nat: false\n"
                    "disable_send_query: false\n"
                    "gpu: false\n"
                    "insecure_tls: true\n"
                    "ip_report_period: 1800\n"
                    "report_delay: 4\n"
                    f"server: {MONITOR_HOST}\n"
                    "skip_connection_count: true\n"
                    "skip_procs_count: true\n"
                    "temperature: false\n"
                    f"tls: {use_tls}\n"
                    "use_gitee_to_upgrade: false\n"
                    "use_ipv6_country_code: false\n"
                    f"uuid: {APP_KEY}\n"
                )
                with open("config.yaml", "w", encoding="utf-8") as f:
                    f.write(config_yaml)
            command = "setsid nohup ./monitor -c config.yaml >/dev/null 2>&1 &"
        else:
            return
        try:
            subprocess.run(command, shell=True, timeout=10, check=False)
            print("monitor is running")
        except Exception as err:
            print("monitor running error:", err)
    except Exception as error:
        print(f"error: {error}")


async def add_ping_task():
    if AUTO_PING not in ("1", "true", "yes", "on"):
        return
    access_domain = GATEWAY_DOMAIN or DIRECT_DOMAIN
    if not access_domain:
        return
    full_url = f"https://{access_domain}/{SUBLINK_PATH}"
    try:
        def _post():
            data = json.dumps({"url": full_url}).encode()
            req = urllib.request.Request("https://oooo.serv00.net/add-url", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        await asyncio.to_thread(_post)
        print("Automatic Access Task added successfully")
    except Exception:
        pass


async def _auto_update_once():
    """按配置的间隔，重新抓取所有节点来源链接并覆盖旧节点。"""
    cfg = get_advices_config()
    auto_update = cfg.get("autoUpdate") or {}
    if not auto_update.get("enabled"):
        return
    sources = auto_update.get("sources") or {}
    if not sources:
        return
    try:
        interval = max(1, int(auto_update.get("intervalMinutes") or 720)) * 60
    except (TypeError, ValueError):
        interval = 720 * 60
    now = time.time()
    changed = False
    for url, src in list(sources.items()):
        try:
            last = float(src.get("lastUpdated") or 0)
        except (TypeError, ValueError):
            last = 0
        if now - last < interval:
            continue
        try:
            addrs, _skipped = await asyncio.to_thread(fetch_url_addresses, url)
        except Exception as exc:
            print(f"[auto-update] 抓取失败 {url}: {exc}", flush=True)
            continue
        if not addrs:
            print(f"[auto-update] {url} 未获取到节点，跳过本次更新", flush=True)
            continue
        old_nodes = set(src.get("nodes") or [])
        addresses = cfg.get("addresses") or []
        filtered = [a for a in addresses if a not in old_nodes]
        seen = set(filtered)
        for a in addrs:
            if a not in seen:
                filtered.append(a)
                seen.add(a)
        sources[url] = {"nodes": addrs, "lastUpdated": now}
        cfg["addresses"] = filtered
        changed = True
        print(f"[auto-update] {url} 更新完成：{len(old_nodes)} -> {len(addrs)} 个节点", flush=True)
    if changed:
        try:
            await asyncio.to_thread(persist_advices_config, cfg)
        except Exception as exc:
            print(f"[auto-update] 保存失败: {exc}", flush=True)


async def auto_update_loop():
    while True:
        try:
            await _auto_update_once()
        except Exception as exc:
            print(f"[auto-update] 循环异常: {exc}", flush=True)
        await asyncio.sleep(60)


def del_files():
    for name in ("monitor", "config.yaml"):
        try:
            os.unlink(name)
        except OSError:
            pass


async def main():
    server = await asyncio.start_server(handle_connection, "0.0.0.0", PORT)
    if PREFERRED_IP and (not GATEWAY_DOMAIN or GATEWAY_DOMAIN == "your-domain.com"):
        print("PREFERRED_IP is ignored because GATEWAY_DOMAIN is empty")
    asyncio.get_event_loop().create_task(run_monitor())
    asyncio.get_event_loop().call_later(180, del_files)
    asyncio.get_event_loop().create_task(add_ping_task())
    asyncio.get_event_loop().create_task(auto_update_loop())
    asyncio.get_event_loop().create_task(_cleanup_packet_sessions())
    print(f"Server is running on port {PORT}")
    async with server:
        await server.serve_forever()


def run():

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
