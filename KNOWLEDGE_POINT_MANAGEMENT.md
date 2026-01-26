# 知识点管理功能说明

## 功能概述

在课程门户（上传习题页面）的侧边栏中添加了"知识点管理"功能，教师可以对知识点进行完整的管理操作。

## 功能模块

### 1. 知识点列表 (`/teacher/knowledge-points/<subject_id>/`)
- **功能**：显示该科目的所有知识点
- **操作**：
  - 搜索知识点
  - 查看关联习题数量
  - 查看父知识点和子知识点
  - 分页显示（每页10条）

### 2. 添加知识点 (`/teacher/knowledge-points/<subject_id>/add/`)
- **功能**：添加新的知识点
- **字段**：
  - 知识点名称（必填）
  - 父知识点（可选，用于构建知识点层级）
- **验证**：
  - 父知识点只能选择同一科目的知识点
  - 知识点名称不能为空

### 3. 编辑知识点 (`/teacher/knowledge-points/<subject_id>/<kp_id>/edit/`)
- **功能**：编辑现有知识点
- **限制**：
  - 父知识点不能选择自己
  - 只能编辑同一科目的知识点

### 4. 删除知识点 (`/teacher/knowledge-points/<subject_id>/<kp_id>/delete/`)
- **功能**：删除知识点
- **限制**：
  - 如果知识点关联了习题，无法删除
  - 需要先删除所有关联的习题

### 5. 知识点与习题关联 (`/teacher/knowledge-points/<subject_id>/<kp_id>/exercises/`)
- **功能**：管理知识点与习题的关联关系
- **操作**：
  - 查看该科目的所有习题
  - 关联或取消关联习题
  - 显示已关联习题数量
  - 分页显示（每页10条）
- **API**：`/teacher/knowledge-points/<subject_id>/<kp_id>/toggle-exercise/` (POST)

### 6. 知识点关系管理 (`/teacher/knowledge-points/<subject_id>/relationships/`)
- **功能**：管理知识点之间的前置关系
- **操作**：
  - 添加知识点关系（前置→后续）
  - 删除知识点关系
  - 查看所有关系
  - 显示关系统计信息
- **限制**：
  - 知识点不能指向自己
  - 不能添加重复的关系
- **API**：
  - 添加：`/teacher/knowledge-points/<subject_id>/relationships/add/` (POST)
  - 删除：`/teacher/knowledge-points/<subject_id>/relationships/<relationship_id>/delete/` (POST)

## 文件结构

### 后端
- `learning/knowledge/views_teacherknowledge_management.py` - 知识点管理视图
- `learning/urls.py` - URL路由配置

### 前端
- `learning/templates/teacher/knowledge_point_list.html` - 知识点列表
- `learning/templates/teacher/knowledge_point_form.html` - 知识点表单（添加/编辑）
- `learning/templates/teacher/knowledge_point_exercise_association.html` - 习题关联管理
- `learning/templates/teacher/knowledge_point_relationship.html` - 知识点关系管理
- `learning/templates/teacher/course_management_sidebar.html` - 侧边栏（已更新）

## 使用流程

### 添加知识点
1. 点击课程门户进入上传习题页面
2. 在侧边栏点击"知识点管理"
3. 点击"添加知识点"按钮
4. 填写知识点名称和可选的父知识点
5. 点击"保存"

### 关联习题
1. 在知识点列表中，点击某个知识点的"关联习题"按钮
2. 查看该科目的所有习题
3. 点击"关联"或"已关联"按钮来切换关联状态
4. 系统会实时更新关联计数

### 管理知识点关系
1. 在知识点列表底部，点击"管理知识点关系"按钮
2. 在左侧面板选择前置知识点和后续知识点
3. 点击"添加关系"按钮
4. 在右侧列表中可以查看和删除已有的关系

## 权限控制

- 只有该科目的授课教师可以管理知识点
- 系统会验证教师是否有权限管理该科目

## 数据模型

### KnowledgePoint
- `subject` - 所属科目
- `name` - 知识点名称
- `parent` - 父知识点（自引用，可选）
- `similar_points` - 相似知识点（多对多）

### KnowledgeGraph
- `subject` - 所属科目
- `source` - 前置知识点
- `target` - 后续知识点
- 唯一约束：(subject, source, target)

### QMatrix
- `exercise` - 习题
- `knowledge_point` - 知识点
- `weight` - 权重（默认1.0）

## 前端交互

### 关联习题
- 使用AJAX实时更新关联状态
- 无需刷新页面
- 实时更新关联计数

### 添加关系
- 使用表单提交
- 成功后自动刷新页面
- 显示成功/失败提示

## 注意事项

1. **删除知识点**：如果知识点关联了习题，需要先删除关联关系
2. **父知识点**：用于构建知识点层级，可选
3. **知识点关系**：表示前置关系，用于诊断系统分析学生的学习路径
4. **权限验证**：所有操作都会验证教师权限

## 后续扩展

可以考虑的功能扩展：
- 批量导入知识点
- 知识点关系的可视化展示
- 知识点的难度等级设置
- 知识点的学习时间估计
- 知识点的学习资源关联
