# AI 模型批改功能 - 文档索引

## 📚 文档导航

### 🚀 快速开始 (5分钟)
- **[QUICK_START.md](QUICK_START.md)** - 快速配置指南
  - 5分钟快速配置步骤
  - 获取 API 密钥的方法
  - 常见问题解答

### 📖 详细文档

#### 配置和安装
- **[LLM_GRADING_SETUP.md](LLM_GRADING_SETUP.md)** - 详细配置指南
  - 完整的安装步骤
  - 多个 LLM 提供商的配置
  - 成本估算
  - 故障排除
  - 安全建议

#### 功能使用
- **[AI_GRADING_FEATURE.md](AI_GRADING_FEATURE.md)** - 功能使用指南
  - 功能介绍和特性
  - 使用流程
  - API 端点文档
  - 评分逻辑说明
  - 高级用法

#### 实现细节
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - 实现总结
  - 实现的功能列表
  - 文件修改清单
  - 系统流程图
  - 代码质量说明
  - 后续改进方向

#### 变更总结
- **[CHANGES_SUMMARY.md](CHANGES_SUMMARY.md)** - 完整变更总结
  - 新增文件列表
  - 修改文件列表
  - 功能流程
  - 配置说明
  - 文件统计

### 🔧 配置文件

- **[.env.example](.env.example)** - 环境变量示例
  - 复制此文件为 `.env`
  - 填入你的 API 密钥

### 🧪 测试

- **[test_llm_grading.py](test_llm_grading.py)** - 测试脚本
  - 验证 LLM 配置是否正确
  - 运行: `python test_llm_grading.py`

### 💻 源代码

- **[learning/llm_grading.py](learning/llm_grading.py)** - LLM 评分核心模块
  - LLMGrader 类
  - 支持多个 LLM 提供商
  - 完善的错误处理

## 🎯 使用场景

### 场景 1: 首次使用

1. 阅读 [QUICK_START.md](QUICK_START.md)
2. 运行 [test_llm_grading.py](test_llm_grading.py)
3. 在批改页面测试功能

### 场景 2: 详细了解

1. 阅读 [AI_GRADING_FEATURE.md](AI_GRADING_FEATURE.md)
2. 查看 [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
3. 阅读源代码 [learning/llm_grading.py](learning/llm_grading.py)

### 场景 3: 故障排除

1. 查看 [LLM_GRADING_SETUP.md](LLM_GRADING_SETUP.md) 的故障排除部分
2. 运行 [test_llm_grading.py](test_llm_grading.py)
3. 查看服务器日志

### 场景 4: 生产部署

1. 阅读 [LLM_GRADING_SETUP.md](LLM_GRADING_SETUP.md) 的安全建议
2. 配置 `.env` 文件
3. 运行测试脚本验证
4. 启动应用

## 📋 文档对照表

| 文档 | 用途 | 阅读时间 |
|------|------|---------|
| QUICK_START.md | 快速配置 | 5分钟 |
| LLM_GRADING_SETUP.md | 详细配置 | 15分钟 |
| AI_GRADING_FEATURE.md | 功能使用 | 20分钟 |
| IMPLEMENTATION_SUMMARY.md | 实现细节 | 15分钟 |
| CHANGES_SUMMARY.md | 变更总结 | 10分钟 |

## 🔑 关键概念

### LLM (Large Language Model)
大语言模型，如 GPT-3.5、GPT-4、Qwen、Claude 等

### API 密钥
用于调用 LLM API 的认证凭证

### 置信度 (Confidence)
AI 对评分的信心程度，0-1 之间的数值

### 评分结果 (Grading Result)
包括是否正确、分数、反馈、理由等信息

## 🚀 快速命令

```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境变量示例
cp .env.example .env

# 测试配置
python test_llm_grading.py

# 启动应用
python manage.py runserver

# 查看日志
tail -f logs/django.log | grep "AI grading"
```

## 💡 常见问题

### Q: 如何开始使用？
A: 阅读 [QUICK_START.md](QUICK_START.md)

### Q: 如何配置 API 密钥？
A: 阅读 [LLM_GRADING_SETUP.md](LLM_GRADING_SETUP.md)

### Q: 如何使用 AI 评分功能？
A: 阅读 [AI_GRADING_FEATURE.md](AI_GRADING_FEATURE.md)

### Q: 如何解决问题？
A: 查看 [LLM_GRADING_SETUP.md](LLM_GRADING_SETUP.md) 的故障排除部分

### Q: 成本是多少？
A: 查看各文档中的成本估算部分

## 📞 支持

遇到问题？

1. 查看相关文档
2. 运行 [test_llm_grading.py](test_llm_grading.py)
3. 查看服务器日志
4. 联系系统管理员

## 📝 文件清单

### 新建文件
- [x] learning/llm_grading.py - LLM 评分核心模块
- [x] .env.example - 环境变量示例
- [x] test_llm_grading.py - 测试脚本
- [x] LLM_GRADING_SETUP.md - 配置指南
- [x] AI_GRADING_FEATURE.md - 功能指南
- [x] IMPLEMENTATION_SUMMARY.md - 实现总结
- [x] QUICK_START.md - 快速开始
- [x] CHANGES_SUMMARY.md - 变更总结
- [x] README_AI_GRADING.md - 本文件

### 修改文件
- [x] requirements.txt - 添加依赖
- [x] edu_system/settings.py - 添加 LLM 配置
- [x] learning/views_teacher.py - 添加 AI 评分视图
- [x] learning/urls.py - 添加 AI 评分路由
- [x] learning/templates/teacher/grade_subjective.html - 添加 AI 评分 UI

## 🎓 学习路径

### 初级用户
1. QUICK_START.md - 快速配置
2. 在批改页面测试功能
3. 查看 AI 评分结果

### 中级用户
1. AI_GRADING_FEATURE.md - 了解功能
2. LLM_GRADING_SETUP.md - 详细配置
3. 自定义评分参数

### 高级用户
1. IMPLEMENTATION_SUMMARY.md - 了解实现
2. learning/llm_grading.py - 阅读源代码
3. 自定义评分逻辑

## 🔐 安全提示

⚠️ **重要**: 
- 不要在代码中硬编码 API 密钥
- 使用 `.env` 文件管理敏感信息
- 定期轮换 API 密钥
- 监控 API 使用情况

## 📊 支持的 LLM 提供商

| 提供商 | 模型 | 推荐用途 |
|--------|------|---------|
| OpenAI | gpt-3.5-turbo | 平衡质量和成本 |
| OpenAI | gpt-4 | 最高质量 |
| Qwen | qwen-turbo | 成本最低 |
| Claude | claude-3-sonnet | 平衡 |

## 🎉 完成！

现在你已经了解了 AI 模型批改功能的全部内容。选择适合你的文档开始吧！

---

**最后更新**: 2024年1月22日  
**版本**: 1.0  
**状态**: 生产就绪 ✅
