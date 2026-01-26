# AI 模型批改功能配置指南

## 功能概述

本系统集成了大语言模型（LLM）自动批改主观题的功能。教师在批改页面可以点击"AI评分建议"按钮，系统会调用配置的LLM API对学生答案进行评分，并提供评分建议、反馈和理由。

## 支持的LLM提供商

- **OpenAI** (推荐): GPT-3.5-turbo, GPT-4
- **阿里云通义千问 (Qwen)**: qwen-turbo, qwen-plus
- **Anthropic Claude**: claude-3-sonnet, claude-3-opus

## 配置步骤

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

已包含的依赖：
- `requests==2.31.0` - HTTP请求库
- `python-dotenv==1.0.0` - 环境变量管理

### 2. 配置环境变量

创建或编辑项目根目录的 `.env` 文件：

```bash
# OpenAI 配置
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-openai-api-key-here
LLM_MODEL=gpt-3.5-turbo

# 或者 Qwen 配置
# LLM_PROVIDER=qwen
# LLM_API_KEY=your-qwen-api-key-here
# LLM_MODEL=qwen-turbo

# 或者 Claude 配置
# LLM_PROVIDER=claude
# LLM_API_KEY=your-claude-api-key-here
# LLM_MODEL=claude-3-sonnet-20240229
```

### 3. 更新 Django 设置

在 `edu_system/settings.py` 中已配置：

```python
LLM_CONFIG = {
    'provider': os.environ.get('LLM_PROVIDER', 'openai'),
    'api_key': os.environ.get('LLM_API_KEY', ''),
    'model': os.environ.get('LLM_MODEL', 'gpt-3.5-turbo'),
    'temperature': 0.3,
    'max_tokens': 500,
    'timeout': 30,
}
```

## 获取 API 密钥

### OpenAI

1. 访问 https://platform.openai.com/account/api-keys
2. 创建新的 API 密钥
3. 复制密钥到 `.env` 文件

**费用**: 按 token 计费，GPT-3.5-turbo 较便宜，GPT-4 较贵

### 阿里云通义千问 (Qwen)

1. 访问 https://dashscope.aliyuncs.com/
2. 登录或注册阿里云账户
3. 创建 API 密钥
4. 复制密钥到 `.env` 文件

**费用**: 按 token 计费，价格较低

### Anthropic Claude

1. 访问 https://console.anthropic.com/
2. 创建 API 密钥
3. 复制密钥到 `.env` 文件

**费用**: 按 token 计费

## 使用方法

### 教师端操作

1. 登录系统，进入"批改作业"页面
2. 选择需要批改的题目和学生答案
3. 点击"批改"按钮打开批改模态框
4. 在模态框中点击"AI评分建议"按钮
5. 系统会调用LLM进行评分，显示：
   - 评分结果（正确/错误/不确定）
   - 分数（0-100）
   - 置信度（0-100%）
   - 反馈意见
   - 评分理由
6. 根据AI建议进行最终判断，点击"正确"或"错误"提交批改

### 评分结果说明

- **评分结果**: AI对答案的判断（正确/错误/不确定）
- **分数**: 0-100分的评分
- **置信度**: AI对评分的信心程度
  - 90-100%: 非常有信心
  - 70-89%: 有信心
  - 50-69%: 中等信心
  - <50%: 低信心，建议人工审核
- **反馈**: 对学生的建议和改进意见
- **评分理由**: AI的评分依据

## 评分逻辑

系统会向LLM提供以下信息：

1. **题目内容** - 学生需要回答的问题
2. **参考答案** - 标准答案
3. **学生答案** - 学生提交的答案
4. **答案解析** - 可选的详细解析

LLM会综合考虑这些信息，评估学生答案的正确性和完整性。

## 成本估算

### OpenAI GPT-3.5-turbo

- 输入: $0.0005 / 1K tokens
- 输出: $0.0015 / 1K tokens
- 平均每次评分成本: $0.001-0.003

### Qwen

- 价格更低，约为 OpenAI 的 1/3-1/2

### Claude

- 价格介于两者之间

## 故障排除

### 问题: "AI评分服务暂时不可用"

**原因**: 
- API密钥未配置或无效
- 网络连接问题
- API服务故障

**解决方案**:
1. 检查 `.env` 文件中的 API 密钥是否正确
2. 检查网络连接
3. 查看服务器日志获取详细错误信息

### 问题: "评分结果解析失败"

**原因**: LLM返回的响应格式不符合预期

**解决方案**:
1. 检查 LLM 模型是否支持
2. 尝试更换模型
3. 查看服务器日志获取 LLM 的原始响应

### 问题: 评分速度很慢

**原因**: 
- API 响应时间长
- 网络延迟

**解决方案**:
1. 检查网络连接
2. 尝试更换 LLM 提供商
3. 增加超时时间（在 settings.py 中修改 `timeout` 值）

## 安全建议

1. **不要在代码中硬编码 API 密钥**，使用环境变量
2. **定期轮换 API 密钥**
3. **监控 API 使用情况**，防止异常消费
4. **设置 API 配额限制**
5. **在生产环境中使用 HTTPS**
6. **定期审计日志**，检查异常活动

## 日志

系统会记录所有 AI 评分操作的日志。查看日志：

```bash
# 查看最近的日志
tail -f logs/django.log | grep "AI grading"
```

## 禁用 AI 评分

如果需要临时禁用 AI 评分功能，可以：

1. 清空 `.env` 中的 `LLM_API_KEY`
2. 或在 `settings.py` 中设置 `LLM_CONFIG['api_key'] = ''`

此时点击"AI评分建议"按钮会显示"未配置LLM API密钥"的提示。

## 高级配置

### 调整评分参数

在 `settings.py` 中修改 `LLM_CONFIG`：

```python
LLM_CONFIG = {
    'provider': 'openai',
    'api_key': os.environ.get('LLM_API_KEY', ''),
    'model': 'gpt-3.5-turbo',
    'temperature': 0.3,      # 0-1, 越低越稳定
    'max_tokens': 500,       # 最大输出长度
    'timeout': 30,           # 超时时间（秒）
}
```

- **temperature**: 控制输出的随机性
  - 0.0: 最稳定，输出最一致
  - 0.5: 平衡
  - 1.0: 最随机，输出最多样

### 自定义评分提示词

编辑 `learning/llm_grading.py` 中的 `_build_grading_prompt()` 方法来自定义评分提示词。

## 支持

如有问题，请：

1. 查看服务器日志
2. 检查 API 配置
3. 测试 API 连接
4. 联系系统管理员
