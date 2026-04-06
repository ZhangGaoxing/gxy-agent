"""工学云指导教师 API 客户端。

封装日报/周报/月报批阅、补签审批、未提交学生查询等接口。
"""
import logging
from datetime import datetime
from typing import Any

import requests

from crypto import aes_encrypt, make_t

BASE_URL = 'https://api.moguding.net:9000/'
logger = logging.getLogger(__name__)


def _extract_list(data_field: Any) -> list:
    """从 API 响应的 data 字段中提取列表（兼容多种分页格式）。"""
    if isinstance(data_field, list):
        return data_field
    if isinstance(data_field, dict):
        for key in ('rows', 'list', 'records', 'data'):
            if key in data_field and isinstance(data_field[key], list):
                return data_field[key]
    return []


class GxyAPI:
    """工学云教师端 API 客户端。"""

    def __init__(self, cfg: dict):
        self._creds = cfg['credentials']
        self._token: str = self._creds.get('token', '')
        self._user_id: str = str(self._creds.get('user_id', ''))
        self._role_key: str = self._creds.get('role_key', 'adviser')
        self._batch_id: str = self._creds.get('batch_id', '')
        self._teacher_id: str = self._creds.get('teacher_id', '')
        self._session = requests.Session()
        self._session.headers['Content-Type'] = 'application/json; charset=UTF-8'
        self._session.headers['User-Agent'] = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )

    # ──────────────── 内部工具 ────────────────

    def _auth_headers(self) -> dict:
        return {
            'authorization': self._token,
            'userid': self._user_id,
            'rolekey': self._role_key,
        }

    def _post(self, path: str, body: dict) -> dict:
        """发送 POST 请求，自动注入 t 参数，token 过期时自动重登。"""
        body = dict(body)
        body['t'] = make_t()
        url = BASE_URL + path

        resp = self._session.post(url, json=body, headers=self._auth_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get('code') == 401:
            logger.info('Token 已过期，尝试重新登录...')
            self.login()
            body['t'] = make_t()
            resp = self._session.post(url, json=body, headers=self._auth_headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()

        if data.get('code') not in (200, None):
            logger.warning('API %s 非 200 响应: code=%s msg=%s', path, data.get('code'), data.get('msg'))

        return data

    # ──────────────── 登录 ────────────────

    def login(self) -> None:
        """使用手机号+密码登录，自动更新 token / userId。"""
        phone = self._creds.get('phone', '')
        password = self._creds.get('password', '')
        if not phone or not password:
            raise ValueError(
                'Token 已失效且未配置手机号/密码，无法自动重新登录。\n'
                '请在 config.yaml 填写 credentials.password，或从浏览器重新复制 token。'
            )
        body = {
            'phone': phone,
            'password': aes_encrypt(password),
            'loginType': 'phone',
            'uuid': '',
            'picCode': '',
        }
        resp = self._session.post(BASE_URL + 'session/user/v6/login', json=body, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') != 200:
            raise RuntimeError(f'登录失败: {result.get("msg", result)}')
        self._token = result['data']['token']
        self._user_id = str(result['data']['userId'])
        self._creds['token'] = self._token
        self._creds['user_id'] = self._user_id
        logger.info('登录成功，token 已更新。')

    # ──────────────── 报告相关 ────────────────

    def get_pending_reports(self, report_type: str) -> list:
        """获取待批阅报告列表。

        report_type: 'day' | 'week' | 'month'
        返回去重后的报告列表，每项包含 reportId、studentName 等字段。
        """
        today = datetime.now().strftime('%Y-%m-%d')
        all_reports: list = []
        page = 1
        while True:
            body = {
                'currPage': page,
                'pageSize': 200,
                'batchId': self._batch_id,
                'reportType': report_type,
                'teaId': self._teacher_id,
                'state': '',           # 查全部，后续客户端过滤未批阅
                'reportTime': today if report_type == 'day' else '',
                'classId': '',
                'planId': '',
                'semester': '',
                'studentNumber': '',
            }
            data = self._post('practice/paper/v1/list', body)
            items = _extract_list(data.get('data'))
            if not items:
                break
            all_reports.extend(items)
            if len(items) < 200:
                break
            page += 1

        # 过滤出未批阅的（state 为 0 或 None）
        pending = [r for r in all_reports if r.get('state') not in (1, '1', 2, '2')]
        logger.info('%-5s 报告：共 %d 份，其中待批阅 %d 份', report_type, len(all_reports), len(pending))
        return pending

    def review_report(self, report_id: str, comment: str = '', star_num: int = 0) -> dict:
        """批阅（审核通过）一份报告。

        star_num: 0=不评星，1~5=对应星级。
        注：practice/paper/v1/comment 仅写评论不改变状态；
            practice/paper/v1/audit  才是真正的审核通过接口。
        """
        body = {
            'reportId': report_id,
            'state': 1,             # 1 = 审核通过
            'comment': comment,
            'starNum': int(star_num) if star_num and 1 <= int(star_num) <= 5 else 0,
        }
        return self._post('practice/paper/v1/audit', body)

    # ──────────────── 补签申请相关 ────────────────

    def get_pending_replacements(self) -> list:
        """获取待审批的补签申请列表。"""
        all_items: list = []
        page = 1
        while True:
            body = {
                'currPage': page,
                'pageSize': 200,
                'batchId': self._batch_id,
                'state': 'APPLYINT',   # 待审批状态
                'username': '',
                'studentNumber': '',
                'startTime': '',
                'endTime': '',
            }
            data = self._post('attendence/attendanceReplace/v1/list', body)
            items = _extract_list(data.get('data'))
            if not items:
                break
            all_items.extend(items)
            if len(items) < 200:
                break
            page += 1
        logger.info('待审批补签：%d 份', len(all_items))
        return all_items

    def approve_replacements(self, attendance_ids: list, comment: str = '') -> dict:
        """批量审批通过补签申请。"""
        body = {
            'attendenceIds': attendance_ids,
            'comment': comment if comment else None,
            'applyState': 1,    # 1 = 通过
        }
        return self._post('attendence/attendanceReplace/v1/audit', body)

    # ──────────────── 未提交学生查询 ────────────────

    def get_no_submit_students(self, report_type: str) -> list:
        """获取未提交指定类型报告的学生列表（已去重）。

        report_type: 'day' | 'week' | 'month'
        每项含 username, studentNumber, className, depName 等字段。
        """
        today_dt = datetime.now()
        today = today_dt.strftime('%Y-%m-%d 00:00:00')
        yearmonth = today_dt.strftime('%Y-%m')

        all_students: list = []
        seen: set = set()
        page = 1
        while True:
            body = {
                'currPage': page,
                'pageSize': 200,
                'batchId': self._batch_id,
                'reportType': report_type,
                'reportTime': today if report_type == 'day' else '',
                'yearmonth': yearmonth if report_type == 'month' else '',
                'teaId': self._teacher_id,
                'username': '',
                'studentNumber': '',
                'classId': '',
                'depId': '',
                'majorId': '',
                'planId': '',
                'practiceState': '',
                'semester': '',
                'startTime': '',
                'endTime': '',
            }
            data = self._post('practice/paper/v1/listNoWrite', body)
            items = _extract_list(data.get('data'))
            if not items:
                break
            for s in items:
                key = s.get('studentNumber') or s.get('studentId') or s.get('username')
                if key and key not in seen:
                    seen.add(key)
                    all_students.append(s)
            if len(items) < 200:
                break
            page += 1

        logger.info('未提交%5s：%d 人', report_type, len(all_students))
        return all_students

    def get_sign_in_warnings(self) -> list:
        """获取签到预警列表（含 studentName, className, warnDesc 等字段）。"""
        all_warns: list = []
        page = 1
        while True:
            body = {
                'currPage': page,
                'pageSize': 200,
                'state': '',
                'batchId': self._batch_id,
            }
            data = self._post('practice/warn/v2/list', body)
            items = _extract_list(data.get('data'))
            if not items:
                break
            all_warns.extend(items)
            if len(items) < 200:
                break
            page += 1
        logger.info('签到预警：%d 条', len(all_warns))
        return all_warns

    def get_today_stats(self) -> dict:
        """获取今日统计数据（未签到人数、未提周报人数等）。"""
        data = self._post('statistics/practice/v1/myStuData', {'batchId': self._batch_id})
        return data.get('data') or {}

    def get_report_detail(self, report_id: str) -> dict:
        """获取单份报告的详细内容（含正文 content 字段）。"""
        data = self._post('practice/paper/v1/detail', {'reportId': report_id})
        return data.get('data') or {}

    # ──────────────── 账号自动发现 ────────────────

    @staticmethod
    def discover_credentials(token: str, user_id: str, role_key: str = 'adviser') -> dict:
        """根据 token 自动获取 batch_id，返回完整凭据字典供写入 config。

        用法：
            info = GxyAPI.discover_credentials(token, user_id, role_key)
            cfg['credentials'] = info
        """
        import requests as _req
        hdrs = {
            'Content-Type': 'application/json; charset=UTF-8',
            'authorization': token,
            'userid': str(user_id),
            'rolekey': role_key,
        }
        body = {'t': make_t(), 'currPage': 1, 'pageSize': 20}
        resp = _req.post(BASE_URL + 'practice/batch/v1/list', json=body, headers=hdrs, timeout=15)
        resp.raise_for_status()
        batches = resp.json().get('data') or []
        batch_id = ''
        school_id = ''
        # 优先取 isCurrentBacth==1 的批次
        for b in batches:
            if b.get('isCurrentBacth') == 1:
                batch_id = b.get('batchId', '')
                school_id = b.get('schoolId', '')
                break
        if not batch_id and batches:
            batch_id = batches[0].get('batchId', '')
            school_id = batches[0].get('schoolId', '')
        return {
            'user_id': str(user_id),
            'role_key': role_key,
            'token': token,
            'batch_id': batch_id,
            'school_id': school_id,
        }
