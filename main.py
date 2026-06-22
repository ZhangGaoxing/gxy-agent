"""工学云指导教师自动批阅工具 - 主程序。

用法：
  python main.py           # 启动定时任务（按 config.yaml 的 schedule.run_at 每日运行）
  python main.py --now     # 立即执行一次
  python main.py --check   # 仅查询并打印待处理信息，不实际提交
"""
import argparse
import logging
import random
import sys
from datetime import datetime
from typing import Optional

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from api import GxyAPI
from notifier import Notifier

# ──────────────── 日志配置 ────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('gxy_agent.log', encoding='utf-8'),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────── 核心任务 ────────────────

def run_job(cfg: dict, dry_run: bool = False) -> None:
    """每日自动批阅主流程。"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    logger.info('====== 工学云自动批阅开始 [%s] ======', today_str)

    api = GxyAPI(cfg)
    notifier = Notifier(cfg)

    review_cfg = cfg.get('review', {})
    report_cfg = review_cfg.get('reports', {})
    replace_cfg = review_cfg.get('replacement', {})

    stats = {
        'reviewed_day': 0,
        'reviewed_week': 0,
        'reviewed_month': 0,
        'commented_day': 0,
        'commented_week': 0,
        'commented_month': 0,
        'approved_replace': 0,
        'reviewed_summary': 0,
        'commented_summary': 0,
        'scored_assessment': 0,
        'errors': [],
    }

    # ── 1. 批阅日报/周报/月报 ──
    type_cn = {'day': '日报', 'week': '周报', 'month': '月报'}
    if report_cfg:
        for rtype in ('day', 'week', 'month'):
            # 兼容新格式（per-type dict）和旧格式（flat dict with types list）
            if isinstance(report_cfg.get(rtype), dict):
                type_cfg = report_cfg[rtype]
            else:
                old_enabled = report_cfg.get('enabled', True)
                old_types = report_cfg.get('types', ['day', 'week', 'month'])
                type_cfg = {
                    'enabled': old_enabled and rtype in old_types,
                    'comment': report_cfg.get('comment', ''),
                    'star_num': 0,
                }

            if not type_cfg.get('enabled', True):
                logger.info('%s：已禁用，跳过', type_cn.get(rtype, rtype))
                continue

            type_comment = type_cfg.get('comment', '')
            type_star = int(type_cfg.get('star_num', 0) or 0)

            try:
                pending = api.get_pending_reports(rtype)
                if not pending:
                    logger.info('%s：无待批阅报告', type_cn.get(rtype, rtype))
                    continue

                logger.info('%s：待批阅 %d 份%s', type_cn.get(rtype, rtype), len(pending),
                            '（dry-run，跳过提交）' if dry_run else '')

                if not dry_run:
                    ok = 0
                    for report in pending:
                        rid = report.get('reportId') or report.get('id')
                        if not rid:
                            logger.warning('报告缺少 reportId，跳过: %s', report)
                            continue
                        try:
                            api.review_report(str(rid), type_comment, star_num=type_star)
                            ok += 1
                        except Exception as e:
                            logger.warning('批阅报告 %s 失败: %s', rid, e)
                            stats['errors'].append(f'批阅{type_cn.get(rtype)}({rid})失败: {e}')
                    stats[f'reviewed_{rtype}'] = ok
                    logger.info('%s：批阅完成 %d/%d 份', type_cn.get(rtype, rtype), ok, len(pending))

            except Exception as e:
                logger.error('获取%s报告失败: %s', type_cn.get(rtype, rtype), e)
                stats['errors'].append(f'获取{type_cn.get(rtype)}失败: {e}')

    # ── 2. 审批补签申请 ──
    if replace_cfg.get('enabled', True):
        try:
            replacements = api.get_pending_replacements()
            if not replacements:
                logger.info('补签申请：无待审批记录')
            else:
                logger.info('补签申请：待审批 %d 份%s', len(replacements),
                            '（dry-run，跳过提交）' if dry_run else '')
                if not dry_run:
                    ids = [str(r.get('attendanceId') or r.get('id') or r.get('attendenceId') or '')
                           for r in replacements if r.get('attendanceId') or r.get('id') or r.get('attendenceId')]
                    if ids:
                        replace_comment = replace_cfg.get('comment', '')
                        result = api.approve_replacements(ids, replace_comment)
                        if result.get('code') == 200:
                            stats['approved_replace'] = len(ids)
                            logger.info('补签申请：审批通过 %d 份', len(ids))
                        else:
                            logger.warning('补签审批返回异常: %s', result)
        except Exception as e:
            logger.error('处理补签申请失败: %s', e)
            stats['errors'].append(f'处理补签申请失败: {e}')

    # ── 3. 批阅总结报告 ──
    summary_cfg = report_cfg.get('summary', {})
    if summary_cfg.get('enabled', False):
        try:
            pending_sum = api.get_pending_reports('summary')
            if not pending_sum:
                logger.info('总结报告：无待批阅')
            else:
                logger.info('总结报告：待批阅 %d 份%s', len(pending_sum),
                            '（dry-run，跳过提交）' if dry_run else '')
                if not dry_run:
                    ok = 0
                    min_s = int(summary_cfg.get('min_score', 60) or 60)
                    max_s = int(summary_cfg.get('max_score', 100) or 100)
                    sum_comment = summary_cfg.get('comment', '')
                    for report in pending_sum:
                        rid = report.get('reportId') or report.get('id')
                        if not rid:
                            continue
                        try:
                            score = random.randint(min_s, max_s)
                            api.review_summary_report(str(rid), score, sum_comment)
                            ok += 1
                        except Exception as e:
                            logger.warning('批阅总结报告 %s 失败: %s', rid, e)
                            stats['errors'].append(f'批阅总结报告({rid})失败: {e}')
                    stats['reviewed_summary'] = ok
                    logger.info('总结报告：批阅完成 %d/%d 份', ok, len(pending_sum))
        except Exception as e:
            logger.error('处理总结报告失败: %s', e)
            stats['errors'].append(f'处理总结报告失败: {e}')

    # ── 4. 为已批阅报告补充教师评语 ──
    supplement_cfg = review_cfg.get('supplement_comment', {})
    comment_choices = [
        line.strip() for line in str(supplement_cfg.get('comment_text', '')).splitlines()
        if line.strip()
    ]
    if supplement_cfg.get('enabled', False):
        if not comment_choices:
            logger.warning('补充批阅评语模式已启用，但评语文本为空，已跳过')
        else:
            for rtype in ('day', 'week', 'month', 'summary'):
                try:
                    reports = api.get_reviewed_reports_without_comment(rtype)
                    if not reports:
                        logger.info('%s：无待补充评语的已批阅报告', type_cn.get(rtype, '总结报告'))
                        continue

                    logger.info('%s：待补充评语 %d 份%s',
                                type_cn.get(rtype, '总结报告'), len(reports),
                                '（dry-run，跳过提交）' if dry_run else '')
                    if dry_run:
                        continue

                    ok = 0
                    for report in reports:
                        rid = report.get('reportId') or report.get('id')
                        if not rid:
                            logger.warning('报告缺少 reportId，跳过补充评语: %s', report)
                            continue
                        try:
                            comments_before = api.get_report_comments(str(rid))
                            if comments_before:
                                continue
                            comment = random.choice(comment_choices)
                            result = api.add_report_comment(
                                str(rid), comment, rtype, report
                            )
                            if result.get('code') not in (200, None):
                                raise RuntimeError(result.get('msg', str(result)))
                            comments_after = api.get_report_comments(str(rid))
                            if not comments_after:
                                raise RuntimeError('接口返回成功，但回读评论列表仍为空')
                            ok += 1
                        except Exception as e:
                            logger.warning('补充报告评语 %s 失败: %s', rid, e)
                            stats['errors'].append(
                                f'补充{type_cn.get(rtype, "总结报告")}评语({rid})失败: {e}'
                            )
                    stats[f'commented_{rtype}'] = ok
                    logger.info('%s：补充评语完成 %d/%d 份',
                                type_cn.get(rtype, '总结报告'), ok, len(reports))
                except Exception as e:
                    logger.error('获取%s补充评语列表失败: %s', type_cn.get(rtype, '总结报告'), e)
                    stats['errors'].append(
                        f'获取{type_cn.get(rtype, "总结报告")}补充评语列表失败: {e}'
                    )

    # ── 5. 实习成绩考核打分 ──
    assessment_cfg = review_cfg.get('assessment', {})
    if assessment_cfg.get('enabled', False):
        try:
            pending_assess = api.get_pending_assessments()
            if not pending_assess:
                logger.info('实习成绩考核：无待打分')
            else:
                logger.info('实习成绩考核：待打分 %d 份%s', len(pending_assess),
                            '（dry-run，跳过提交）' if dry_run else '')
                if not dry_run:
                    ok = 0
                    min_s = int(assessment_cfg.get('min_score', 60) or 60)
                    max_s = int(assessment_cfg.get('max_score', 100) or 100)
                    assess_comment = assessment_cfg.get('comment', '')
                    for item in pending_assess:
                        sid = item.get('studentId', '')
                        pid = item.get('planId', '')
                        if not sid or not pid:
                            continue
                        try:
                            score = random.randint(min_s, max_s)
                            api.score_assessment(sid, pid, score, assess_comment)
                            ok += 1
                        except Exception as e:
                            logger.warning('实习成绩考核打分 %s 失败: %s', sid, e)
                            stats['errors'].append(f'实习成绩考核({sid})失败: {e}')
                    stats['scored_assessment'] = ok
                    logger.info('实习成绩考核：打分完成 %d/%d 份', ok, len(pending_assess))
        except Exception as e:
            logger.error('处理实习成绩考核失败: %s', e)
            stats['errors'].append(f'处理实习成绩考核失败: {e}')

    # ── 5. 查询未提交/未签到学生 ──
    no_submit: dict = {}
    warns: list = []
    today_stat: dict = {}

    try:
        for rtype in ['day', 'week', 'month']:
            no_submit[rtype] = api.get_no_submit_students(rtype)
    except Exception as e:
        logger.error('查询未提交学生失败: %s', e)

    try:
        warns = api.get_sign_in_warnings()
    except Exception as e:
        logger.error('查询签到预警失败: %s', e)

    try:
        today_stat = api.get_today_stats()
    except Exception as e:
        logger.error('查询今日统计失败: %s', e)

    # ── 6. 构建通知内容 ──
    title = f'【工学云】{today_str} 自动批阅完成'
    # ─────────────────────────────────────────
    # 构建通知内容（表格化、结构化）
    # ─────────────────────────────────────────
    SEP = '━' * 32
    acct_name = cfg.get('credentials', {}).get('name', '') or cfg.get('credentials', {}).get('phone', '')

    lines = [
        f'📅 {today_str}　工学云自动批阅报告',
        *([ f'👤 账号：{acct_name}'] if acct_name else []),
        SEP,
    ]

    # ── 批阅汇总表 ──
    if not dry_run:
        lines += [
            '✅ 本次批阅结果',
            f'  {"类型":<4}  {"数量":>4}',
            f'  {"────":<4}  {"────":>4}',
            f'  {"日报":<4}  {stats["reviewed_day"]:>4} 份',
            f'  {"周报":<4}  {stats["reviewed_week"]:>4} 份',
            f'  {"月报":<4}  {stats["reviewed_month"]:>4} 份',
            f'  {"补签":<4}  {stats["approved_replace"]:>4} 份',
            f'  {"总结":<4}  {stats["reviewed_summary"]:>4} 份',
            f'  {"考核":<4}  {stats["scored_assessment"]:>4} 份',
            '💬 补充教师评语',
            f'  {"日报":<4}  {stats["commented_day"]:>4} 份',
            f'  {"周报":<4}  {stats["commented_week"]:>4} 份',
            f'  {"月报":<4}  {stats["commented_month"]:>4} 份',
            f'  {"总结":<4}  {stats["commented_summary"]:>4} 份',
        ]
    else:
        lines += ['ℹ️  查询模式（dry-run），未实际提交批阅']

    # ── 今日总体统计 ──
    if today_stat:
        total = today_stat.get('studentNum', today_stat.get('bindNum', '?'))
        no_atten = today_stat.get('noAttenNum', '?')
        no_week = today_stat.get('noWeekReportNum', '?')
        lines += [
            SEP,
            f'📊 今日数据  （管理学生：{total} 人）',
            f'  · 未签到：{no_atten} 人',
            f'  · 未提本周周报：{no_week} 人',
        ]

    # ── 未提交报告学生（按班级分组）──
    for rtype, students in no_submit.items():
        lines.append(SEP)
        if not students:
            lines.append(f'✅ {type_cn[rtype]}：全员已提交')
            continue
        lines.append(f'❌ 未提交{type_cn[rtype]}（{len(students)} 人）')
        # 按班级分组
        groups: dict = {}
        for s in students:
            cls = s.get('className') or '未知班级'
            groups.setdefault(cls, []).append(s)
        for cls, sts in sorted(groups.items()):
            names_str = '、'.join(
                s.get('username') or s.get('studentName') or '?'
                for s in sts
            )
            lines.append(f'  [{cls}（{len(sts)}人）] {names_str}')

    # ── 签到预警 ──
    lines.append(SEP)
    if warns:
        lines.append(f'⚠️  签到预警（{len(warns)} 条）')
        # 按班级分组
        warn_groups: dict = {}
        for w in warns:
            cls = w.get('className') or '未知班级'
            warn_groups.setdefault(cls, []).append(w)
        for cls, ws in sorted(warn_groups.items()):
            lines.append(f'  [{cls}（{len(ws)}条）]')
            for w in ws[:5]:
                name = w.get('studentName') or '未知'
                desc = w.get('warnDesc') or ''
                lines.append(f'    · {name}  {desc}')
            if len(ws) > 5:
                lines.append(f'    ... 还有 {len(ws) - 5} 条')
    else:
        lines.append('✅ 无签到预警')

    # ── 错误信息 ──
    if stats['errors']:
        lines += [
            SEP,
            f'🚨 执行错误（{len(stats["errors"])} 个）',
        ]
        for err in stats['errors']:
            lines.append(f'  · {err}')

    lines.append(SEP)
    content = '\n'.join(lines)
    logger.info('\n%s', content)

    notifier.send(title, content)
    logger.info('====== 工学云自动批阅结束 ======')


# ──────────────── 入口 ────────────────

def load_config(path: str = 'config.yaml') -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description='工学云指导教师自动批阅工具')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--now', action='store_true', help='立即执行一次（批阅 + 通知）')
    group.add_argument('--check', action='store_true', help='仅查询，不实际提交（dry-run）')
    args = parser.parse_args()

    cfg = load_config()

    if args.now:
        run_job(cfg, dry_run=False)
        return

    if args.check:
        run_job(cfg, dry_run=True)
        return

    # ── 启动定时任务 ──
    schedule_cfg = cfg.get('schedule', {})
    run_at: str = schedule_cfg.get('run_at', '08:30')
    hour, minute = run_at.split(':')

    scheduler = BlockingScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(
        run_job,
        trigger=CronTrigger(hour=int(hour), minute=int(minute)),
        args=[cfg],
        id='daily_review',
        name='工学云每日自动批阅',
        replace_existing=True,
    )

    if schedule_cfg.get('run_on_start', False):
        logger.info('run_on_start=true，立即执行一次...')
        run_job(cfg)

    logger.info('定时任务已启动，每日 %s 自动执行（按 Ctrl+C 退出）', run_at)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info('已停止。')


if __name__ == '__main__':
    main()
