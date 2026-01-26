# 学生学习诊断逻辑说明

## 概述
学生学习诊断系统用于分析学生对各个知识点的掌握程度，并以知识点关系图和柱状图两种方式展示。

## 核心数据模型

### 1. StudentDiagnosis（学生诊断记录）
```
- student: 学生用户
- knowledge_point: 知识点
- mastery_level: 掌握程度（0-1之间的浮点数）
- practice_count: 练习次数
- correct_count: 正确次数
- last_practiced: 最后练习时间
- diagnosis_model_id: 诊断模型ID（3表示使用的是某个特定模型）
```

### 2. KnowledgePoint（知识点）
```
- name: 知识点名称
- subject: 所属科目
```

### 3. KnowledgeGraph（知识点关系）
```
- source: 源知识点
- target: 目标知识点
- subject: 所属科目
```

## 诊断流程

### 第一步：页面加载
1. 用户访问学生诊断页面 (`student_diagnosis` 视图)
2. 获取学生已选修的所有科目
3. 渲染诊断页面，显示科目选择器

### 第二步：选择科目
1. 用户从下拉菜单选择科目
2. 触发 `loadDiagnosisData()` 函数
3. 调用API: `/learning/student/api/knowledge-points/{subject_id}/`

### 第三步：API数据获取 (`student_knowledge_data_api`)

#### 3.1 获取知识点
```python
knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)
```
获取该科目的所有知识点

#### 3.2 获取学生掌握情况
```python
student_diagnoses = StudentDiagnosis.objects.filter(
    student=request.user,
    knowledge_point__subject_id=subject_id,
    diagnosis_model_id=3  # 只获取模型3的数据
)
```
获取学生对每个知识点的诊断数据

#### 3.3 构建节点数据
对每个知识点，计算：
- **掌握程度** (mastery_level): 0-1之间
- **颜色编码**:
  - 绿色 (#2ecc71): ≥80% (掌握良好)
  - 橙色 (#f39c12): 60%-80% (基本掌握)
  - 红色 (#e74c3c): <60% (需要加强)
  - 灰色 (#95a5a6): 0% (未学习)
- **准确率**: correct_count / practice_count * 100%

#### 3.4 构建链接数据
```python
relationships = KnowledgeGraph.objects.filter(subject_id=subject_id)
```
获取知识点之间的关系，构建图的边

#### 3.5 聚类检测
使用DFS算法检测知识点聚类：
- 基于知识点之间的连接关系
- 将相关的知识点分组
- 为每个节点分配聚类ID

#### 3.6 返回数据
```json
{
  "status": "success",
  "nodes": [...],           // 知识点节点
  "links": [...],           // 知识点关系
  "clusters": [...],        // 聚类信息
  "mastery_stats": {        // 掌握程度统计
    "mastered": 21,         // 已掌握（≥80%）
    "partial": 4,           // 基本掌握（60%-80%）
    "weak": 5,              // 需要加强（40%-60%）
    "beginner": 4,          // 刚开始学（0%-40%）
    "none": 17              // 未学习（0%）
  }
}
```

## 视图展示

### 1. 关系图视图
- 使用D3.js绘制知识点关系图
- 节点大小和颜色表示掌握程度
- 节点之间的连线表示知识点关系
- 支持拖拽、缩放、悬停查看详情

### 2. 柱状图视图
- 按掌握程度从高到低排序
- X轴: 知识点名称
- Y轴: 掌握程度百分比
- 柱子颜色对应掌握程度
- 支持悬停查看详细信息

## 掌握程度计算

### 简单诊断模型
```
mastery_level = correct_count / practice_count
```

### 掌握程度分类
| 范围 | 分类 | 颜色 | 含义 |
|------|------|------|------|
| ≥80% | 已掌握 | 绿色 | 学生已充分掌握该知识点 |
| 60%-80% | 基本掌握 | 橙色 | 学生基本掌握，还需巩固 |
| 40%-60% | 需要加强 | 红色 | 学生掌握不足，需要加强 |
| 0%-40% | 刚开始学 | 红色 | 学生刚开始学习 |
| 0% | 未学习 | 灰色 | 学生未做过相关练习 |

## 数据更新流程

### 当学生完成练习时
1. 创建 `AnswerLog` 记录
2. 调用 `update_knowledge_mastery()` 函数
3. 更新或创建 `StudentDiagnosis` 记录
4. 重新计算 `mastery_level`

```python
def update_knowledge_mastery(student, exercise, is_correct):
    # 获取该题目涉及的所有知识点
    related_kps = QMatrix.objects.filter(exercise=exercise)
    
    for q_item in related_kps:
        # 获取或创建诊断记录
        diagnosis = StudentDiagnosis.objects.filter(
            student=student,
            knowledge_point=q_item.knowledge_point
        ).first()
        
        # 更新练习次数和正确次数
        diagnosis.practice_count += 1
        if is_correct:
            diagnosis.correct_count += 1
        
        # 重新计算掌握程度
        diagnosis.mastery_level = diagnosis.correct_count / diagnosis.practice_count
        diagnosis.save()
```

## 关键特性

### 1. 多模型支持
- 诊断数据通过 `diagnosis_model_id` 区分
- 目前使用 `diagnosis_model_id=3` 的数据
- 支持未来扩展其他诊断模型

### 2. 知识点聚类
- 自动检测相关知识点的聚类
- 帮助学生理解知识点之间的关系
- 支持按聚类查看学习进度

### 3. 双向关系支持
- 知识点之间可能有单向或双向关系
- 图中用箭头表示单向关系
- 双向关系用实线表示

### 4. 实时更新
- 学生每完成一次练习，诊断数据实时更新
- 掌握程度动态变化
- 颜色编码自动更新

## 使用场景

### 学生使用
1. 查看自己的知识点掌握情况
2. 识别薄弱知识点
3. 了解知识点之间的关系
4. 制定学习计划

### 教师使用
1. 分析全班学生的学习情况
2. 识别教学难点
3. 调整教学策略
4. 提供个性化指导

## 性能优化

### 数据库查询优化
- 使用 `select_related()` 减少数据库查询
- 使用 `filter()` 只获取必要数据
- 缓存掌握程度统计结果

### 前端渲染优化
- 使用D3.js的力模拟算法优化节点布局
- 支持缩放和拖拽交互
- 异步加载数据，不阻塞UI

## 总结

学生学习诊断系统通过以下方式帮助学生和教师：

1. **可视化展示**: 用图表直观展示掌握程度
2. **关系分析**: 显示知识点之间的关系
3. **聚类识别**: 自动识别相关知识点
4. **实时更新**: 练习后立即更新诊断数据
5. **多维度分析**: 支持关系图和柱状图两种视图

这样可以帮助学生更好地理解自己的学习进度，制定更有效的学习计划。
