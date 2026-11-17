# 独立交接版本验证记录

日期：2026年11月17日。

| 检查 | 结果 |
| --- | --- |
| 目标记忆、证据修订、自适应采集、本体核验、知识加工和业务接口相关后端测试 | 277项通过 |
| 前端现有Node测试集 | 232项通过 |
| 空业务数据目录的API启动 | 成功；健康检查与专题列表接口均返回200 |
| 运行必需字段契约与新方法文件 | 已核对包含 |
| 当前实际配置密钥与候选文件内容比对 | 未发现实际配置密钥进入交付文件 |
| 本机配置、业务数据、依赖及构建目录 | 由独立忽略规则排除 |

检查对象是本次整理出的独立源码。测试复用本机已安装的依赖，执行时明确加载独立目录源码；前端临时依赖链接已移除。此记录不包含新设备全量依赖重装、在线付费调查或完整端到端模型评测。

## 复现后端检查

先按根目录README安装依赖，再在 `research-workbench/` 下运行：

```bash
PYTHONPATH="$PWD:$PWD/web" .venv/bin/python -m pytest -q \
  tests/test_p2_memory.py \
  tests/test_p2_pipeline.py \
  tests/test_p2_pipelines.py \
  tests/test_p2_compaction.py \
  tests/test_p1_revisions.py \
  tests/test_p1_runtime.py \
  tests/test_p1_dependency_reads.py \
  tests/test_p1_publication.py \
  tests/test_p1_repair_service.py \
  tests/test_adaptive_collection.py \
  tests/test_knowledge_quality.py \
  tests/test_executable_ontology.py \
  tests/test_evidence_analysis.py \
  tests/test_handoff_service.py \
  tests/test_handoff_review.py \
  tests/test_handoff_package.py \
  tests/test_research_database.py \
  tests/test_research_assets.py \
  tests/test_workbench_modules.py \
  tests/test_web_api_start.py
```

## 复现前端检查

在 `research-workbench/web/frontend/` 下运行：

```bash
npm ci
npm test
```

## 启动检查

在 `research-workbench/` 下执行 `bash web/start.sh all`。健康检查路径是 `/api/health`，专题列表路径是 `/api/topics`；新环境的专题内容取决于已恢复的数据。
