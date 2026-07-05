# 部署指南

服务器现状（2026-07 部署验证过）：

| 项目 | 值 |
|---|---|
| 服务器用户 | `quant`（非 root，家目录 `/home/quant`） |
| 项目目录 | `/home/quant/quant/Quant_longbridge_trade` |
| Python 环境 | 项目目录下的 `.venv` |
| systemd 服务 | `quant-longbridge.service`（`/etc/systemd/system/quant-longbridge.service`） |
| 凭证文件 | 项目目录下的 `.env`（隐藏文件，`ls -la` 才能看到） |

daemon 启动参数（当前线上）：

```
quant-lb daemon --symbol TQQQ.US --fast 5 --slow 30 \
  --watch-sqqq-death-cross --notify-no-signal \
  --preclose-at 15:55 --confirm-at 16:10 \
  --market-timezone America/New_York --poll-seconds 60
```

---

## 日常更新代码（最常用）

```bash
# ① 本地：提交并推送改动
git add -A && git commit -m "..." && git push

# ② 服务器：用 quant 用户登录
cd ~/quant/Quant_longbridge_trade
git pull
.venv/bin/pip install -e .        # 目录结构有变动时必须；只改逻辑可跳过，但跑一下不亏

# ③ 重启前验证（不发飞书、不影响线上状态）
.venv/bin/python tests/test_live_signal.py --dry-run

# ④ 重启并确认
sudo systemctl restart quant-longbridge
systemctl status quant-longbridge     # Active: active (running)，Main PID 是新的
sudo journalctl -u quant-longbridge -f  # Ctrl+C 退出，不影响服务
```

**必须重启才生效**：`git pull` 只更新磁盘文件，运行中的老进程不会自己换代码。

## 修改了 .env / 环境变量之后

- 改 `.env` → `sudo systemctl restart quant-longbridge` 即可
- 改 service 文件本身 → `sudo systemctl daemon-reload && sudo systemctl restart quant-longbridge`
- 改 `~/.bashrc` 里的 export → 无效！systemd 不读 shell 配置，把值写进 `.env`
- 验证进程实际读到的值：
  ```bash
  sudo cat /proc/$(pgrep -f "quant-lb daemon")/environ | tr '\0' '\n' | grep LONGBRIDGE
  ```
- 注意：代码里 `.env` **不会覆盖已存在的同名环境变量**；如果 service 文件里有 `Environment=` 写死的旧值，会压住 `.env` 的新值

## 全新部署（换服务器时）

```bash
# 1. 拉代码
git clone <仓库地址> ~/quant/Quant_longbridge_trade
cd ~/quant/Quant_longbridge_trade

# 2. 装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

# 3. 配凭证
cp .env.example .env && vim .env   # 填长桥三件套 + 飞书 webhook
chmod 600 .env

# 4. 验证
.venv/bin/python tests/test_live_signal.py --dry-run   # 长桥连接 + 策略计算
.venv/bin/python tests/test_feishu_webhook.py          # 飞书（会真发一条测试消息）

# 5. 配 systemd
sudo vim /etc/systemd/system/quant-longbridge.service  # 内容见下
sudo systemctl daemon-reload
sudo systemctl enable quant-longbridge
sudo systemctl start quant-longbridge
sudo journalctl -u quant-longbridge -f
```

service 文件模板：

```ini
[Unit]
Description=Quant Longbridge EMA Monitor
After=network-online.target

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant/Quant_longbridge_trade
EnvironmentFile=/home/quant/quant/Quant_longbridge_trade/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/quant/quant/Quant_longbridge_trade/.venv/bin/quant-lb daemon --symbol TQQQ.US --fast 5 --slow 30 --watch-sqqq-death-cross --notify-no-signal --preclose-at 15:55 --confirm-at 16:10 --market-timezone America/New_York --poll-seconds 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> `WorkingDirectory` 必须指向项目目录：去重状态 `.data/alert_state.json` 和 `.env` 都按这个目录找。
> `PYTHONUNBUFFERED=1` 让日志实时打印，不然 print 会攒一批才出现在 journalctl 里。

## 排查速查

```bash
systemctl status quant-longbridge            # 服务状态
sudo journalctl -u quant-longbridge -n 100   # 最近 100 行日志
systemctl cat quant-longbridge               # 看服务配置（凭证从哪读、启动参数）
ps aux | grep quant-lb                       # 进程在不在、完整启动命令
```

常见问题：

- **长桥 Access Token 过期**（有效期约 3 个月）：去 open.longportapp.com 刷新，更新 `.env` 里的 `LONGBRIDGE_ACCESS_TOKEN`，重启服务。过期时 daemon 会推飞书异常提醒（相同错误 1 小时冷却）
- **收不到飞书**：先跑 `tests/test_feishu_webhook.py` 排除 webhook 问题；再查 `.data/alert_state.json` 是不是当天该信号已发过（同一天同信号只推一次）
- **找不到 .env / 项目**：`.env` 是隐藏文件要 `ls -la`；注意每个用户家目录独立，用 root 登录看不到 quant 用户家里的东西
- **验收标准**：开着 `--notify-no-signal` 时，每个交易日美东 15:55 和 16:10 各会来一条飞书（无信号也有心跳）；一整个交易日一条都没收到 = 服务有问题，上服务器看日志
