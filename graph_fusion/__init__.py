"""
多学科知识图谱融合 + 融合图谱质量评估（独立功能包）
======================================================================
本包把 Learn/edu-knowledge-graph 下「多学科图谱融合」与「融合图谱评估」
两块算法移植为可在主 Django 项目内直接调用的模块。

模块划分：
  - fusion.py            : 多学科 / 多课程图谱融合核心（数据源 = MySQL）
  - entity_quality.py    : 实体质量启发式评估（移植自 Learn KnowledgeQualityEvaluator）
  - deepseek_evaluator.py: 融合图谱质量评估（DeepSeek 大模型验证关系准确性）
  - views.py             : 教师端页面 / 融合接口 / 评估接口

数据分工（沿用主项目约定）：
  - 知识点实体        -> MySQL  learning.models.KnowledgePoint
  - 知识点关系        -> MySQL  learning.models.KnowledgeGraph
"""
