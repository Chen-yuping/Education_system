# AI 模型批改功能 - 快速开始指南

## 5分钟快速配置

### 1. 安装依赖 (1分钟)

```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥 (2分钟)

**方式一：使用 .env 文件（推荐）**

```bash
# 复制示例文件
cp .env.example .env

# 编辑 .env 文件，填入你的 API 密钥
# 使用你喜欢的编辑器打开 .env
```

**选择一个 LLM 提供商**:

**OpenAI** (推荐用于高质量评分)
```
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-openai-api-key-here
LLM_MODEL=gpt-3.5-turbo
```

**Qwen** (推荐用于成本控制)
```
LLM_PROVIDER=qwen
LLM_API_KEY=your-qwen-api-key-here
LLM_MODEL=qwen-turbo
```

**Claude** (推荐用于平衡)
```
LLM_PROVIDER=claude
LLM_API_KEY=your-claude-api-key-here
LLM_MODEL=claude-3-sonnet-20240229
```

### 3. 测试配置 (1分钟)

```bash
python test_llm_grading.py
```

如果看到 "✓ 测试成功！" 说明配置正确。

### 4. 启动应用 (1分钟)

```bash
python manage.py runserver
```

## 使用方法

### 教师端操作

1. 登录系统 → 进入"批改作业"
2. 选择需要批改的题目
3. 点击"批改"按钮
4. 点击"AI评分建议"按钮
5. 查看 AI 的评分建议
6. 点击"正确"或"错误"提交批改

## 获取 API 密钥

### OpenAI

1. 访问 https://platform.openai.com/account/api-keys
2. 点击 "Create new secret key"
3. 复制密钥

**费用**: 按 token 计费，约 $0.001-0.003 每次评分

### Qwen (阿里云)

1. 访问 https://dashscope.aliyuncs.com/
2. 登录或注册
3. 创建 API 密钥
4. 复制密钥

**费用**: 按 token 计费，约 $0.0003-0.001 每次评分

### Claude (Anthropic)

1. 访问 https://console.anthropic.com/
2. 创建 API 密钥
3. 复制密钥

**费用**: 按 token 计费，约 $0.0005-0.002 每次评分

## 常见问题

### Q: 如何禁用 AI 评分？
A: 清空 `.env` 中的 `LLM_API_KEY` 或设置为空字符串。

### Q: 如何更换 LLM 提供商？
A: 编辑 `.env` 文件，修改 `LLM_PROVIDER` 和 `LLM_API_KEY`。

### Q: 评分速度太慢怎么办？
A: 尝试更快的模型，如 `gpt-3.5-turbo` 或 `qwen-turbo`。

### Q: 如何查看日志？
A: 
```bash
tail -f logs/django.log | grep "AI grading"
```

### Q: 支持离线使用吗？
A: 不支持，需要网络连接调用 LLM API。

## 文件说明

| 文件 | 说明 |
|------|------|
| `.env.example` | 环境变量示例 |
| `test_llm_grading.py` | 测试脚本 |
| `learning/llm_grading.py` | LLM 评分核心模块 |
| `LLM_GRADING_SETUP.md` | 详细配置指南 |
| `AI_GRADING_FEATURE.md` | 功能使用指南 |
| `IMPLEMENTATION_SUMMARY.md` | 实现总结 |

## 下一步

- 阅读 `LLM_GRADING_SETUP.md` 了解详细配置
- 阅读 `AI_GRADING_FEATURE.md` 了解功能详情
- 运行 `test_llm_grading.py` 测试配置
- 在批改页面测试 AI 评分功能

## 支持

遇到问题？

1. 检查 `.env` 文件配置
2. 运行 `test_llm_grading.py` 测试
3. 查看服务器日志
4. 阅读详细文档

## 成本估算

| 提供商 | 每次评分 | 1000次评分 |
|--------|---------|-----------|
| OpenAI | $0.001-0.003 | $1-3 |
| Qwen | $0.0003-0.001 | $0.3-1 |
| Claude | $0.0005-0.002 | $0.5-2 |

## 安全提示

⚠️ **重要**: 不要在代码中硬编码 API 密钥，使用 `.env` 文件！

```python
# ❌ 错误
api_key = "sk-xxx"

# ✅ 正确
api_key = os.environ.get('LLM_API_KEY')
```

## 完成！

现在你可以在批改页面使用 AI 评分功能了。祝你使用愉快！
