# 项目工作说明

## 范围与入口

这是独立的数据管线业务系统。主要工作目录为 `research-workbench/`；项目入口说明见根目录README，算法与业务模块定位见 `docs/HANDOFF.md`。外部WideSearch实验工程、旧SearchOS检出和完整业务数据不属于此仓库。

## 开发约定

- 目标驱动记忆、证据修订和自适应采集通过有效运行配置接入；维护现有的可选开关语义。
- `design/knowledge-extraction-handoff-20261104/schema/` 和 `design/knowledge-ingestion-v2/` 是程序依赖的交付契约，修改时同步考虑调用方与测试。
- 对象身份、事实记录、来源版本和证据定位分别管理；保留幂等发布与版本检查语义。
- 数据库和实际资料在本地 `research-workbench/data/` 等目录保存；测试优先采用临时数据库与虚构证据。
- 前端工作同时遵循 `research-workbench/web/frontend/AGENTS.md` 中的Next.js版本说明。
- 修改后运行与改动相关的检查；已有启动和测试命令见根目录README及 `docs/VALIDATION.md`。
- 交付文档默认使用Markdown。文档中的项目内文件和图片采用相对路径。

## 协作与配置

源码通过Git管理；实际密钥、本机配置、业务数据、依赖目录及生成产物受 `.gitignore` 排除。用户的明确指示优先于本文档的工作约定。
