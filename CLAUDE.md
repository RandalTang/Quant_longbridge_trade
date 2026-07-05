# CLAUDE.md

Longbridge或其他券商（待添加） 量化交易辅助系统：
目前实现：日线 EMA5/EMA30 金叉死叉策略（TQQQ/SQQQ 轮动），产生信号后发飞书提醒，不自动下单，交易手动执行。

## 项目结构

- `src/quant_longbridge_trade/brokers/` — 券商抽象层
  - `base.py`：`Broker` 接口 + 通用数据模型（`DailyCandle` / `QuoteSnapshot` / `AccountSnapshot`）
  - `longbridge/`：长桥实现；以后新增券商（IBKR、嘉信）在这里加目录，并在 `brokers/__init__.py` 的 `create_broker()` 注册
- `src/quant_longbridge_trade/strategies/` — 策略层，纯函数（输入 K 线，输出信号），不碰网络和 SDK
  - `indicators.py`：公共指标（EMA 等），所有策略共用
  - `ema_cross.py`：EMA 快慢线金叉/死叉策略；新策略在这里加文件，并在 `strategies/__init__.py` re-export
- `src/quant_longbridge_trade/ema_service.py` — 服务层：拉数据 → 调策略 → 查持仓 → 拼消息
- `src/quant_longbridge_trade/daemon.py` — 常驻调度：工作日美东 15:55 盘前预警 / 16:10 收盘确认
- `src/quant_longbridge_trade/monitor.py` — 独立的盘中轮询监控（价格阈值/涨跌幅/回撤）
- `src/quant_longbridge_trade/notifier.py` — 飞书 webhook 通知
- `src/quant_longbridge_trade/state.py` — JSON 状态存储（`.data/alert_state.json`，提醒去重）
- `src/quant_longbridge_trade/cli.py` — CLI 入口：`quant-lb account / monitor / signal / daemon`
- `*.ipynb` — 回测 notebook（yfinance 数据），与线上代码不共享

## 常用命令

```bash
# 开发环境（if use .venv）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

# 不装包直接跑
PYTHONPATH=src python -m quant_longbridge_trade signal --symbol TQQQ.US

# 语法检查（无测试框架）
python3 -m compileall -q src/quant_longbridge_trade
```

## 架构约束

- 策略、服务、调度层只依赖 `Broker` 接口，禁止直接 import 券商 SDK；券商相关代码只能出现在 `brokers/<券商名>/` 下
- 新策略照 `strategies/ema_cross.py` 的模式写：纯函数，输入 K 线列表，输出带 `dedupe_key` 的信号 dataclass；公共指标放 `strategies/indicators.py`
- 价格计算统一用 `Decimal`，不用 float
- 凭证放 `.env`（长桥 API Key、飞书 webhook），不提交 Git；新增配置项同步更新 `.env.example`

## 注意事项

- 不要主动执行 git 提交/推送等操作，除非明确要求
- 本项目目前只做信号提醒，不实现自动下单

<!-- 以下为项目规范，后续补充 -->
