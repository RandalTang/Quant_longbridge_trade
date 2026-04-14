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

## 模块用法

```python
from quant_longbridge_trade import AccountService, create_trade_context

ctx = create_trade_context()
service = AccountService(ctx)
snapshot = service.get_account_snapshot(currency="USD", symbols=["AAPL.US"])

print(snapshot.to_dict())
```
