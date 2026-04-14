# Quant Longbridge Trade

一个最小的 Longbridge 量化交易系统骨架，目前实现账号资金与股票持仓查询。

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

## 模块用法

```python
from quant_longbridge_trade import AccountService, create_trade_context

ctx = create_trade_context()
service = AccountService(ctx)
snapshot = service.get_account_snapshot(currency="USD", symbols=["AAPL.US"])

print(snapshot.to_dict())
```
