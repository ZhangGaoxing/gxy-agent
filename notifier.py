"""通知推送模块。

支持三种渠道：
- PushPlus（推荐，微信推送）
- 邮件（SMTP）
- Server酱（微信推送）
"""
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """统一通知推送器。"""

    def __init__(self, cfg: dict):
        self._cfg = cfg.get('notification', {})

    def send(self, title: str, content: str) -> None:
        """向所有已启用的渠道发送通知。"""
        sent = False

        pp_cfg = self._cfg.get('pushplus', {})
        if pp_cfg.get('enabled') and pp_cfg.get('token'):
            try:
                self._send_pushplus(pp_cfg['token'], title, content)
                sent = True
            except Exception as e:
                logger.error('PushPlus 推送失败: %s', e)

        email_cfg = self._cfg.get('email', {})
        if email_cfg.get('enabled') and email_cfg.get('sender') and email_cfg.get('password'):
            try:
                self._send_email(email_cfg, title, content)
                sent = True
            except Exception as e:
                logger.error('邮件推送失败: %s', e)

        sc_cfg = self._cfg.get('serverchan', {})
        if sc_cfg.get('enabled') and sc_cfg.get('sendkey'):
            try:
                self._send_serverchan(sc_cfg['sendkey'], title, content)
                sent = True
            except Exception as e:
                logger.error('Server酱推送失败: %s', e)

        if not sent:
            logger.info('未配置通知渠道，跳过推送。通知内容已输出到控制台。')
            sep = '=' * 50
            out = f'\n{sep}\n[通知] {title}\n{sep}\n{content}\n{sep}\n'
            try:
                import sys
                sys.stdout.buffer.write(out.encode('utf-8', errors='replace'))
                sys.stdout.buffer.flush()
            except Exception:
                pass

    # ──────────────── PushPlus ────────────────

    @staticmethod
    def _send_pushplus(token: str, title: str, content: str) -> None:
        payload = {
            'token': token,
            'title': title,
            'content': content,
            'template': 'txt',
        }
        resp = requests.post(
            'http://www.pushplus.plus/send',
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') != 200:
            raise RuntimeError(f'PushPlus 返回错误: {result}')
        logger.info('PushPlus 推送成功')

    # ──────────────── 邮件 ────────────────

    @staticmethod
    def _send_email(cfg: dict, title: str, content: str) -> None:
        msg = MIMEText(content, 'plain', 'utf-8')
        msg['Subject'] = Header(title, 'utf-8')
        msg['From'] = cfg['sender']
        msg['To'] = cfg['recipient']

        if cfg.get('use_ssl', True):
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg['smtp_server'], cfg['smtp_port'], context=context) as server:
                server.login(cfg['sender'], cfg['password'])
                server.sendmail(cfg['sender'], [cfg['recipient']], msg.as_string())
        else:
            with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as server:
                server.starttls()
                server.login(cfg['sender'], cfg['password'])
                server.sendmail(cfg['sender'], [cfg['recipient']], msg.as_string())
        logger.info('邮件推送成功 → %s', cfg['recipient'])

    # ──────────────── Server酱 ────────────────

    @staticmethod
    def _send_serverchan(sendkey: str, title: str, content: str) -> None:
        resp = requests.post(
            f'https://sctapi.ftqq.com/{sendkey}.send',
            data={'title': title, 'desp': content},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') not in (0, 200):
            raise RuntimeError(f'Server酱返回错误: {result}')
        logger.info('Server酱推送成功')
