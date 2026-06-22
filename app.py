"""工学云指导教师自动批阅工具 - GUI 界面

运行：python app.py
"""
import logging
import queue
import sys
import threading
from pathlib import Path

import yaml

try:
    import tkinter as tk
    import customtkinter as ctk
    from tkinter import messagebox
except ImportError:
    print("请先安装 customtkinter：pip install customtkinter")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# PyInstaller 打包后 sys.executable 指向 exe 目录，开发时使用脚本目录
_IS_FROZEN = getattr(sys, "frozen", False)
_APP_DIR = Path(sys.executable).parent if _IS_FROZEN else Path(__file__).parent

VERSION = "1.2.0"
CONFIG_PATH = _APP_DIR / "config.yaml"

STAR_OPTIONS = [
    "不评分",
    "★☆☆☆☆  1星",
    "★★☆☆☆  2星",
    "★★★☆☆  3星",
    "★★★★☆  4星",
    "★★★★★  5星",
]
STAR_MAP = {opt: i for i, opt in enumerate(STAR_OPTIONS)}
STAR_REV = {i: opt for i, opt in enumerate(STAR_OPTIONS)}

TEST_TYPES = ["日报", "周报", "月报", "补签申请", "总结报告", "实习成绩考核"]
TEST_TYPE_MAP = {"日报": "day", "周报": "week", "月报": "month", "补签申请": "replace", "总结报告": "summary", "实习成绩考核": "assessment"}


# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_CONFIG = """
accounts:
  - name: "请填写姓名"
    phone: ""
    password: ""
    token: ""
    user_id: ""
    role_key: adviser
    batch_id: ""
    plan_id: ""
    teacher_id: ""
    school_id: ""
active_account: 0
schedule:
  run_at: "08:30"
  run_on_start: false
review:
  reports:
    day:
      enabled: false
      comment: ""
      star_num: 5
    week:
      enabled: false
      comment: ""
      star_num: 5
    month:
      enabled: false
      comment: ""
      star_num: 5
    summary:
      enabled: false
      min_score: 60
      max_score: 100
      comment: ""
  replacement:
    enabled: false
    comment: ""
  supplement_comment:
    enabled: false
    comment_text: ""
  assessment:
    enabled: false
    min_score: 60
    max_score: 100
    comment: ""
notification:
  pushplus:
    enabled: false
    token: ""
  email:
    enabled: false
    sender: ""
    password: ""
    recipient: ""
  serverchan:
    enabled: false
    sendkey: ""
