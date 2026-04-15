# Quant Longbridge Trade

一个最小的 Longbridge 量化交易系统骨架，目前实现账号资金、股票持仓查询，以及简单行情监控提醒。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## 配置

Longbridge Python SDK 支持从环境变量读取 API Key 配置：

```bash
export LONGBRIDGE_APP_KEY="你的 App Key"
export LONGBRIDGE_APP_SECRET="你的 App Secret"
export LONGBRIDGE_ACCESS_TOKEN="你的 Access Token"
```

可参考 `.env.example`。

程序启动时也会自动读取项目根目录的 `.env` 文件。`.env` 不要提交到 Git。

## 查询账号资金与持仓

查询全部币种资金与全部股票持仓：

```bash
quant-lb account
```

只查某个币种：

```bash
quant-lb account --currency USD
```

只查指定股票持仓：

```bash
quant-lb account --symbols AAPL.US 700.HK
```

输出 JSON，方便给策略或风控模块消费：

```bash
quant-lb account --currency HKD --symbols 700.HK --json
```

也可以不安装 editable package，直接运行：

```bash
PYTHONPATH=src python -m quant_longbridge_trade account --json
```

## 监控 TQQQ

第一版监控器使用轮询方式获取实时行情，满足规则时在终端打印提醒。

监控 TQQQ 当前价高于 75：

```bash
quant-lb monitor --symbol TQQQ.US --price-above 75
```

监控 5 分钟窗口涨跌幅，涨幅超过 2% 或跌幅低于 -2% 提醒：

```bash
quant-lb monitor --symbol TQQQ.US --pct-change-above 2 --pct-change-below -2
```

监控从启动后的高点回撤超过 3%：

```bash
quant-lb monitor --symbol TQQQ.US --drawdown-below -3
```

组合多个规则，并设置 10 秒轮询、10 分钟冷却：

```bash
quant-lb monitor \
  --symbol TQQQ.US \
  --interval-seconds 10 \
  --cooldown-seconds 600 \
  --price-above 75 \
  --pct-change-below -2 \
  --drawdown-below -3
```

测试时可以限制轮询次数：

```bash
quant-lb monitor --symbol TQQQ.US --price-above 75 --max-ticks 3
```

## EMA 策略信号和飞书提醒

日线 EMA5/EMA30 策略不需要盘中高频轮询。建议每天美股收盘后检查一次，例如新加坡时间 06:00。

单次检查 TQQQ EMA5/EMA30 信号：

```bash
quant-lb signal --symbol TQQQ.US --fast 5 --slow 30
```

有买卖信号时发送飞书提醒：

```bash
quant-lb signal --symbol TQQQ.US --fast 5 --slow 30 --notify
```

无信号也推送一次，用于测试飞书 webhook：

```bash
quant-lb signal --symbol TQQQ.US --fast 5 --slow 30 --notify-no-signal --no-dedupe
```

检查失败时也推送飞书错误提醒：

```bash
quant-lb signal --symbol TQQQ.US --fast 5 --slow 30 --notify-errors
```

这类错误包括 Longbridge Access Token 过期/无效、API Key 缺失、行情权限不足、网络异常等。

常驻运行，每天新加坡时间 06:00 检查一次：

```bash
quant-lb daemon \
  --symbol TQQQ.US \
  --fast 5 \
  --slow 30 \
  --run-at 06:00 \
  --timezone Asia/Singapore
```

提醒去重状态保存在 `.data/alert_state.json`。同一天同一个信号默认只推送一次。

daemon 默认会把检查异常推送到飞书，并对相同错误做 1 小时冷却，避免刷屏。可以调整：

```bash
quant-lb daemon --error-cooldown-seconds 1800
```

如果不想推送异常：

```bash
quant-lb daemon --no-notify-errors
```

### 飞书机器人配置

1. 在飞书里创建一个群，或者进入你想接收提醒的群。
2. 打开群设置，找到 `机器人`。
3. 添加 `自定义机器人`。
4. 复制机器人 webhook 地址，格式类似：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

5. 写入项目 `.env`：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/你的-webhook"
```

如果机器人启用了签名校验，也把签名密钥写入 `.env`：

```bash
FEISHU_WEBHOOK_SECRET="你的签名密钥"
```

### 云服务器 systemd 示例

在服务器上把项目放到 `/opt/quant-longbridge-trade` 后，可以创建：

```ini
# /etc/systemd/system/quant-lb.service
[Unit]
Description=Quant Longbridge Trade Daemon
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/quant-longbridge-trade
EnvironmentFile=/opt/quant-longbridge-trade/.env
ExecStart=/opt/miniconda/envs/quant-longbridge/bin/quant-lb daemon --symbol TQQQ.US --fast 5 --slow 30 --run-at 06:00 --timezone Asia/Singapore
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable quant-lb
sudo systemctl start quant-lb
sudo journalctl -u quant-lb -f
```

## 模块用法

```python
from quant_longbridge_trade import AccountService, create_trade_context

ctx = create_trade_context()
service = AccountService(ctx)
snapshot = service.get_account_snapshot(currency="USD", symbols=["AAPL.US"])

print(snapshot.to_dict())
```
