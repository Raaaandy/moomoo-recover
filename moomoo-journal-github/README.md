# 回看 · Moomoo Journal

本地交易复盘应用：读取 moomoo OpenD 的真实成交，把开仓、平仓、策略、盈亏和个人笔记放在一起。

## 功能

- 实盘成交同步、重复成交去重；同步后可离线复盘。
- 股票 / ETF、期权分开查看，支持日期、标的、账户和观点筛选。
- 成交列表右侧提供可拖拽的策略识别、开仓和平仓框。
- 单张 Call / Put 及 PDS、CDS、PCS、CCS 识别；确认后关联。
- 完整交易统一 Thesis 与笔记；支持部分平仓、先进先出成本匹配。
- 已实现毛盈亏；填写总费用且全部平仓后显示净盈亏。
- 中文 Summary PDF、JSON 备份、本地 SQLite 存储。

## 环境

Windows 10/11，Python 3.13（当前验证版本），moomoo OpenD。浏览器界面无需 Node.js；Node 仅用于开发时检查 JavaScript。

## 首次安装

1. 安装 Python，并勾选加入 PATH。
2. 从 [moomoo 官方网站](https://www.moomoo.com/download/OpenAPI) 下载 OpenD，启动并登录。
3. 下载或克隆本项目，双击 `setup.cmd` 安装依赖。
4. 双击 `start.cmd`，打开 `http://127.0.0.1:8765/`。
5. 在「连接设置」选择开户券商、端口（默认 11111），读取并选择实盘账户。
6. 选择日期并同步成交。

需要一键同时启动 OpenD：复制 `local-config.example.ps1` 为 `local-config.ps1`，填写自己的 OpenD 图形界面程序路径。登录及验证码仍在 OpenD 内完成。自动同步由应用内设置决定。

手动启动：

```powershell
python -m venv .venv
python -m pip --python .venv/Scripts/python.exe install -r requirements.txt
.venv/Scripts/python.exe app.py
```

## 复盘操作

选中成交填写单笔 Thesis 与笔记。拖入单张期权或两腿组合，可识别策略并确认保存；四腿移仓分旧、新组合操作。识别不确定时手动选择开仓或平仓。

同账户、同合约及策略的关联成交会归为完整交易；也可手动关联开平仓。完整交易下填写统一复盘，展开查看原始成交与原笔记。尚未结束的仓位不计算浮动盈亏。

日期筛选范围决定显示哪些交易，但完整交易盈亏可能包含日期范围以外的相关成交。美股成交时间保留 OpenD 原始时间，通常是美东时间。

## 数据与备份

关闭浏览器不会删除已保存数据。数据库、账户设置、个人笔记及日志位于 `data/`。可下载 JSON 备份；目前没有 JSON 导入恢复界面。完整迁移请停止后台后复制整个 `data` 文件夹。

本项目仅绑定本机 `127.0.0.1`，无云上传功能。数据未作磁盘加密，不应把服务暴露到公网。关闭浏览器后服务仍可能运行。

`data/`、本地配置、日志、虚拟环境及生成的报告均已加入 `.gitignore`。不要使用 `git add -f` 上传这些文件。

## 盈亏及限制

- 标准美股期权默认乘数 100，可按真实合约修改；股票默认乘数 1。
- 手续费需要填写，未填写时展示毛盈亏。
- 行权、指派、拆股、转入持仓、非标准合约、缺失历史需要人工核对。
- 比例价差及任意多腿结构不做自动识别。
- OpenD 历史成交接口支持实盘，需账户有相关权限；可取回历史范围以实际接口返回为准。
- 只读交易接口，不调用下单、改单、撤单或解锁交易。

## 测试

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

测试使用临时数据库和合成成交，不需要 moomoo 登录。GitHub Actions 在 Windows + Python 3.13 上运行相同测试及 JavaScript 语法检查。

## 项目结构

```text
app.py                本地服务、数据库、同步和报告
cycles.py             期权策略开平仓匹配
stocks.py             股票完整交易与成本
campaigns.py          调整交易汇总
recognize.py          期权策略识别
static/               中文界面、拖拽和筛选
tests/                合成数据回归测试
```

## 提交到 GitHub

只提交本目录的源码、静态文件、测试及说明。可以使用 GitHub Desktop 添加本目录并创建仓库。提交前检查变更列表中没有 `data/`、`.venv/` 或本地配置。

本项目未附开源许可证；公开仓库不自动赋予他人再使用许可。若计划正式开源，请先选择并添加许可证。

## 接口文档

- [历史成交](https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-fill-list.html)
- [账户查询](https://openapi.moomoo.com/moomoo-api-doc/trade/get-acc-list.html)

本项目为独立工具，与 moomoo 官方无关联。
