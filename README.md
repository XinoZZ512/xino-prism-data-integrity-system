# 思诺棱镜-数据诚信检测系统

思诺棱镜-数据诚信检测系统是一个**本地优先、只读、无账号、无计费、默认不联网**的数据完整性与表格审计工具。它是根据公开研究方法和独立工程设计实现的平替 MVP，不包含 LingJingSystem 的专有代码、二进制或资源。

## 已实现能力

- 输入 `.csv`、`.tsv`、`.xlsx`、`.xlsm`；XLSM 只盘点 VBA 项目，不执行宏。
- Excel 结构审计：公式错误 token、公式漂移、公式中的硬编码常量、易变/间接函数、同表公式循环风险、隐藏行列/工作表、合并单元格提示。
- 数值表审计：重复行、重复连续块、简单列间加减/比值关系偏离、规则序列偏离、小数尾数低熵、末位数字集中；Benford 首位数字筛查可选开启。
- 每条 finding 都包含严重性、证据强度、误报风险、置信度、复核优先级、单元格/范围、现象、统计依据、假设、可能的良性原因、建议复核和原始证据。
- 输出 JSON、UTF-8 CSV、自包含离线 HTML；结果包含输入 SHA-256 和逐检测器 coverage，明确已完成、部分覆盖、跳过或禁用。
- 输入文件永不覆盖；报告默认写入单独目录。

## 安装与运行

需要 Python 3.11+。在项目目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m lingjing_alt audit .\data\study.xlsx --out-dir .\reports
```

也可以不安装包，直接在仓库根目录执行：

```powershell
python -m lingjing_alt audit .\data\study.csv --out-dir .\reports
```

有候选问题时退出码为 `1`；没有问题且覆盖完整为 `0`；覆盖部分/跳过时为 `2`；输入或参数错误为 `4`；未预期内部错误为 `5`。`--strict` 会把任何部分/跳过覆盖直接作为退出码 `2`。

可选参数：

```powershell
# 仅在数据适合 Benford 假设时开启
python -m lingjing_alt audit input.csv --out-dir reports --benford

# 缩小资源上限，避免处理超大文件失控
python -m lingjing_alt audit input.xlsx --out-dir reports --max-rows 50000 --max-columns 256 --strict
```

## 输出文件

- `*.audit.json`：机器可读结果，结构约束见 [`schema/audit-result.schema.json`](schema/audit-result.schema.json)。
- `*.findings.csv`：便于筛选和导入其他审计系统。
- `*.report.html`：不依赖外部资源的离线报告，可直接用浏览器打开。

## 测试

```powershell
python -m pytest
```

测试使用合成 CSV/XLSX，仅覆盖项目自己的临时目录，不读取或上传真实实验数据。

## 安全与解释边界

- 代码不发起 HTTP 请求，不上传文件，不登录，不使用远端配额或分析授权。
- XLSX/XLSM 作为不可信压缩包读取；当前使用 `openpyxl`，不执行宏，不跟随外部链接，不调用 Excel 进行重新计算。
- 结果是筛查证据，不是造假或 misconduct 结论。Benford、重复值、离群关系、机械化尾数和公式风险都有合理良性解释；应保留原始数据、实验设计、版本和人工复核记录。
- 公式计算值可能是 Excel 保存的缓存值或未知状态；本版本优先审计公式文本和结构，不能替代受控环境中的公式重新计算。
- 当前只支持标准 `.xlsx/.xlsm`，不读取旧式二进制 `.xls`；不执行 VBA、Power Query、Power Pivot、动态数组运行时或外部数据连接。

## 后续路线

1. 增加稳定的 XLSX 公式解析器、跨工作表依赖图和受控 LibreOffice 重算适配。
2. 增加 GRIM、GRIMMER、SPRITE、statcheck 文本抽取和 `strait` 风格有界量表检查。
3. 建立合成缺陷基准集、真实公开工作簿精度/召回评估和版本化规则目录。
4. 增加本地浏览器 UI、审计历史、规则配置、finding 忽略理由和 SARIF 导出。
5. 用 PyInstaller 打包 Windows 可执行版本，并在打包前审查依赖许可证和网络行为。

## 许可证

MIT，见 [`LICENSE`](LICENSE)。
