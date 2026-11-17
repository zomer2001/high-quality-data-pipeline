# 高质量数据管线与专题研究工作台

基于 SearchOS 扩展的科技情报数据管线，将连续调查、网页与本地资料读取、来源归档、结构化知识加工、证据核验和产品技术图谱组织在同一工作台中。

此仓库从2026年11月17日的本地最新源码建立独立版本，包含目标驱动记忆、证据修订、自适应采集，以及本体核验与推导模块。

## 项目入口

| 目录 | 内容 |
| --- | --- |
| `research-workbench/searchos/` | 调查引擎、共享状态、新方法、知识存储与规则分析 |
| `research-workbench/web/api/` | 工作台业务接口、知识加工与资料管理 |
| `research-workbench/web/frontend/` | Next.js界面、知识字段查询与AntV G6图谱 |
| `research-workbench/design/` | 程序依赖的字段目录、映射契约和知识加工说明 |
| `research-workbench/tests/` | 主系统与新方法的测试 |
| `report/` | 当前建设报告、实际界面截图和实现记录 |
| `docs/` | 本仓库交接和验证记录 |

先阅读[项目交接说明](docs/HANDOFF.md)和[当前建设报告](report/2026-11-16/高质量数据管线建设进展报告_20261116.md)。

## 当前能力

- 专题工作台：专题管理、网页及本地材料读取、原文与摘要归档。
- 目标驱动记忆：目标原文保护、实际收益经验卡、缺口匹配与多样性选择。
- 证据修订：按用途与版本维护证据，追踪实际读取依赖并修复相关产物。
- 自适应采集：按目标缺口与信息增量调整任务顺序，结合来源图和去冗余算法组织阅读。
- 知识加工：七维字段目录、对象与单位对齐、候选预览、事务发布及原文追溯。
- 本体与核验：事实级证据台账、分类关系推导、共同技术分析和前提撤回后的重算。
- 知识图谱：从业务记录生成对象关系图，提供布局、筛选、原文联动与导出。

目标驱动记忆、证据修订和自适应采集是可选增强模块，默认配置关闭；界面入口和运行配置见交接说明。自动模型抽取当前关闭，已有候选结果可以通过导入流程加工。

## 安装与启动

建议 Python 3.12、Node.js 20.9以上版本。项目依赖由Python项目声明和前端锁文件管理。

```bash
cd research-workbench
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[access,local-docs,crawling,dev]'
cp .env.example .env
.venv/bin/python -m playwright install chromium
cd web/frontend
npm ci
cd ../..
bash web/start.sh all
```

界面地址为 `http://127.0.0.1:3000`，后端监听 `http://127.0.0.1:8000`。默认以构建后的前端启动；开发界面时可用 `WORKBENCH_DEV=1 bash web/start.sh all`。

模型和搜索服务通过本机 `.env` 或页面设置配置。凭据不进入仓库。网络调查调用按所配置服务计费；离线测试使用样例数据。

## 数据与验证

仓库提供源码、字段契约、示例及测试；真实业务数据库、139份完整资料归档、历史运行记录和本机依赖单独保存。恢复已有知识库时，将单独交接的数据放回 `research-workbench/data/` 等对应目录。没有恢复数据的新环境不会显示原工作目录中的现有知识资产。

验证方法与本次执行结果见[验证记录](docs/VALIDATION.md)。

## 协作

本仓库为独立项目；原始综合工程和原Git历史另行保留。后续开发从本仓库最新主分支创建任务分支，通过PR（合并申请）汇总修改。Google Jules等支持GitHub写入的编码代理可使用本仓库；Gemini网页端导入代码用于读取与讨论，导入快照不会自动跟随后续提交更新。

## 来源与许可

基于 [antins-labs/SearchOS](https://github.com/antins-labs/SearchOS) 扩展，保留[上游MIT许可](research-workbench/LICENSE)及[相关许可说明](research-workbench/LEGAL.md)。`research-workbench/README.md` 保留上游项目介绍；本项目的使用入口以本页和交接说明为准。第三方依赖遵循各自许可证。
