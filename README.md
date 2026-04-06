# 工学云 - 指导教师自动批阅工具

> **v1.0.0** · 每日定时自动批阅日报/周报/月报、审批补签申请，并推送未提交/未签到学生名单通知。

---

## 两种使用方式

| 方式 | 适合人群 | 启动方法 |
|------|----------|----------|
| **GUI 图形界面**（推荐） | 所有用户 | 双击 exe 或 `python app.py` |
| **命令行模式** | 熟悉终端 | `python main.py` |

---

## GUI 快速开始

### 方式一：直接运行 exe（免安装）

1. 下载 `dist\工学云自动批阅工具\` 整个目录
2. 将 `config.yaml` 放到与 `工学云自动批阅工具.exe` **同级目录**
3. 双击 `工学云自动批阅工具.exe` 启动

> 首次运行若无 `config.yaml`，程序会报错提示。可复制项目根目录的 `config.yaml` 模板。

### 方式二：从源码运行

```bash
pip install -r requirements.txt
python app.py
```

### GUI 功能介绍

| 标签页 | 功能 |
|--------|------|
| 📝 批阅设置 | 开启/关闭日报、周报、月报自动批阅，设置评语和星级 |
| ⏰ 定时设置 | 配置每日定时时间，支持启动时立即执行 |
| 🔔 通知设置 | 配置 PushPlus / 邮件 / Server酱 通知推送 |
| 👤 账号设置 | 管理多个教师账号，支持一键切换、JSON 导入 |
| 🧪 手动批阅 | 手动拉取并批阅/审批，点击每条记录可查看详情 |
| ℹ️ 关于 | 版本信息和技术栈 |

### 手动批阅 - 查看详情

在「手动批阅」标签页加载报告列表后，点击任意一行的 **学生姓名或日期** 区域，即可弹出详情窗口，查看：
- 学生信息（姓名、班级、时间、标题）
- 报告正文（自动从 API 加载）
- 已有教师评语和星级

---

## 多账号管理

GUI「账号设置」页面支持：
- **切换当前账号**：下拉选择，保存后立即生效
- **新增账号（JSON 导入）**：将以下 JSON 粘贴到输入框并点击「导入」：
  ```json
  {
    "name": "张老师",
    "phone": "138xxxxxxxx",
    "password": "登录密码（可选）",
    "token": "从浏览器复制的 token",
    "user_id": "工学云用户ID",
    "role_key": "adviser",
    "batch_id": "实习批次ID",
    "teacher_id": "教师ID",
    "school_id": "学校ID"
  }
  ```
- **删除账号**：选中后点击「删除当前」

---

## 命令行快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 `config.yaml`

打开 `config.yaml`，按说明填写：

| 配置项 | 说明 |
|--------|------|
| `credentials.token` | 从浏览器 localStorage 复制（初次运行用） |
| `credentials.phone` | 手机号（token 过期后自动重新登录用） |
| `credentials.password` | 登录密码（token 过期后自动重新登录用） |
| `schedule.run_at` | 每日自动执行时间，如 `08:30` |
| `review.reports.comment` | 批阅评语，留空则不填 |
| `notification.*` | 选择一种通知方式并填写对应 token/密码 |

#### 获取 token（首次配置）

1. 浏览器打开 [工学云教师端](https://p3.gongxueyun.com)，正常登录
2. 按 F12 打开开发者工具 → Console，粘贴以下代码：
   ```js
   JSON.parse(localStorage.getItem('userinfo')).token
   ```
3. 复制输出的 token 填入 `config.yaml`

### 3. 测试运行（不实际提交）

```bash
python main.py --check
```

### 4. 立即执行一次

```bash
python main.py --now
```

### 5. 启动定时任务

```bash
python main.py
```

程序会在每日配置时间自动运行，日志保存在 `gxy_agent.log`。

---

## 通知渠道配置

### PushPlus（推荐 · 微信推送）

1. 注册 [PushPlus](https://www.pushplus.plus)，获取 token
2. 在 `config.yaml` 填入：
   ```yaml
   notification:
     pushplus:
       enabled: true
       token: "你的token"
   ```

### QQ 邮件通知

1. 在 QQ 邮箱设置中开启 SMTP，获取授权码
2. 在 `config.yaml` 填入：
   ```yaml
   notification:
     email:
       enabled: true
       sender: "你的QQ号@qq.com"
       password: "授权码"
       recipient: "接收通知的邮箱"
   ```

### Server酱（微信推送）

1. 注册 [Server酱](https://sct.ftqq.com)，获取 SendKey
2. 在 `config.yaml` 填入：
   ```yaml
   notification:
     serverchan:
       enabled: true
       sendkey: "你的SendKey"
   ```

---

## 打包成 exe（开发者）

运行根目录的 `build.bat`（自动安装 PyInstaller 并打包）：

```bat
build.bat
```

输出目录：`dist\工学云自动批阅工具\`

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | GUI 主界面（customtkinter，推荐使用） |
| `config.yaml` | 配置文件（账号、定时、通知） |
| `main.py` | 命令行入口 + APScheduler 定时任务 |
| `api.py` | 工学云 API 客户端（批阅、查询等） |
| `crypto.py` | AES 加密 + MD5 签名工具 |
| `notifier.py` | 通知推送（PushPlus / 邮件 / Server酱） |
| `build.bat` | PyInstaller 打包脚本 |
| `gxy_agent.log` | 运行日志（自动生成，与 exe/脚本同目录） |

---

## 开机自启（Windows · 命令行模式）

使用任务计划程序，或创建 `start.bat`：

```bat
@echo off
cd /d "C:\Users\zhang\Desktop\gxy-agent"
python main.py
```

将此脚本添加到 Windows 任务计划程序，设置为开机后运行。

---

## 注意事项

- token 有效期较长，但到期后程序会自动用手机号+密码重新登录（需提前配置密码）
- 若 `review.reports.comment` 留空，即仅点击批阅通过，不填写评语
- 定时任务依赖本机保持开机，若需 7×24 运行请部署到服务器
- exe 版本运行时需确保 `config.yaml` 与 exe 在同一目录

---

## 版本历史

| 版本 | 说明 |
|------|------|
| v1.0.0 | 初始版本：GUI 界面、多账号、手动批阅、报告详情、关于页 |