"""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(_DEFAULT_CONFIG.lstrip(), encoding="utf-8")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # ── 迁移：若无 accounts 列表，从 credentials 构建 ──
    if not cfg.get("accounts"):
        creds = cfg.get("credentials", {})
        name = creds.get("name") or creds.get("phone") or "账号1"
        cfg["accounts"] = [{**creds, "name": name}]
        cfg["active_account"] = 0
    # 确保 credentials 始终指向当前激活账号
    idx = int(cfg.get("active_account", 0) or 0)
    idx = max(0, min(idx, len(cfg["accounts"]) - 1))
    cfg["credentials"] = cfg["accounts"][idx]
    cfg["active_account"] = idx
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ─────────────────────────────────────────────────────────────────────────────


class UILogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


# ─────────────────────────────────────────────────────────────────────────────


class CaptchaDialog(ctk.CTkToplevel):
    """仅显示拼图验证码的独立对话框，验证通过后回调 on_verified(verif, client_uid)。"""

    IMG_W = 310
    IMG_H = 155

    def __init__(self, parent, cap, on_verified):
        super().__init__(parent)
        self.title("拼图验证")
        self.resizable(False, False)
        self.grab_set()
        self._cap = cap
        self._on_verified = on_verified
        self._bg_photo = None
        self._jig_photo = None
        self._jig_canvas_id = None
        self._build_ui()
        self.after(100, self._center)
        self.after(150, lambda: self._render(cap))

    def _center(self):
        self.update_idletasks()
        px = self.master.winfo_x() + (self.master.winfo_width() - self.winfo_width()) // 2
        py = self.master.winfo_y() + (self.master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

    def _build_ui(self):
        main = ctk.CTkFrame(self, fg_color='transparent')
        main.pack(fill='both', expand=True, padx=14, pady=12)

        hdr = ctk.CTkFrame(main, fg_color='transparent')
        hdr.pack(fill='x', pady=(0, 6))
        ctk.CTkLabel(hdr, text='🧩  拖动滑块使拼图对准缺口',
                     font=ctk.CTkFont(size=13, weight='bold')).pack(side='left')
        ctk.CTkButton(hdr, text='🔄 换一张', width=80, height=26,
                      command=self._refresh).pack(side='right')

        self._canvas = tk.Canvas(main, width=self.IMG_W, height=self.IMG_H,
                                 bg='#2b2b2b', highlightthickness=0)
        self._canvas.pack(pady=(0, 6))

        self._slider_var = tk.IntVar(value=0)
        tk.Scale(
            main, variable=self._slider_var,
            from_=0, to=263, orient=tk.HORIZONTAL, length=self.IMG_W,
            showvalue=True, bg='#2b2b2b', fg='#aaaaaa',
            troughcolor='#404040', activebackground='#1a6090',
            highlightthickness=0, command=self._on_slider,
        ).pack(fill='x', pady=(0, 8))

        btn_row = ctk.CTkFrame(main, fg_color='transparent')
        btn_row.pack(fill='x')
        self._verify_btn = ctk.CTkButton(
            btn_row, text='✅  确认验证', width=130, height=34,
            fg_color='#2d6a2d', hover_color='#235023',
            command=self._do_verify,
        )
        self._verify_btn.pack(side='right')
        self._status_lbl = ctk.CTkLabel(btn_row, text='', text_color='gray')
        self._status_lbl.pack(side='left')

    def _render(self, cap):
        try:
            from PIL import ImageTk, Image
            orig = cap.orig_img.convert('RGB').resize((self.IMG_W, self.IMG_H), Image.LANCZOS)
            self._bg_photo = ImageTk.PhotoImage(orig)
            self._canvas.delete('all')
            self._canvas.create_image(0, 0, anchor='nw', image=self._bg_photo)
            self._jig_pil = cap.jig_img.convert('RGBA')
            self._jig_photo = ImageTk.PhotoImage(self._jig_pil)
            self._jig_canvas_id = self._canvas.create_image(
                self._slider_var.get(), 0, anchor='nw', image=self._jig_photo)
        except Exception as e:
            logging.warning('渲染验证码失败: %s', e)

    def _on_slider(self, val):
        if self._jig_canvas_id is not None:
            self._canvas.coords(self._jig_canvas_id, int(val), 0)

    def _refresh(self):
        self._verify_btn.configure(state='disabled')
        self._status_lbl.configure(text='正在获取新验证码...', text_color='#f0a500')

        def work():
            try:
                from captcha import fetch_captcha
                cap = fetch_captcha()
                self._cap = cap
                self.after(0, lambda: (
                    self._slider_var.set(0),
                    self._render(cap),
                    self._verify_btn.configure(state='normal'),
                    self._status_lbl.configure(text='', text_color='gray'),
                ))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    self._status_lbl.configure(text=f'刷新失败: {e}', text_color='#f44336'),
                    self._verify_btn.configure(state='normal'),
                ))

        threading.Thread(target=work, daemon=True).start()

    def _do_verify(self):
        cap = self._cap
        if not cap:
            return
        x = float(self._slider_var.get())
        self._verify_btn.configure(state='disabled')
        self._status_lbl.configure(text='正在验证...', text_color='#f0a500')

        def work():
            try:
                from captcha import submit_check
                verif = submit_check(cap, x)
                if verif:
                    cb, uid = self._on_verified, cap.client_uid
                    self.after(0, lambda: (cb(verif, uid), self.destroy()))
                else:
                    self.after(0, lambda: (
                        self._status_lbl.configure(text='❌ 位置不对，请重新拖动', text_color='#f44336'),
                        self._verify_btn.configure(state='normal'),
                    ))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    self._status_lbl.configure(text=f'验证失败: {e}', text_color='#f44336'),
                    self._verify_btn.configure(state='normal'),
                ))

        threading.Thread(target=work, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────


class TestRow:
    """手动批阅列表中的单行 UI 组件。"""

    STATUS_PENDING = ("●", "gray")
    STATUS_BUSY    = ("◉", "#f0a500")
    STATUS_OK      = ("✓", "#4caf50")
    STATUS_ERR     = ("✗", "#f44336")

    def __init__(self, parent, item: dict, item_type: str):
        self.item = item
        self.item_type = item_type  # 'day'/'week'/'month'/'replace'
        self.frame = ctk.CTkFrame(parent, fg_color=("gray90", "gray17"), corner_radius=6)
        self.frame.pack(fill="x", padx=6, pady=3)

        is_replace = item_type == "replace"

        # 状态指示
        self._status_label = ctk.CTkLabel(self.frame, text="●", text_color="gray", width=20)
        self._status_label.grid(row=0, column=0, padx=(10, 4), pady=8)

        # 学生姓名 + 班级
        name = item.get("username") or item.get("studentName") or "未知"
        cls_ = item.get("className") or ""
        self._name_label = ctk.CTkLabel(
            self.frame, text=f"{name}  {cls_}", width=160, anchor="w",
            font=ctk.CTkFont(size=13), cursor="hand2",
        )
        self._name_label.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="w")

        # 日期 / 类型描述
        if is_replace:
            date_str = (item.get("attendenceTime") or item.get("dateTime") or "")[:10]
            desc = f"补签  {date_str}"
        elif item_type == "assessment":
            semester = (item.get("semester") or item.get("planName") or "")[:14]
            desc = f"考核  {semester}"
        else:
            type_cn = {"day": "日报", "week": "周报", "month": "月报", "summary": "总结"}.get(item_type, "")
            report_time = (
                item.get("reportTime") or item.get("startTime") or item.get("createTime") or ""
            )[:10]
            desc = f"{type_cn}  {report_time}"
        self._desc_label = ctk.CTkLabel(
            self.frame, text=desc, width=140, anchor="w",
            text_color=("gray40", "gray70"), cursor="hand2",
        )
        self._desc_label.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="w")

        if not is_replace:
            is_score_type = item_type in ("summary", "assessment")
            if is_score_type:
                # 数值分数输入
                self._score_var = ctk.StringVar()
                ctk.CTkEntry(
                    self.frame, textvariable=self._score_var,
                    placeholder_text="分数（0-100）", width=130,
                ).grid(row=0, column=3, padx=(0, 8), pady=8)
                self._star_var = None
            else:
                # 星级选择
                self._score_var = None
                self._star_var = ctk.StringVar(value=STAR_REV.get(5, STAR_OPTIONS[5]))
                ctk.CTkOptionMenu(
                    self.frame, variable=self._star_var, values=STAR_OPTIONS,
                    width=148, dynamic_resizing=False,
                ).grid(row=0, column=3, padx=(0, 8), pady=8)

            # 评语
            self._comment_var = ctk.StringVar()
            ctk.CTkEntry(
                self.frame, textvariable=self._comment_var,
                placeholder_text="批阅评语（可选）",
            ).grid(row=0, column=4, padx=(0, 8), pady=8, sticky="ew")
            self.frame.columnconfigure(4, weight=1)
            btn_col = 5
        else:
            self._star_var = None
            self._score_var = None
            self._comment_var = None
            self.frame.columnconfigure(3, weight=1)
            btn_col = 4

        # 操作按钮
        btn_text = "审  批" if is_replace else ("打  分" if item_type == "assessment" else "批  阅")
        self._btn = ctk.CTkButton(
            self.frame, text=btn_text, width=76, height=30,
            fg_color="#1a5f7a", hover_color="#144d63",
        )
        self._btn.grid(row=0, column=btn_col, padx=(0, 10), pady=8)

    def bind_action(self, callback) -> None:
        self._btn.configure(command=callback)

    def bind_detail(self, callback) -> None:
        """点击姓名/日期区域触发详情弹窗。"""
        for w in (self._name_label, self._desc_label):
            w.bind("<Button-1>", lambda e, cb=callback: cb())

    def set_status(self, status: tuple) -> None:
        icon, color = status
        self._status_label.configure(text=icon, text_color=color)

    def set_busy(self, busy: bool) -> None:
        self._btn.configure(state="disabled" if busy else "normal")
        if busy:
            self.set_status(self.STATUS_BUSY)

    def get_star_num(self) -> int:
        if self._star_var is None:
            return 0
        return STAR_MAP.get(self._star_var.get(), 0)

    def get_score(self) -> int:
        """获取数值分数（0-100），未填写或无效返回 -1。"""
        if self._score_var is None:
            return -1
        try:
            v = int(self._score_var.get())
            return max(0, min(100, v))
        except (ValueError, TypeError):
            return -1

    def get_comment(self) -> str:
        if self._comment_var is None:
            return ""
        return self._comment_var.get()

    def mark_done(self) -> None:
        self.set_status(self.STATUS_OK)
        self._btn.configure(state="disabled", text="✓ 已完成", fg_color="#2d6a2d")

    def mark_error(self, msg: str = "") -> None:
        self.set_status(self.STATUS_ERR)
        self._btn.configure(state="normal")
        logging.error("操作失败: %s", msg)

    def is_done(self) -> bool:
        return self._btn.cget("text") == "✓ 已完成"


# ─────────────────────────────────────────────────────────────────────────────


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("工学云自动批阅工具")
        self.geometry("1080x860")
        self.minsize(920, 720)

        self.cfg = load_config()
        self.log_queue: queue.Queue = queue.Queue()
        self._scheduler = None
        self._job_thread: threading.Thread | None = None

        self._setup_logging()
        self._build_header()
        self._build_tabs()
        self._build_actions()
        self._build_log_area()
        self._poll_log_queue()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Logging ──────────────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.handlers.clear()
        root.addHandler(UILogHandler(self.log_queue))
        fh = logging.FileHandler(str(_APP_DIR / "gxy_agent.log"), encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        root.addHandler(fh)

    # ── Header ───────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=("gray82", "gray20"))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr,
            text="  🎓  工学云指导教师自动批阅工具",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(
            hdr, text=f"v{VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray60"),
        ).pack(side="right", padx=16)

    # ── Tab View ─────────────────────────────────────────────────────────────

    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(self, height=400)
        self.tabview.pack(fill="x", padx=14, pady=(10, 0))

        for name in ("📝  批阅设置", "⏰  定时设置", "🔔  通知设置", "👤  账号设置", "🧪  手动批阅", "ℹ️  关于"):
            self.tabview.add(name)

        self._build_review_tab()
        self._build_schedule_tab()
        self._build_notify_tab()
        self._build_account_tab()
        self._build_test_tab()
        self._build_about_tab()

    # ── Tab: 批阅设置 ──────────────────────────────────────────────────────────

    def _build_review_tab(self) -> None:
        tab = self.tabview.tab("📝  批阅设置")
        tab.columnconfigure(0, weight=1)

        review_cfg = self.cfg.get("review", {})
        reports_cfg = review_cfg.get("reports", {})
        self._review_vars: dict = {}

        for row_idx, (rtype, cn) in enumerate(
            [("day", "日报"), ("week", "周报"), ("month", "月报")]
        ):
            sec: dict = (
                reports_cfg[rtype]
                if isinstance(reports_cfg.get(rtype), dict)
                else reports_cfg
            )
            frame = ctk.CTkFrame(tab)
            frame.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=4)
            frame.columnconfigure(4, weight=1)

            enabled_var = ctk.BooleanVar(value=bool(sec.get("enabled", True)))
            star_num = sec.get("star_num", 5) if isinstance(sec.get("star_num"), int) else 5
            star_var = ctk.StringVar(value=STAR_REV.get(star_num, STAR_OPTIONS[5]))
            comment_var = ctk.StringVar(value=str(sec.get("comment", "") or ""))

            ctk.CTkCheckBox(
                frame, text=f"批阅{cn}", variable=enabled_var, width=88,
                command=lambda rt=rtype: self._toggle_review_row(rt),
            ).grid(row=0, column=0, padx=(14, 6), pady=12, sticky="w")

            ctk.CTkLabel(frame, text="批阅星级：").grid(row=0, column=1, padx=(6, 2), pady=12)
            star_menu = ctk.CTkOptionMenu(
                frame, variable=star_var, values=STAR_OPTIONS,
                width=166, dynamic_resizing=False,
            )
            star_menu.grid(row=0, column=2, padx=(0, 10), pady=12)

            ctk.CTkLabel(frame, text="批阅评语：").grid(row=0, column=3, padx=(6, 2), pady=12)
            comment_entry = ctk.CTkEntry(
                frame, textvariable=comment_var,
                placeholder_text="留空则仅点击通过，不写评语",
            )
            comment_entry.grid(row=0, column=4, padx=(0, 14), pady=12, sticky="ew")

            self._review_vars[rtype] = {
                "enabled": enabled_var, "star": star_var, "comment": comment_var,
                "star_menu": star_menu, "comment_entry": comment_entry,
            }

        # 补签申请
        replace_sec = review_cfg.get("replacement", {})
        rep_frame = ctk.CTkFrame(tab)
        rep_frame.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        rep_frame.columnconfigure(3, weight=1)

        rep_enabled = ctk.BooleanVar(value=bool(replace_sec.get("enabled", True)))
        rep_comment_var = ctk.StringVar(value=str(replace_sec.get("comment", "") or ""))

        ctk.CTkCheckBox(rep_frame, text="审批补签申请", variable=rep_enabled, width=120).grid(
            row=0, column=0, padx=(14, 6), pady=12, sticky="w"
        )
        ctk.CTkLabel(rep_frame, text="（自动全部通过）", text_color="gray").grid(
            row=0, column=1, padx=(0, 12), pady=12
        )
        ctk.CTkLabel(rep_frame, text="审批备注：").grid(row=0, column=2, padx=(6, 2), pady=12)
        ctk.CTkEntry(
            rep_frame, textvariable=rep_comment_var,
            placeholder_text="留空则不填写备注",
        ).grid(row=0, column=3, padx=(0, 14), pady=12, sticky="ew")

        self._review_vars["replacement"] = {
            "enabled": rep_enabled, "comment": rep_comment_var,
        }

        # 总结报告打分
        summary_sec = (reports_cfg.get("summary") or {}) if isinstance(reports_cfg, dict) else {}
        sum_frame = ctk.CTkFrame(tab)
        sum_frame.grid(row=4, column=0, sticky="ew", padx=4, pady=4)
        sum_frame.columnconfigure(6, weight=1)

        sum_enabled = ctk.BooleanVar(value=bool(summary_sec.get("enabled", False)))
        sum_min = ctk.StringVar(value=str(summary_sec.get("min_score", 60)))
        sum_max = ctk.StringVar(value=str(summary_sec.get("max_score", 100)))
        sum_comment_var = ctk.StringVar(value=str(summary_sec.get("comment", "") or ""))

        ctk.CTkCheckBox(
            sum_frame, text="批阅总结报告", variable=sum_enabled, width=110,
        ).grid(row=0, column=0, padx=(14, 6), pady=12, sticky="w")
        ctk.CTkLabel(sum_frame, text="分数范围：").grid(row=0, column=1, padx=(6, 2), pady=12)
        ctk.CTkEntry(sum_frame, textvariable=sum_min, width=60).grid(
            row=0, column=2, padx=(0, 4), pady=12)
        ctk.CTkLabel(sum_frame, text="~").grid(row=0, column=3, padx=4, pady=12)
        ctk.CTkEntry(sum_frame, textvariable=sum_max, width=60).grid(
            row=0, column=4, padx=(0, 10), pady=12)
        ctk.CTkLabel(sum_frame, text="批阅评语：").grid(row=0, column=5, padx=(6, 2), pady=12)
        ctk.CTkEntry(
            sum_frame, textvariable=sum_comment_var,
            placeholder_text="留空则不填写评语",
        ).grid(row=0, column=6, padx=(0, 14), pady=12, sticky="ew")

        self._review_vars["summary"] = {
            "enabled": sum_enabled, "min_score": sum_min,
            "max_score": sum_max, "comment": sum_comment_var,
        }

        # 实习成绩考核打分
        assess_sec = review_cfg.get("assessment", {})
        assess_frame = ctk.CTkFrame(tab)
        assess_frame.grid(row=5, column=0, sticky="ew", padx=4, pady=4)
        assess_frame.columnconfigure(6, weight=1)

        assess_enabled = ctk.BooleanVar(value=bool(assess_sec.get("enabled", False)))
        assess_min = ctk.StringVar(value=str(assess_sec.get("min_score", 60)))
        assess_max = ctk.StringVar(value=str(assess_sec.get("max_score", 100)))
        assess_comment_var = ctk.StringVar(value=str(assess_sec.get("comment", "") or ""))

        ctk.CTkCheckBox(
            assess_frame, text="实习成绩考核", variable=assess_enabled, width=110,
        ).grid(row=0, column=0, padx=(14, 6), pady=12, sticky="w")
        ctk.CTkLabel(assess_frame, text="分数范围：").grid(row=0, column=1, padx=(6, 2), pady=12)
        ctk.CTkEntry(assess_frame, textvariable=assess_min, width=60).grid(
            row=0, column=2, padx=(0, 4), pady=12)
        ctk.CTkLabel(assess_frame, text="~").grid(row=0, column=3, padx=4, pady=12)
        ctk.CTkEntry(assess_frame, textvariable=assess_max, width=60).grid(
            row=0, column=4, padx=(0, 10), pady=12)
        ctk.CTkLabel(assess_frame, text="打分备注：").grid(row=0, column=5, padx=(6, 2), pady=12)
        ctk.CTkEntry(
            assess_frame, textvariable=assess_comment_var,
            placeholder_text="留空则不填写备注",
        ).grid(row=0, column=6, padx=(0, 14), pady=12, sticky="ew")

        self._review_vars["assessment"] = {
            "enabled": assess_enabled, "min_score": assess_min,
            "max_score": assess_max, "comment": assess_comment_var,
        }

        # 已批阅报告补充评语
        supplement_sec = review_cfg.get("supplement_comment", {})
        supplement_frame = ctk.CTkFrame(tab)
        supplement_frame.grid(row=6, column=0, sticky="ew", padx=4, pady=4)
        supplement_frame.columnconfigure(0, weight=1)

        supplement_enabled = ctk.BooleanVar(
            value=bool(supplement_sec.get("enabled", False))
        )
        ctk.CTkCheckBox(
            supplement_frame, text="补充批阅评语", variable=supplement_enabled, width=120,
        ).grid(row=0, column=0, padx=(14, 6), pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            supplement_frame,
            text="自动为已批阅且暂无教师评语的日报、周报、月报、总结补充评语；每行一条，随机选取。",
            text_color="gray",
        ).grid(row=0, column=1, padx=(0, 14), pady=(12, 2), sticky="w")
        supplement_textbox = ctk.CTkTextbox(supplement_frame, height=100, wrap="word")
        supplement_textbox.grid(row=1, column=0, columnspan=2, padx=14, pady=(6, 12), sticky="ew")
        supplement_textbox.insert("1.0", str(supplement_sec.get("comment_text", "") or ""))
        self._review_vars["supplement_comment"] = {
            "enabled": supplement_enabled, "comment_text": supplement_textbox,
        }

        for rtype in ("day", "week", "month"):
            self._toggle_review_row(rtype)

    def _toggle_review_row(self, rtype: str) -> None:
        v = self._review_vars.get(rtype, {})
        if "star_menu" not in v:
            return
        state = "normal" if v["enabled"].get() else "disabled"
        v["star_menu"].configure(state=state)
        v["comment_entry"].configure(state=state)

    # ── Tab: 定时设置 ──────────────────────────────────────────────────────────

    def _build_schedule_tab(self) -> None:
        tab = self.tabview.tab("⏰  定时设置")
        sch = self.cfg.get("schedule", {})

        outer = ctk.CTkFrame(tab)
        outer.pack(fill="x", padx=4, pady=4)

        ctk.CTkLabel(
            outer, text="每日自动执行时间（HH:MM，24小时制）：",
            font=ctk.CTkFont(size=14),
        ).grid(row=0, column=0, padx=15, pady=(16, 8), sticky="w")
        self._run_at_var = ctk.StringVar(value=str(sch.get("run_at", "08:30")))
        ctk.CTkEntry(outer, textvariable=self._run_at_var, width=90).grid(
            row=0, column=1, padx=(8, 15), pady=(16, 8)
        )

        self._run_on_start_var = ctk.BooleanVar(value=bool(sch.get("run_on_start", False)))
        ctk.CTkCheckBox(
            outer, text="程序启动时立即执行一次", variable=self._run_on_start_var,
        ).grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 14), sticky="w")

        ctk.CTkLabel(
            tab,
            text=(
                "💡 提示：\n"
                "  · 点击「启动定时任务」后，程序将在后台等待，每日到达指定时间自动批阅。\n"
                "  · 保持此窗口开启即可，日志实时显示于下方区域。\n"
                "  · 若需在系统后台长期运行，请使用命令行：python main.py"
            ),
            text_color="gray", justify="left", anchor="nw",
        ).pack(fill="x", padx=14, pady=(10, 0), anchor="w")

    # ── Tab: 通知设置 ──────────────────────────────────────────────────────────

    def _build_notify_tab(self) -> None:
        tab = self.tabview.tab("🔔  通知设置")
        notify_cfg = self.cfg.get("notification", {})

        scroll = ctk.CTkScrollableFrame(tab, height=320)
        scroll.pack(fill="both", expand=True, padx=4, pady=4)
        scroll.columnconfigure(1, weight=1)

        self._notify_vars: dict = {}

        # PushPlus
        pp = notify_cfg.get("pushplus", {})
        pp_frame = ctk.CTkFrame(scroll)
        pp_frame.pack(fill="x", pady=(0, 8))
        pp_frame.columnconfigure(1, weight=1)
        pp_enabled = ctk.BooleanVar(value=bool(pp.get("enabled", False)))
        pp_token = ctk.StringVar(value=str(pp.get("token", "") or ""))
        ctk.CTkCheckBox(
            pp_frame, text="PushPlus（微信推送，推荐）", variable=pp_enabled, width=210,
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        ctk.CTkLabel(
            pp_frame, text="注册：https://www.pushplus.plus", text_color="gray",
        ).grid(row=0, column=1, padx=8, pady=(12, 4), sticky="w")
        ctk.CTkLabel(pp_frame, text="Token：", anchor="e").grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="e"
        )
        ctk.CTkEntry(
            pp_frame, textvariable=pp_token,
            placeholder_text="PushPlus Token（在官网个人中心获取）",
        ).grid(row=1, column=1, padx=(0, 12), pady=(0, 12), sticky="ew")
        self._notify_vars["pushplus"] = {"enabled": pp_enabled, "token": pp_token}

        # 邮件
        em = notify_cfg.get("email", {})
        em_frame = ctk.CTkFrame(scroll)
        em_frame.pack(fill="x", pady=(0, 8))
        em_frame.columnconfigure(1, weight=1)
        em_vars = {
            "enabled": ctk.BooleanVar(value=bool(em.get("enabled", False))),
            "smtp_server": ctk.StringVar(value=str(em.get("smtp_server", "smtp.qq.com") or "smtp.qq.com")),
            "smtp_port": ctk.StringVar(value=str(em.get("smtp_port", 465) or 465)),
            "sender": ctk.StringVar(value=str(em.get("sender", "") or "")),
            "password": ctk.StringVar(value=str(em.get("password", "") or "")),
            "recipient": ctk.StringVar(value=str(em.get("recipient", "") or "")),
            "use_ssl": ctk.BooleanVar(value=bool(em.get("use_ssl", True))),
        }
        ctk.CTkCheckBox(
            em_frame, text="邮件通知（SMTP）", variable=em_vars["enabled"], width=160,
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        for i, (lbl, key, is_pass) in enumerate([
            ("SMTP服务器：", "smtp_server", False),
            ("SMTP端口：",   "smtp_port",   False),
            ("发件人邮箱：", "sender",      False),
            ("SMTP授权码：", "password",    True),
            ("收件人邮箱：", "recipient",   False),
        ]):
            ctk.CTkLabel(em_frame, text=lbl, anchor="e").grid(
                row=i + 1, column=0, padx=12, pady=(0, 6), sticky="e"
            )
            ctk.CTkEntry(em_frame, textvariable=em_vars[key], show="*" if is_pass else "").grid(
                row=i + 1, column=1, padx=(0, 12), pady=(0, 6), sticky="ew"
            )
        ctk.CTkCheckBox(em_frame, text="使用 SSL（推荐）", variable=em_vars["use_ssl"]).grid(
            row=6, column=1, padx=(0, 12), pady=(0, 12), sticky="w"
        )
        self._notify_vars["email"] = em_vars

        # Server酱
        sc = notify_cfg.get("serverchan", {})
        sc_frame = ctk.CTkFrame(scroll)
        sc_frame.pack(fill="x", pady=(0, 8))
        sc_frame.columnconfigure(1, weight=1)
        sc_enabled = ctk.BooleanVar(value=bool(sc.get("enabled", False)))
        sc_key = ctk.StringVar(value=str(sc.get("sendkey", "") or ""))
        ctk.CTkCheckBox(
            sc_frame, text="Server酱（微信推送）", variable=sc_enabled, width=180,
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        ctk.CTkLabel(
            sc_frame, text="注册：https://sct.ftqq.com", text_color="gray",
        ).grid(row=0, column=1, padx=8, pady=(12, 4), sticky="w")
        ctk.CTkLabel(sc_frame, text="SendKey：", anchor="e").grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="e"
        )
        ctk.CTkEntry(sc_frame, textvariable=sc_key, placeholder_text="SendKey").grid(
            row=1, column=1, padx=(0, 12), pady=(0, 12), sticky="ew"
        )
        self._notify_vars["serverchan"] = {"enabled": sc_enabled, "sendkey": sc_key}

    # ── Tab: 账号设置（多账号管理）────────────────────────────────────────────

    def _build_account_tab(self) -> None:
        tab = self.tabview.tab("👤  账号设置")

        # ── 账号选择器行 ──
        sel_frame = ctk.CTkFrame(tab, fg_color="transparent")
        sel_frame.pack(fill="x", padx=4, pady=(8, 4))

        ctk.CTkLabel(sel_frame, text="当前账号：", width=80, anchor="e").pack(side="left", padx=(8, 4))
        self._account_names_var: list[str] = self._get_account_display_names()
        active_name = self._account_names_var[self.cfg.get("active_account", 0)]
        self._acct_sel_var = ctk.StringVar(value=active_name)
        self._acct_selector = ctk.CTkOptionMenu(
            sel_frame, variable=self._acct_sel_var,
            values=self._account_names_var, width=220,
            command=self._on_account_switch,
        )
        self._acct_selector.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            sel_frame, text="＋ 新增", width=72, height=30,
            command=self._add_account,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            sel_frame, text="删除", width=68, height=30,
            fg_color="gray35", hover_color="gray25",
            command=self._delete_account,
        ).pack(side="left")

        # ── 字段编辑区 ──
        outer = ctk.CTkFrame(tab)
        outer.pack(fill="x", padx=4, pady=(4, 0))
        outer.columnconfigure(1, weight=1)

        self._cred_vars: dict = {}
        active_creds = self.cfg.get("credentials", {})
        fields = [
            ("账号名称：", "name",     False),
            ("手机号：",   "phone",    False),
            ("登录密码：", "password", True),
        ]
        for i, (lbl, key, is_pass) in enumerate(fields):
            ctk.CTkLabel(outer, text=lbl, anchor="e", width=90).grid(
                row=i, column=0, padx=(14, 6), pady=(14 if i == 0 else 6, 6), sticky="e"
            )
            var = ctk.StringVar(value=str(active_creds.get(key, "") or ""))
            ctk.CTkEntry(outer, textvariable=var, show="*" if is_pass else "").grid(
                row=i, column=1, padx=(0, 14), pady=(14 if i == 0 else 6, 6), sticky="ew"
            )
            self._cred_vars[key] = var

        # ── 登录按钮行 ──
        login_row = ctk.CTkFrame(outer, fg_color='transparent')
        login_row.grid(row=3, column=0, columnspan=2, padx=(14, 14), pady=(4, 12), sticky='ew')
        login_row.columnconfigure(1, weight=1)
        self._acct_login_btn = ctk.CTkButton(
            login_row, text='🚀  登录', width=100, height=32,
            fg_color='#1a6090', hover_color='#145070',
            command=self._do_account_login,
        )
        self._acct_login_btn.grid(row=0, column=0, padx=(0, 10))
        self._login_status_lbl = ctk.CTkLabel(
            login_row, text='', text_color='gray', anchor='w')
        self._login_status_lbl.grid(row=0, column=1, sticky='ew')

        # ── 当前学年（批次）选择行 ──
        batch_frame = ctk.CTkFrame(tab)
        batch_frame.pack(fill="x", padx=4, pady=(8, 0))
        batch_frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(batch_frame, text="当前学年：", anchor="e", width=90).grid(
            row=0, column=0, padx=(14, 6), pady=10, sticky="e")
        self._batch_var = ctk.StringVar(value="")
        self._batch_menu = ctk.CTkOptionMenu(
            batch_frame, variable=self._batch_var,
            values=["（请先登录）"], width=260, state="disabled",
            command=self._on_batch_select,
        )
        self._batch_menu.grid(row=0, column=1, padx=(0, 6), pady=10, sticky="ew")
        ctk.CTkButton(
            batch_frame, text="🔄", width=36, height=32,
            command=self._refresh_batches,
        ).grid(row=0, column=2, padx=(0, 14), pady=10)

        # ── 实习计划选择行 ──
        plan_frame = ctk.CTkFrame(tab)
        plan_frame.pack(fill="x", padx=4, pady=(4, 0))
        plan_frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(plan_frame, text="实习计划：", anchor="e", width=90).grid(
            row=0, column=0, padx=(14, 6), pady=10, sticky="e")
        self._plan_var = ctk.StringVar(value="")
        self._plan_menu = ctk.CTkOptionMenu(
            plan_frame, variable=self._plan_var,
            values=["（请先选择学年）"], width=260, state="disabled",
            command=self._on_plan_select,
        )
        self._plan_menu.grid(row=0, column=1, padx=(0, 6), pady=10, sticky="ew")

        self._batch_status_lbl = ctk.CTkLabel(
            tab, text='', text_color='gray', font=ctk.CTkFont(size=11), anchor='w')
        self._batch_status_lbl.pack(fill='x', padx=20, pady=(0, 4))

        self._batch_list: list[dict] = []
        self._plan_list: list[dict] = []
        # 若已登录，延迟加载批次列表
        if active_creds.get('token') and active_creds.get('user_id'):
            self.after(800, self._refresh_batches)

    def _get_account_display_names(self) -> list[str]:
        names = []
        for i, a in enumerate(self.cfg.get("accounts", [])):
            label = a.get("name") or a.get("phone") or f"账号{i + 1}"
            names.append(label)
        return names or ["账号1"]

    def _on_account_switch(self, name: str) -> None:
        names = self._get_account_display_names()
        try:
            idx = names.index(name)
        except ValueError:
            idx = 0
        self.cfg["active_account"] = idx
        active = self.cfg["accounts"][idx]
        self.cfg["credentials"] = active
        for key, var in self._cred_vars.items():
            var.set(str(active.get(key, "") or ""))
        # 切换账号时刷新批次和登录状态
        self._login_status_lbl.configure(text='', text_color='gray')
        self._batch_menu.configure(values=['（请先登录）'], state='disabled')
        self._plan_menu.configure(values=['（请先选择学年）'], state='disabled')
        self._batch_list = []
        self._plan_list = []
        if active.get('token') and active.get('user_id'):
            self._refresh_batches()

    def _add_account(self) -> None:
        n = len(self.cfg.get("accounts", [])) + 1
        new_acct = {
            "name": f"账号{n}", "phone": "", "password": "", "token": "",
            "user_id": "", "role_key": "adviser",
            "batch_id": "", "plan_id": "", "teacher_id": "", "school_id": "",
        }
        self.cfg.setdefault("accounts", []).append(new_acct)
        new_idx = len(self.cfg["accounts"]) - 1
        names = self._get_account_display_names()
        self._account_names_var = names
        self._acct_selector.configure(values=names)
        self._acct_sel_var.set(names[new_idx])
        self._on_account_switch(names[new_idx])

    def _delete_account(self) -> None:
        accounts = self.cfg.get("accounts", [])
        if len(accounts) <= 1:
            messagebox.showwarning("无法删除", "至少需要保留一个账号。")
            return
        idx = int(self.cfg.get("active_account", 0))
        accounts.pop(idx)
        new_idx = max(0, idx - 1)
        self.cfg["active_account"] = new_idx
        names = self._get_account_display_names()
        self._account_names_var = names
        self._acct_selector.configure(values=names)
        self._acct_sel_var.set(names[new_idx])
        self._on_account_switch(names[new_idx])

    # ── 账号登录（内嵌在账号设置Tab）────────────────────────────────────

    def _set_login_status(self, text: str, color: str = 'gray') -> None:
        self._login_status_lbl.configure(text=text, text_color=color)

    def _do_account_login(self) -> None:
        phone = self._cred_vars['phone'].get().strip()
        pwd = self._cred_vars['password'].get().strip()
        if not phone or not pwd:
            messagebox.showwarning('提示', '请先填写手机号和登录密码。')
            return
        self._acct_login_btn.configure(state='disabled')
        self._set_login_status('正在获取验证码...', '#f0a500')

        def work():
            try:
                from captcha import fetch_captcha, auto_solve
                cap = fetch_captcha()
                self.after(0, lambda: self._set_login_status('正在识别验证码...', '#f0a500'))
                verif = auto_solve(cap)
                if verif:
                    self.after(0, lambda: self._set_login_status('验证成功，正在登录...', '#4caf50'))
                    self._execute_login(phone, pwd, verif, cap.client_uid)
                else:
                    self.after(0, lambda c=cap: self._open_captcha_dialog(phone, pwd, c))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    self._set_login_status(f'失败: {e}', '#f44336'),
                    self._acct_login_btn.configure(state='normal'),
                ))
                logging.error('获取验证码失败: %s', exc)

        threading.Thread(target=work, daemon=True).start()

    def _open_captcha_dialog(self, phone: str, pwd: str, cap) -> None:
        self._set_login_status('自动识别失败，请手动拖动滑块', '#f0a500')
        self._acct_login_btn.configure(state='normal')

        def on_verified(verif: str, client_uid: str):
            self._acct_login_btn.configure(state='disabled')
            self._set_login_status('验证成功，正在登录...', '#4caf50')
            self._execute_login(phone, pwd, verif, client_uid)

        CaptchaDialog(self, cap, on_verified=on_verified).focus()

    def _execute_login(self, phone: str, pwd: str, verif: str, client_uid: str) -> None:
        def work():
            try:
                from captcha import login_with_captcha
                result = login_with_captcha(phone, pwd, verif, client_uid)
                if result.get('code') == 200:
                    data = result['data']
                    self.after(0, lambda: self._on_account_login_ok(phone, pwd, data))
                else:
                    msg = result.get('msg', '未知错误')
                    self.after(0, lambda m=msg: (
                        self._set_login_status(f'登录失败: {m}', '#f44336'),
                        self._acct_login_btn.configure(state='normal'),
                    ))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    self._set_login_status(f'登录异常: {e}', '#f44336'),
                    self._acct_login_btn.configure(state='normal'),
                ))
                logging.error('登录请求异常: %s', exc)

        threading.Thread(target=work, daemon=True).start()

    def _on_account_login_ok(self, phone: str, pwd: str, data: dict) -> None:
        idx = int(self.cfg.get('active_account', 0))
        acct = self.cfg['accounts'][idx]
        acct['phone'] = phone
        acct['password'] = pwd
        acct['token'] = data.get('token', '')
        acct['user_id'] = str(data.get('userId', ''))
        nikename = data.get('nikeName', '') or data.get('username', '')
        if nikename:
            acct['name'] = nikename
        org = data.get('orgJson', {}) or {}
        if org.get('teacheId') or org.get('teacherId'):
            acct['teacher_id'] = org.get('teacheId') or org.get('teacherId', '')
        if org.get('schoolId'):
            acct['school_id'] = org['schoolId']
        self.cfg['credentials'] = acct
        # 刷新字段和账号选择器
        for key, var in self._cred_vars.items():
            var.set(str(acct.get(key, '') or ''))
        names = self._get_account_display_names()
        self._account_names_var = names
        self._acct_selector.configure(values=names)
        self._acct_sel_var.set(names[idx])
        self._acct_login_btn.configure(state='normal')
        self._set_login_status(f'✅ 已登录：{acct.get("name", phone)}', '#4caf50')
        logging.info('登录成功，userId=%s', acct['user_id'])
        self._refresh_batches()

    # ── 批次管理 ──────────────────────────────────────────────────────────

    def _refresh_batches(self) -> None:
        acct = self.cfg.get('credentials', {})
        token = acct.get('token', '')
        user_id = acct.get('user_id', '')
        role_key = acct.get('role_key', 'adviser')
        if not token or not user_id:
            self._batch_status_lbl.configure(
                text='⚠️ 请先登录获取 Token', text_color='#f0a500')
            return
        self._batch_status_lbl.configure(text='正在加载批次列表...', text_color='gray')

        def work():
            try:
                from api import GxyAPI
                info = GxyAPI.discover_credentials(token, user_id, role_key)
                batches = info.get('batches', [])
                auto_bid = info.get('batch_id', '')
                school_id = info.get('school_id', '')
                self.after(0, lambda: self._populate_batches(batches, auto_bid, school_id))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: (
                    self._batch_status_lbl.configure(
                        text=f'⚠️ 获取失败: {m}', text_color='#f44336'),
                    self._batch_menu.configure(values=['（获取失败，请重新登录）'], state='disabled'),
                ))
                logging.warning('获取批次列表失败: %s', exc)

        threading.Thread(target=work, daemon=True).start()

    def _populate_batches(self, batches: list, auto_batch_id: str, school_id: str) -> None:
        self._batch_list = batches
        idx = int(self.cfg.get('active_account', 0))
        acct = self.cfg['accounts'][idx]
        current_bid = acct.get('batch_id', '') or auto_batch_id
        if school_id:
            acct['school_id'] = school_id

        if batches:
            names = [b['batchName'] for b in batches]
            self._batch_menu.configure(values=names, state='normal')
            selected_name = names[0]
            for b in batches:
                if b['batchId'] == current_bid:
                    selected_name = b['batchName']
                    break
            self._batch_var.set(selected_name)
            for b in batches:
                if b['batchName'] == selected_name:
                    acct['batch_id'] = b['batchId']
                    break
            self._batch_status_lbl.configure(
                text=f'✅ 已加载 {len(batches)} 个学年', text_color='#4caf50')
            # 加载当前学年的实习计划
            self._refresh_plans(acct['batch_id'])
        else:
            self._batch_menu.configure(values=['（无可用学年）'], state='disabled')
            self._batch_status_lbl.configure(
                text='⚠️ Token 已失效，请点击「登录」重新获取', text_color='#f44336')

        self.cfg['credentials'] = acct

    def _on_batch_select(self, name: str) -> None:
        for b in self._batch_list:
            if b['batchName'] == name:
                idx = int(self.cfg.get('active_account', 0))
                acct = self.cfg['accounts'][idx]
                acct['batch_id'] = b['batchId']
                acct['plan_id'] = ''    # 清空计划，等待重新选择
                self.cfg['credentials'] = acct
                logging.info('学年已切换: %s (%s)', name, b['batchId'])
                self._refresh_plans(b['batchId'])
                break

    def _refresh_plans(self, batch_id: str) -> None:
        """异步加载指定学年下的实习计划列表。"""
        self._plan_menu.configure(values=['正在加载...'], state='disabled')
        cfg = self.cfg

        def work():
            try:
                from api import GxyAPI
                api = GxyAPI(cfg)
                plans = api.get_plans_by_batch(batch_id)
                self.after(0, lambda: self._populate_plans(plans))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._plan_menu.configure(
                    values=[f'获取失败: {m[:30]}'], state='disabled'))
                logging.warning('获取实习计划失败: %s', exc)

        threading.Thread(target=work, daemon=True).start()

    def _populate_plans(self, plans: list) -> None:
        self._plan_list = plans
        idx = int(self.cfg.get('active_account', 0))
        acct = self.cfg['accounts'][idx]
        current_pid = acct.get('plan_id', '')

        if plans:
            names = [p.get('planName') or p.get('name') or f"计划{i+1}" for i, p in enumerate(plans)]
            self._plan_menu.configure(values=names, state='normal')
            # 优先选择上次保存的计划
            selected_name = names[0]
            for p in plans:
                pname = p.get('planName') or p.get('name') or ''
                if p.get('planId') == current_pid:
                    selected_name = pname
                    break
            self._plan_var.set(selected_name)
            # 写入 planId
            for p in plans:
                pname = p.get('planName') or p.get('name') or ''
                if pname == selected_name:
                    acct['plan_id'] = p.get('planId', '')
                    break
            self.cfg['credentials'] = acct
            self._batch_status_lbl.configure(
                text=f'✅ 已加载 {len(plans)} 个实习计划', text_color='#4caf50')
        else:
            self._plan_menu.configure(values=['（全部计划）'], state='normal')
            self._plan_var.set('（全部计划）')
            acct['plan_id'] = ''
            self.cfg['credentials'] = acct
            self._batch_status_lbl.configure(
                text='ℹ️ 当前学年无实习计划（不按计划筛选）', text_color='gray')

    def _on_plan_select(self, name: str) -> None:
        for p in self._plan_list:
            pname = p.get('planName') or p.get('name') or ''
            if pname == name:
                idx = int(self.cfg.get('active_account', 0))
                acct = self.cfg['accounts'][idx]
                acct['plan_id'] = p.get('planId', '')
                self.cfg['credentials'] = acct
                logging.info('实习计划已切换: %s (%s)', name, p.get('planId', ''))
                break
                logging.info('批次已切换: %s (%s)', name, b['batchId'])
                break

    # ── Tab: 手动批阅 ─────────────────────────────────────────────────────────

    def _build_test_tab(self) -> None:
        tab = self.tabview.tab("🧪  手动批阅")

        # 顶部工具栏
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.pack(fill="x", padx=4, pady=(6, 4))

        ctk.CTkLabel(toolbar, text="类型：").pack(side="left", padx=(8, 4))
        self._test_type_var = ctk.StringVar(value="周报")
        ctk.CTkOptionMenu(
            toolbar, variable=self._test_type_var, values=TEST_TYPES, width=110,
        ).pack(side="left", padx=(0, 12))

        self._test_refresh_btn = ctk.CTkButton(
            toolbar, text="🔄  刷新列表", width=110, height=32,
            command=self._test_refresh,
        )
        self._test_refresh_btn.pack(side="left", padx=(0, 10))

        self._test_approve_all_btn = ctk.CTkButton(
            toolbar, text="⚡  全部批阅", width=110, height=32,
            fg_color="#6b3a0a", hover_color="#522d07",
            command=self._test_approve_all,
            state="disabled",
        )
        self._test_approve_all_btn.pack(side="right", padx=(0, 8))

        self._test_status_label = ctk.CTkLabel(
            toolbar, text="点击「刷新列表」加载待批阅内容", text_color="gray",
        )
        self._test_status_label.pack(side="left", padx=8)

        # 分隔线
        ctk.CTkFrame(tab, height=1, fg_color=("gray75", "gray30")).pack(fill="x", padx=4, pady=(0, 4))

        # 列表区域
        self._test_scroll = ctk.CTkScrollableFrame(tab)
        self._test_scroll.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self._test_rows: list[TestRow] = []

    def _test_refresh(self) -> None:
        self._test_refresh_btn.configure(state="disabled")
        self._test_status_label.configure(text="加载中...", text_color="#f0a500")
        self._test_approve_all_btn.configure(state="disabled")

        # 清空列表
        for row in self._test_rows:
            row.frame.destroy()
        self._test_rows.clear()

        item_type = TEST_TYPE_MAP.get(self._test_type_var.get(), "week")
        cfg = self.cfg

        def fetch():
            try:
                from api import GxyAPI
                api = GxyAPI(cfg)
                if item_type == "replace":
                    items = api.get_pending_replacements()
                elif item_type == "assessment":
                    items = api.get_pending_assessments()
                else:
                    items = api.get_pending_reports(item_type)
                self.after(0, lambda: self._test_populate(items, item_type))
            except Exception as exc:
                self.after(0, lambda: self._test_status_label.configure(
                    text=f"加载失败: {exc}", text_color="#f44336",
                ))
                logging.error("刷新列表失败: %s", exc)
            finally:
                self.after(0, lambda: self._test_refresh_btn.configure(state="normal"))

        threading.Thread(target=fetch, daemon=True).start()

    # 每次 after() 渲染的行数；越小越流畅，越大越快完成
    _ROW_BATCH = 15

    def _test_populate(self, items: list, item_type: str) -> None:
        cnt = len(items)
        type_cn = {"day": "日报", "week": "周报", "month": "月报", "replace": "补签申请", "summary": "总结报告", "assessment": "实习成绩考核"}.get(item_type, "")
        if not items:
            self._test_status_label.configure(
                text=f"暂无待批阅{type_cn}", text_color=("gray40", "gray70"),
            )
            self._test_approve_all_btn.configure(state="disabled")
            return

        self._test_status_label.configure(
            text=f"加载中... 0/{cnt}", text_color="#f0a500",
        )
        self._test_approve_all_btn.configure(state="disabled")
        # 保存待渲染数据，逐批插入避免主线程卡顿
        self._pending_items = list(items)
        self._pending_item_type = item_type
        self._pending_type_cn = type_cn
        self.after(1, lambda: self._insert_batch(0))

    def _insert_batch(self, offset: int) -> None:
        items = self._pending_items
        item_type = self._pending_item_type
        batch = items[offset: offset + self._ROW_BATCH]
        for item in batch:
            row = TestRow(self._test_scroll, item, item_type)
            row.bind_action(lambda r=row, it=item_type: self._test_do_single(r, it))
            row.bind_detail(lambda it=item, ity=item_type: self._show_detail(it, ity))
            self._test_rows.append(row)
        loaded = min(offset + self._ROW_BATCH, len(items))
        if loaded < len(items):
            self._test_status_label.configure(text=f"加载中... {loaded}/{len(items)}")
            self.after(1, lambda: self._insert_batch(loaded))
        else:
            cn = self._pending_type_cn
            self._test_status_label.configure(
                text=f"共 {len(items)} 条待{'打分' if self._pending_item_type == 'assessment' else '批阅'}{cn}",
                text_color=("gray40", "gray70"),
            )
            self._test_approve_all_btn.configure(state="normal")

    def _test_do_single(self, row: TestRow, item_type: str) -> None:
        import random as _random
        row.set_busy(True)
        cfg = self.cfg
        # ⚠️ tkinter 变量必须在主线程读取
        comment = row.get_comment()
        star_num = row.get_star_num()
        score = row.get_score()

        # 若用户未填写分数，从配置中随机生成
        if item_type == "summary" and score < 0:
            rv = self.cfg.get("review", {})
            sc = (rv.get("reports") or {}).get("summary", {})
            score = _random.randint(
                int(sc.get("min_score", 60) or 60),
                int(sc.get("max_score", 100) or 100),
            )
        elif item_type == "assessment" and score < 0:
            rv = self.cfg.get("review", {})
            sc = rv.get("assessment", {})
            score = _random.randint(
                int(sc.get("min_score", 60) or 60),
                int(sc.get("max_score", 100) or 100),
            )

        def work():
            try:
                from api import GxyAPI
                api = GxyAPI(cfg)
                if item_type == "replace":
                    aid = (
                        row.item.get("attendanceId")
                        or row.item.get("id")
                        or row.item.get("attendenceId")
                        or ""
                    )
                    result = api.approve_replacements([str(aid)], comment) if aid else {"code": 0}
                elif item_type == "summary":
                    rid = row.item.get("reportId") or row.item.get("id") or ""
                    result = api.review_summary_report(str(rid), score, comment) if rid else {"code": 0}
                elif item_type == "assessment":
                    sid = row.item.get("studentId", "")
                    pid = row.item.get("planId", "")
                    result = api.score_assessment(sid, pid, score, comment) if sid and pid else {"code": 0}
                else:
                    rid = row.item.get("reportId") or row.item.get("id") or ""
                    result = (
                        api.review_report(str(rid), comment, star_num=star_num)
                        if rid else {"code": 0}
                    )

                if result.get("code") == 200:
                    self.after(0, row.mark_done)
                else:
                    msg = f"code={result.get('code')} msg={result.get('msg')}"
                    self.after(0, lambda m=msg: row.mark_error(m))
            except Exception as exc:
                self.after(0, lambda e=exc: row.mark_error(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _test_approve_all(self) -> None:
        import random as _random
        item_type = TEST_TYPE_MAP.get(self._test_type_var.get(), "week")
        pending = [r for r in self._test_rows if not r.is_done()]
        if not pending:
            return
        self._test_approve_all_btn.configure(state="disabled")

        rv = self.cfg.get("review", {})

        # 在主线程预先读取所有 tkinter 变量，避免子线程访问 UI
        tasks = []
        for row in pending:
            row.set_busy(True)
            comment = row.get_comment()
            star = row.get_star_num()
            score = row.get_score()

            if item_type == "summary" and score < 0:
                sc = (rv.get("reports") or {}).get("summary", {})
                score = _random.randint(
                    int(sc.get("min_score", 60) or 60),
                    int(sc.get("max_score", 100) or 100),
                )
            elif item_type == "assessment" and score < 0:
                sc = rv.get("assessment", {})
                score = _random.randint(
                    int(sc.get("min_score", 60) or 60),
                    int(sc.get("max_score", 100) or 100),
                )

            tasks.append((row, comment, star, score))

        cfg = self.cfg

        def run_all():
            from concurrent.futures import ThreadPoolExecutor
            from api import GxyAPI

            def do_one(row, comment, star, score):
                try:
                    api = GxyAPI(cfg)
                    if item_type == "replace":
                        aid = (
                            row.item.get("attendanceId")
                            or row.item.get("id")
                            or row.item.get("attendenceId")
                            or ""
                        )
                        result = api.approve_replacements([str(aid)], comment) if aid else {"code": 0}
                    elif item_type == "summary":
                        rid = row.item.get("reportId") or row.item.get("id") or ""
                        result = api.review_summary_report(str(rid), score, comment) if rid else {"code": 0}
                    elif item_type == "assessment":
                        sid = row.item.get("studentId", "")
                        pid = row.item.get("planId", "")
                        result = api.score_assessment(sid, pid, score, comment) if sid and pid else {"code": 0}
                    else:
                        rid = row.item.get("reportId") or row.item.get("id") or ""
                        result = api.review_report(str(rid), comment, star_num=star) if rid else {"code": 0}
                    if result.get("code") == 200:
                        self.after(0, row.mark_done)
                    else:
                        msg = f"code={result.get('code')} msg={result.get('msg')}"
                        self.after(0, lambda r=row, m=msg: r.mark_error(m))
                except Exception as exc:
                    self.after(0, lambda r=row, e=exc: r.mark_error(str(e)))

            # 最多 5 个并发请求，避免过载
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(lambda t: do_one(*t), tasks))

            # 若仍有未完成行，恢复按钮可用
            self.after(0, lambda: self._test_approve_all_btn.configure(
                state="normal" if any(not r.is_done() for r in pending) else "disabled"
            ))

        threading.Thread(target=run_all, daemon=True).start()

    # ── Action Bar ────────────────────────────────────────────────────────────

    def _build_actions(self) -> None:
        bar = ctk.CTkFrame(self, height=52)
        bar.pack(fill="x", padx=14, pady=(8, 0))
        bar.pack_propagate(False)

        btn_opts = dict(height=36)

        ctk.CTkButton(
            bar, text="▶  立即运行", width=120,
            fg_color="#1a6090", hover_color="#145070",
            command=self._run_now, **btn_opts,
        ).pack(side="left", padx=(12, 6), pady=8)

        ctk.CTkButton(
            bar, text="🔍  仅查询", width=120,
            fg_color="#2d6a2d", hover_color="#235023",
            command=self._run_check, **btn_opts,
        ).pack(side="left", padx=6, pady=8)

        self._scheduler_btn = ctk.CTkButton(
            bar, text="⏰  启动定时任务", width=150,
            fg_color="#6b3a0a", hover_color="#522d07",
            command=self._toggle_scheduler, **btn_opts,
        )
        self._scheduler_btn.pack(side="left", padx=6, pady=8)

        self._status_label = ctk.CTkLabel(bar, text="● 就绪", text_color="gray")
        self._status_label.pack(side="right", padx=16)

    # ── Log Area ──────────────────────────────────────────────────────────────

    def _build_log_area(self) -> None:
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=14, pady=(8, 12))

        hdr = ctk.CTkFrame(frame, height=30, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(hdr, text="运行日志", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="清除日志", width=72, height=24, command=self._clear_log).pack(side="right")

        self._log_textbox = ctk.CTkTextbox(
            frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=12),
        )
        self._log_textbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _clear_log(self) -> None:
        self._log_textbox.configure(state="normal")
        self._log_textbox.delete("1.0", "end")
        self._log_textbox.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._log_textbox.configure(state="normal")
                self._log_textbox.insert("end", msg + "\n")
                self._log_textbox.see("end")
                self._log_textbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    # ── Config Save（静默，无弹窗）────────────────────────────────────────────

    def _save_config(self) -> None:
        # 批阅设置
        reports_cfg: dict = {}
        for rtype in ("day", "week", "month"):
            v = self._review_vars[rtype]
            reports_cfg[rtype] = {
                "enabled": v["enabled"].get(),
                "comment": v["comment"].get(),
                "star_num": STAR_MAP.get(v["star"].get(), 0),
            }
        rv = self._review_vars["replacement"]
        sv = self._review_vars.get("summary", {})
        av = self._review_vars.get("assessment", {})
        if sv:
            reports_cfg["summary"] = {
                "enabled": sv["enabled"].get(),
                "min_score": int(sv["min_score"].get() or 60),
                "max_score": int(sv["max_score"].get() or 100),
                "comment": sv["comment"].get(),
            }
        self.cfg["review"] = {
            "reports": reports_cfg,
            "replacement": {
                "enabled": rv["enabled"].get(),
                "comment": rv["comment"].get(),
            },
        }
        if av:
            self.cfg["review"]["assessment"] = {
                "enabled": av["enabled"].get(),
                "min_score": int(av["min_score"].get() or 60),
                "max_score": int(av["max_score"].get() or 100),
                "comment": av["comment"].get(),
            }
        cv = self._review_vars.get("supplement_comment", {})
        if cv:
            self.cfg["review"]["supplement_comment"] = {
                "enabled": cv["enabled"].get(),
                "comment_text": cv["comment_text"].get("1.0", "end-1c"),
            }
        # 定时设置
        self.cfg["schedule"] = {
            "run_at": self._run_at_var.get().strip(),
            "run_on_start": self._run_on_start_var.get(),
        }
        # 通知设置
        nv = self._notify_vars
        ev = nv["email"]
        self.cfg["notification"] = {
            "pushplus": {
                "enabled": nv["pushplus"]["enabled"].get(),
                "token": nv["pushplus"]["token"].get().strip(),
            },
            "email": {
                "enabled": ev["enabled"].get(),
                "smtp_server": ev["smtp_server"].get().strip(),
                "smtp_port": int(ev["smtp_port"].get().strip() or 465),
                "use_ssl": ev["use_ssl"].get(),
                "sender": ev["sender"].get().strip(),
                "password": ev["password"].get(),
                "recipient": ev["recipient"].get().strip(),
            },
            "serverchan": {
                "enabled": nv["serverchan"]["enabled"].get(),
                "sendkey": nv["serverchan"]["sendkey"].get().strip(),
            },
        }
        # 账号设置：更新当前激活账号，并保存 accounts 列表
        cv = self._cred_vars
        idx = int(self.cfg.get("active_account", 0))
        accounts = self.cfg.setdefault("accounts", [{}])
        if idx >= len(accounts):
            idx = 0
        acct = accounts[idx]
        acct.update({
            "name":     cv["name"].get().strip() or acct.get("phone", f"账号{idx + 1}"),
            "phone":    cv["phone"].get().strip(),
            "password": cv["password"].get(),
        })
        accounts[idx] = acct
        self.cfg["accounts"] = accounts
        self.cfg["active_account"] = idx
        # credentials 始终指向当前激活账号（供 api.py 使用）
        self.cfg["credentials"] = acct
        save_config(self.cfg)

    # ── Job Execution ─────────────────────────────────────────────────────────

    def _run_in_thread(self, dry_run: bool) -> None:
        if self._job_thread and self._job_thread.is_alive():
            messagebox.showwarning("任务运行中", "当前任务尚未完成，请等待后再操作。")
            return
        self._save_config()
        self._set_status("● 运行中...", "#f0a500")

        def task() -> None:
            try:
                from main import run_job
                run_job(self.cfg, dry_run=dry_run)
            except Exception as exc:
                logging.error("任务执行出错: %s", exc)
            finally:
                self.after(0, lambda: self._set_status("● 就绪", "gray"))

        self._job_thread = threading.Thread(target=task, daemon=True)
        self._job_thread.start()

    def _run_now(self) -> None:
        self._run_in_thread(dry_run=False)

    def _run_check(self) -> None:
        self._run_in_thread(dry_run=True)

    def _set_status(self, text: str, color: str) -> None:
        self._status_label.configure(text=text, text_color=color)

    # ── Scheduler ─────────────────────────────────────────────────────────────

    def _toggle_scheduler(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            self._scheduler_btn.configure(
                text="⏰  启动定时任务", fg_color="#6b3a0a", hover_color="#522d07"
            )
            self._set_status("● 就绪", "gray")
            logging.info("定时任务已停止。")
        else:
            self._start_scheduler()

    def _start_scheduler(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        self._save_config()
        run_at = self.cfg.get("schedule", {}).get("run_at", "08:30")
        try:
            hour, minute = map(int, run_at.split(":"))
        except (ValueError, AttributeError):
            messagebox.showerror(
                "格式错误", f"执行时间格式不正确：{run_at}\n应填写 HH:MM（如 08:30）"
            )
            return

        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._scheduler.add_job(
            self._scheduled_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_review",
        )
        self._scheduler.start()

        if self.cfg.get("schedule", {}).get("run_on_start", False):
            self._run_in_thread(dry_run=False)

        self._scheduler_btn.configure(
            text="⏹  停止定时任务", fg_color="#7a1a1a", hover_color="#5c1010"
        )
        self._set_status(f"● 定时任务运行中（每日 {run_at} 执行）", "#4caf50")
        logging.info("定时任务已启动，每日 %s 自动执行。", run_at)

    def _scheduled_job(self) -> None:
        from main import run_job
        try:
            run_job(self.cfg)
        except Exception as exc:
            logging.error("定时任务执行出错: %s", exc)

    # ── Window Close ──────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._scheduler and self._scheduler.running:
            if not messagebox.askyesno(
                "确认退出", "定时任务仍在运行，关闭窗口后将停止。\n确认退出？"
            ):
                return
            self._scheduler.shutdown(wait=False)
        self._save_config()
        self.destroy()

    # ── Detail Dialog ─────────────────────────────────────────────────────────

    def _show_detail(self, item: dict, item_type: str) -> None:
        """弹出报告/补签申请详情窗口。"""
        type_cn = {"day": "日报", "week": "周报", "month": "月报", "replace": "补签申请"}.get(item_type, "详情")
        is_replace = item_type == "replace"

        win = ctk.CTkToplevel(self)
        win.title(f"{type_cn}详情")
        win.geometry("700x580")
        win.resizable(True, True)
        win.grab_set()
        win.focus_force()

        # ── 顶部标题栏 ──
        hdr = ctk.CTkFrame(win, fg_color=("gray82", "gray20"), corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr, text=f"📄  {type_cn}详情",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left", padx=16, pady=10)

        # ── 基本信息区 ──
        info_frame = ctk.CTkFrame(win, fg_color=("gray92", "gray15"))
        info_frame.pack(fill="x", padx=12, pady=(8, 4))
        info_frame.columnconfigure(1, weight=1)

        name = item.get("username") or item.get("studentName") or "未知"
        cls_ = item.get("className") or ""
        if not is_replace:
            report_time = (item.get("reportTime") or item.get("startTime") or "")[:10]
            weeks = item.get("weeks") or ""
            title_str = item.get("title") or "（无标题）"
            info_items = [
                ("👤 学生", f"{name}" + (f"  （{cls_}）" if cls_ else "")),
                ("📅 时间", f"{report_time}  {weeks}".strip()),
                ("📌 标题", title_str),
            ]
        else:
            date_str = (item.get("attendenceTime") or item.get("dateTime") or "")[:10]
            reason = item.get("reason") or item.get("content") or "（未填写）"
            info_items = [
                ("👤 学生", f"{name}" + (f"  （{cls_}）" if cls_ else "")),
                ("📅 补签日期", date_str or "—"),
                ("📝 补签原因", reason),
            ]

        for row_i, (lbl, val) in enumerate(info_items):
            pad_top = (8, 2) if row_i == 0 else (2, 2)
            pad_bot = (2, 8) if row_i == len(info_items) - 1 else (2, 2)
            ctk.CTkLabel(
                info_frame, text=lbl, text_color="gray",
                font=ctk.CTkFont(size=11), anchor="e", width=80,
            ).grid(row=row_i, column=0, padx=(12, 6), pady=pad_top, sticky="e")
            ctk.CTkLabel(
                info_frame, text=val, anchor="w", wraplength=560, justify="left",
            ).grid(row=row_i, column=1, padx=(0, 12), pady=pad_top, sticky="w")

        # ── 报告正文 ──
        ctk.CTkLabel(
            win, text="📝  报告正文",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(8, 4))

        content_box = ctk.CTkTextbox(win, font=ctk.CTkFont(size=12))
        content_box.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        pre_content = item.get("content") or ""
        content_box.insert("1.0", pre_content or "加载中...")
        content_box.configure(state="disabled")

        # ── 已有教师评语 ──
        if not is_replace:
            existing_comment = item.get("commentContent") or ""
            star_num_val = item.get("starNum") or 0
            ctk.CTkLabel(
                win, text="💬  教师评语",
                font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
            ).pack(fill="x", padx=16, pady=(4, 2))
            cbox = ctk.CTkTextbox(win, height=64, font=ctk.CTkFont(size=12))
            cbox.pack(fill="x", padx=12, pady=(0, 12))

            def format_comment(comment: str, star_num: object) -> str:
                try:
                    stars_num = max(0, min(5, int(star_num or 0)))
                except (TypeError, ValueError):
                    stars_num = 0
                if stars_num:
                    stars = "★" * stars_num + "☆" * (5 - stars_num)
                    return f"{stars}  {stars_num}星\n{comment}".strip()
                return comment or "（暂无评语）"

            cbox.insert("1.0", format_comment(existing_comment, star_num_val))
            cbox.configure(state="disabled")

        # 报告详情中的评语字段比列表可靠，始终回读并更新正文与评语展示。
        if not is_replace:
            cfg = self.cfg

            def fetch_detail():
                rid = item.get("reportId") or item.get("id") or ""
                try:
                    from api import GxyAPI
                    api = GxyAPI(cfg)
                    detail = api.get_report_detail(rid) if rid else {}
                    text = detail.get("content") or pre_content or "（报告正文为空）"
                    comment = api.get_teacher_comment(detail)
                    stars = detail.get("starNum") or star_num_val
                except Exception as exc:
                    text = pre_content or f"加载失败: {exc}"
                    comment = existing_comment
                    stars = star_num_val

                def update():
                    try:
                        content_box.configure(state="normal")
                        content_box.delete("1.0", "end")
                        content_box.insert("1.0", text)
                        content_box.configure(state="disabled")
                        cbox.configure(state="normal")
                        cbox.delete("1.0", "end")
                        cbox.insert("1.0", format_comment(comment, stars))
                        cbox.configure(state="disabled")
                    except Exception:
                        pass
                try:
                    win.after(0, update)
                except Exception:
                    pass

            threading.Thread(target=fetch_detail, daemon=True).start()

    # ── Tab: 关于 ─────────────────────────────────────────────────────────────

    def _build_about_tab(self) -> None:
        tab = self.tabview.tab("ℹ️  关于")

        ctk.CTkLabel(
            tab, text="🎓  工学云指导教师自动批阅工具",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(28, 6))

        ctk.CTkLabel(
            tab, text=f"Version {VERSION}",
            font=ctk.CTkFont(size=13),
            text_color=("gray50", "gray60"),
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            tab,
            text="每日定时自动批阅日报 / 周报 / 月报  ·  审批补签申请  ·  推送未提交学生通知",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        ).pack(pady=(0, 20))

        ctk.CTkFrame(tab, height=1, fg_color=("gray75", "gray30")).pack(fill="x", padx=60, pady=(0, 18))

        ctk.CTkLabel(
            tab, text="作者",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray40", "gray65"),
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            tab, text="电脑玩家张高兴",
            font=ctk.CTkFont(size=15),
        ).pack(pady=(0, 20))

        ctk.CTkFrame(tab, height=1, fg_color=("gray75", "gray30")).pack(fill="x", padx=60, pady=(0, 10))

        ctk.CTkLabel(
            tab,
            text="本工具仅供个人学习交流使用，请遵守工学云平台相关使用条款。",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
        ).pack(pady=(0, 6))


# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
