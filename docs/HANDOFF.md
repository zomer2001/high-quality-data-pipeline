# 项目交接说明

基线日期：2026年11月17日。以原工作目录当前文件为准，纳入原仓库尚未提交的本体、核验、业务接口和界面更新。独立仓库只保留当前初始快照，不继承原综合项目的Git历史。

## 方法与业务代码

| 能力 | 主要入口 |
| --- | --- |
| 目标驱动记忆P2 | `research-workbench/searchos/harness/p2_memory.py`及相关上下文中间层 |
| 用途感知证据修订P1 | `research-workbench/searchos/socm/revisions.py`、`revision_state.py`及 `harness/p1_runtime.py` |
| 自适应采集 | `research-workbench/searchos/collection_policy/` |
| 运行配置与模块开关 | `research-workbench/searchos/config/run_config.py`、`settings.py` |
| 知识业务库与字段目录 | `research-workbench/searchos/knowledge_store/`、`design/knowledge-extraction-handoff-20261104/schema/` |
| 证据核验与本体分析 | `research-workbench/searchos/knowledge_quality/` |
| 导入、预览与发布 | `research-workbench/web/api/knowledge_handoff/` |
| 业务查询与关系投影 | `research-workbench/web/api/research_database.py`、`research_assets.py`、`research_projection.py` |
| 工作台与图谱 | `research-workbench/web/frontend/src/components/topics/` |

P1与P2以可选研究增强形式保留；默认开关为关闭。主工作台的研究设置提供自适应采集选项，其他模块入口与运行链见 `research-workbench/docs/innovation-modules.md`。报告中的合成场景、离线核验及对照实验各有各的验证口径。

## 数据交接

源码不附带真实业务库、完整原文、搜索和运行缓存。原工作目录主要数据位置为：

- `research-workbench/data/knowledge/`：业务数据库及相关知识资产。
- `research-workbench/data/` 其他子目录：资料归档、采集与运行记录等。
- `research-workbench/knowledge_base/`：本地资料库。
- `research-workbench/.env`、`web_settings.json`：本机服务配置，另行填写，不入Git。

恢复数据时保持目录层级和资料引用关系；迁移运行中的SQLite库应使用数据库备份方式或停止服务后复制，避免遗漏写入中的WAL内容。项目内 `examples/` 与各项测试数据用于离线演示和回归检查。

## 保留与分离

已保留核心源码、现有技能库、界面资源、运行契约、主系统测试、当前报告与实现记录，以及上游版权和许可文件。

外层 `SearchOS/`、`widesearch_*`、实验结果、专利、临时文件和原Git历史保留在原综合工程中。本次不复制依赖这些旧评测组件的7个测试：`test_ablation_flags.py`、`test_compare_schema_ablation.py`、`test_eval_fixed_schema.py`、`test_eval_qa.py`、`test_preprocess_cache.py`、`test_re_reformat_and_rescore.py`、`test_reformat_grounding.py`。原工程中的这些文件未删除。

历史实现文档可能含旧工程路径；当前开发入口以本文定位表和实际代码为准。

## 开发同步

以本独立仓库为后续开发入口。远端编码代理和本地开发分别使用任务分支，通过PR合入主分支，再拉取最新主分支开展下一项任务。原综合工程与本仓库是两个独立副本，文件修改不会自动相互同步。
