"""工学云滑块验证码处理模块。

提供验证码获取、自动破解、人工验证等功能。
"""
import base64
import io
import json
import logging
import time
from typing import Optional

import requests

from crypto import aes_encrypt, aes_decrypt, make_t

logger = logging.getLogger(__name__)

API_BASE = 'https://api.moguding.net:9000/'
ORIG_IMG_W = 310   # AJ-Captcha 固定的原始图宽度
ORIG_IMG_H = 155   # 固定高度

_HEADERS = {
    'Content-Type': 'application/json; charset=UTF-8',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
}


class CaptchaSession:
    """一次验证码会话的数据。"""

    def __init__(self, data: dict, client_uid: str = ''):
        self.secret_key: str = data['secretKey']
        self.token: str = data['token']
        self.orig_b64: str = data['originalImageBase64']
        self.jig_b64: str = data['jigsawImageBase64']
        self.client_uid: str = client_uid   # 获取验证码时用的 clientUid，登录 uuid 字段使用
        self._orig_img = None
        self._jig_img = None

    @property
    def orig_img(self):
        if self._orig_img is None:
            from PIL import Image
            self._orig_img = Image.open(io.BytesIO(base64.b64decode(self.orig_b64))).convert('RGBA')
        return self._orig_img

    @property
    def jig_img(self):
        if self._jig_img is None:
            from PIL import Image
            self._jig_img = Image.open(io.BytesIO(base64.b64decode(self.jig_b64))).convert('RGBA')
        return self._jig_img


def fetch_captcha(session: Optional[requests.Session] = None) -> CaptchaSession:
    """从服务器获取新验证码。"""
    import uuid
    client_uid = 'slider-' + str(uuid.uuid4())
    s = session or requests
    resp = s.post(
        API_BASE + 'session/captcha/v1/get',
        json={
            'captchaType': 'blockPuzzle',
            'clientUid': client_uid,
            'ts': int(time.time() * 1000),
        },
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('data'):
        raise RuntimeError(f'验证码获取失败: {data.get("msg", data)}')
    return CaptchaSession(data['data'], client_uid=client_uid)


def encrypt_point(x: float, secret_key: str) -> str:
    """与前端 JS 完全相同的加密格式：{"x":float,"y":5}，AES-128-ECB，Base64输出。"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    point_str = json.dumps({'x': x, 'y': 5}, separators=(',', ':'))
    key = secret_key.encode('utf-8')
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(point_str.encode('utf-8'), 16))
    return base64.b64encode(encrypted).decode()


def compute_verification(token: str, x: float, secret_key: str) -> str:
    """计算登录所需的 captchaVerification（JS 前端逻辑复现）。

    JS原始逻辑：
        captchaVerification = AES_ECB(secretKey, token + '---' + JSON.stringify({x,y:5}))
    """
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    point_str = json.dumps({'x': x, 'y': 5}, separators=(',', ':'))
    plain = f"{token}---{point_str}"
    key = secret_key.encode('utf-8')
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(plain.encode('utf-8'), 16))
    return base64.b64encode(encrypted).decode()


def submit_check(cap: CaptchaSession, x: float,
                 session: Optional[requests.Session] = None) -> Optional[str]:
    """提交验证位置，成功返回 captchaVerification，失败返回 None。"""
    s = session or requests
    point_enc = encrypt_point(x, cap.secret_key)
    try:
        resp = s.post(
            API_BASE + 'session/captcha/v1/check',
            json={
                'captchaType': 'blockPuzzle',
                'token': cap.token,
                'pointJson': point_enc,
                't': make_t(),
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 200:
            return compute_verification(cap.token, x, cap.secret_key)
        logger.debug('验证码 check 失败: code=%s msg=%s x=%s', result.get('code'), result.get('msg'), x)
    except Exception as e:
        logger.debug('验证码 check 异常: %s', e)
    return None


def find_hole_x(cap: CaptchaSession) -> int:
    """图像分析找到缺口的 x 坐标（原始图坐标 0-263）。"""
    try:
        import numpy as np
        orig = cap.orig_img
        jig = cap.jig_img
        orig_arr = np.array(orig)
        jig_arr = np.array(jig)

        # 拼图块有效像素蒙版
        jig_alpha = jig_arr[:, :, 3] > 0
        if not jig_alpha.any():
            logger.warning('拼图蒙版为空，跳过自动识别')
            return -1

        jig_rgb = jig_arr[:, :, :3].astype(float)
        orig_rgb = orig_arr[:, :, :3].astype(float)
        orig_gray = np.mean(orig_rgb, axis=2)
        jig_h, jig_w = jig_arr.shape[:2]

        # 方法：RGB颜色差最小处 = 拼图与背景最相似 = 缺口位置
        best_x, best_score = 0, float('inf')
        for x in range(0, orig.width - jig_w + 1):
            bg = orig_rgb[:jig_h, x:x + jig_w]
            diff = float(np.mean(np.abs(bg[jig_alpha] - jig_rgb[jig_alpha])))
            if diff < best_score:
                best_score = diff
                best_x = x

        logger.debug('图像分析找到缺口: x=%d, score=%.1f', best_x, best_score)
        return best_x
    except Exception as e:
        logger.warning('图像分析失败: %s', e)
        return -1


def auto_solve(cap: CaptchaSession,
               session: Optional[requests.Session] = None) -> Optional[str]:
    """尝试自动破解验证码，返回 captchaVerification 或 None。"""
    hole_x = find_hole_x(cap)
    if hole_x < 0:
        return None

    logger.info('尝试自动验证码，候选 x=%d', hole_x)
    verif = submit_check(cap, float(hole_x), session)
    if verif:
        logger.info('验证码自动破解成功，x=%d', hole_x)
        return verif

    logger.info('自动破解失败，需要手动验证')
    return None


def login_with_captcha(phone: str, password: str, captcha_verif: str,
                       client_uid: str = '',
                       session: Optional[requests.Session] = None) -> dict:
    """使用手机号+密码+验证码登录，返回 API 响应。

    client_uid: 获取验证码时使用的 clientUid（CaptchaSession.client_uid），作为 uuid 字段传入。
    """
    s = session or requests
    resp = s.post(
        API_BASE + 'session/user/v6/login',
        json={
            't': make_t(),                      # AES 加密时间戳，必填
            'phone': aes_encrypt(phone),
            'password': aes_encrypt(password),
            'loginType': 'web',
            'uuid': client_uid,
            'captcha': captcha_verif,
        },
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()
    if raw.get('code') == 200 and isinstance(raw.get('data'), str):
        try:
            raw['data'] = json.loads(aes_decrypt(raw['data']))
        except Exception:
            pass
    return raw
