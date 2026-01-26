# AI 模型批改功能

## 功能介绍

本系统集成了大语言模型（LLM）自动批改主观题的功能。教师在批改主观题时，可以点击"AI评分建议"按钮，系统会调用配置的LLM API对学生答案进行智能评分，并提供详细的评分建议、反馈和理由。

## 核心特性

✅ **多LLM支持** - 支持 OpenAI、阿里云通义千问、Anthropic Claude  
✅ **智能评分** - 基于题目、参考答案、学生答案进行综合评分  
✅ **详细反馈** - 提供评分理由、改进建议和置信度  
✅ **易于集成** - 无缝集成到现有批改流程  
✅ **安全可靠** - 支持环境变量配置，不硬编码密钥  
✅ **错误处理** - 完善的错误处理和日志记录  

## 文件结构

```
learning/
├── llm_grading.py              # LLM评分核心模块
├── views_teacher.py            # 教师视图（包含ai_grade_answer视图）
├── urls.py                     # URL路由（包含AI评分API端点）
└── templates/teacher/
    └── grade_subjective.html   # 批改页面（包含AI评分UI）

edu_system/
└── settings.py                 # Django设置（包含LLM配置）

.env.example                    # 环境变量示例
LLM_GRADING_SETUP.md           # 详细配置指南
AI_GRADING_FEATURE.md          # 本文件
test_llm_grading.py            # 测试脚本
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API 密钥：

```bash
# 选择一个LLM提供商
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL=gpt-3.5-turbo
```

### 3. 测试配置

运行测试脚本验证配置：

```bash
python manage.py shell < test_llm_grading.py
```

或者：

```bash
python test_llm_grading.py
```

### 4. 启动应用

```bash
python manage.py runserver
```

## 使用流程

### 教师端操作步骤

1. **登录系统** - 使用教师账户登录

2. **进入批改页面** - 点击"批改作业"菜单

3. **选择题目** - 从列表中选择需要批改的学生答案

4. **打开批改模态框** - 点击"批改"按钮

5. **查看答案信息** - 模态框显示：
   - 学生信息
   - 题目内容
   - 学生答案
   - 参考答案
   - 答案解析

6. **请求AI评分** - 点击"AI评分建议"按钮

7. **查看AI建议** - 系统显示：
   - 评分结果（正确/错误/不确定）
   - 分数（0-100）
   - 置信度（0-100%）
   - 反馈意见
   - 评分理由

8. **做出最终判断** - 根据AI建议和自己的判断，点击"正确"或"错误"

9. **提交批改** - 系统保存批改结果

## API 端点

### AI 评分 API

**端点**: `POST /learning/teacher/api/answer/<log_id>/ai-grade/`

**请求头**:
```
X-CSRFToken: <csrf_token>
```

**响应**:
```json
{
    "success": true,
    "grading": {
        "is_correct": true,
        "score": 85,
        "feedback": "学生的答案基本正确...",
        "reasoning": "评分理由：...",
        "confidence": 0.92
    }
}
```

**错误响应**:
```json
{
    "success": false,
    "message": "错误信息"
}
```

## 配置选项

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_PROVIDER` | LLM提供商 | `openai`, `qwen`, `claude` |
| `LLM_API_KEY` | API密钥 | `sk-...` |
| `LLM_MODEL` | 模型名称 | `gpt-3.5-turbo` |

### Django 设置

在 `edu_system/settings.py` 中配置：

```python
LLM_CONFIG = {
    'provider': 'openai',           # LLM提供商
    'api_key': os.environ.get('LLM_API_KEY', ''),
    'model': 'gpt-3.5-turbo',       # 模型
    'temperature': 0.3,              # 温度（0-1）
    'max_tokens': 500,               # 最大输出长度
    'timeout': 30,                   # 超时时间（秒）
}
```

## LLM 提供商对比

| 提供商 | 模型 | 价格 | 速度 | 质量 |
|--------|------|------|------|------|
| OpenAI | GPT-3.5-turbo | 中等 | 快 | 优秀 |
| OpenAI | GPT-4 | 高 | 中等 | 最优 |
| Qwen | qwen-turbo | 低 | 快 | 良好 |
| Qwen | qwen-plus | 低 | 中等 | 优秀 |
| Claude | claude-3-sonnet | 中等 | 快 | 优秀 |
| Claude | claude-3-opus | 高 | 中等 | 最优 |

## 评分逻辑

系统向LLM提供以下信息进行评分：

1. **系统提示** - 告诉LLM它是教育评分专家
2. **题目内容** - 学生需要回答的问题
3. **参考答案** - 标准答案
4. **学生答案** - 学生提交的答案
5. **答案解析** - 可选的详细解析

LLM会综合考虑这些信息，评估：
- 答案的正确性
- 答案的完整性
- 答案的逻辑性
- 与参考答案的相似度

## 评分结果说明

### 是否正确 (is_correct)

- `true` - 答案正确
- `false` - 答案错误
- `null` - 不确定，需要人工审核

### 分数 (score)

- 0-100 的数值
- 反映答案的完整性和准确性

### 置信度 (confidence)

- 0-1 的小数
- 表示AI对评分的信心程度
- 0.9+ 表示非常有信心
- <0.5 表示低信心，建议人工审核

### 反馈 (feedback)

- 对学生的建议和改进意见
- 帮助学生理解错误之处

### 理由 (reasoning)

- AI的评分依据
- 解释为什么给出这个分数

## 成本估算

### OpenAI GPT-3.5-turbo

- 输入: $0.0005 / 1K tokens
- 输出: $0.0015 / 1K tokens
- 平均每次评分: $0.001-0.003
- 1000次评分成本: $1-3

### Qwen

- 价格更低，约为 OpenAI 的 1/3-1/2
- 1000次评分成本: $0.3-1.5

### Claude

- 价格介于两者之间
- 1000次评分成本: $0.5-2

## 故障排除

### 问题: "AI评分服务暂时不可用"

**检查清单**:
- [ ] `.env` 文件中是否配置了 `LLM_API_KEY`
- [ ] API 密钥是否正确
- [ ] 网络连接是否正常
- [ ] API 配额是否充足

**解决方案**:
```bash
# 1. 检查环境变量
echo $LLM_API_KEY

# 2. 查看服务器日志
tail -f logs/django.log

# 3. 运行测试脚本
python test_llm_grading.py
```

### 问题: "评分结果解析失败"

**原因**: LLM返回的响应格式不符合预期

**解决方案**:
1. 检查 LLM 模型是否支持
2. 尝试更换模型
3. 增加 `max_tokens` 值
4. 查看服务器日志获取详细错误

### 问题: 评分速度很慢

**原因**: 
- API 响应时间长
- 网络延迟
- 模型处理时间长

**解决方案**:
1. 尝试更换更快的模型（如 GPT-3.5-turbo）
2. 检查网络连接
3. 增加超时时间

### 问题: 评分结果不准确

**原因**:
- 题目或答案表述不清
- LLM 模型能力限制
- 参考答案不完整

**解决方案**:
1. 完善参考答案
2. 添加详细的答案解析
3. 尝试更强大的模型（如 GPT-4）
4. 人工审核低置信度的评分

## 安全建议

1. **不要在代码中硬编码 API 密钥**
   ```python
   # ❌ 错误
   api_key = "sk-xxx"
   
   # ✅ 正确
   api_key = os.environ.get('LLM_API_KEY')
   ```

2. **定期轮换 API 密钥**
   - 每月更换一次
   - 发现泄露立即更换

3. **监控 API 使用情况**
   - 设置使用配额
   - 监控异常消费

4. **在生产环境中使用 HTTPS**
   - 确保数据传输安全
   - 使用 SSL 证书

5. **定期审计日志**
   - 检查异常活动
   - 记录所有评分操作

## 日志

系统会记录所有 AI 评分操作。查看日志：

```bash
# 查看最近的日志
tail -f logs/django.log | grep "AI grading"

# 查看特定日期的日志
grep "2024-01-22" logs/django.log | grep "AI grading"
```

## 禁用 AI 评分

如果需要临时禁用 AI 评分功能：

```bash
# 方法1: 清空环境变量
unset LLM_API_KEY

# 方法2: 编辑 .env 文件
LLM_API_KEY=

# 方法3: 编辑 settings.py
LLM_CONFIG['api_key'] = ''
```

此时点击"AI评分建议"按钮会显示"未配置LLM API密钥"的提示。

## 高级用法

### 自定义评分提示词

编辑 `learning/llm_grading.py` 中的 `_build_grading_prompt()` 方法：

```python
def _build_grading_prompt(self, exercise_content, reference_answer, 
                         student_answer, exercise_solution):
    # 自定义提示词
    prompt = f"""
    你是一个专业的{subject}教师...
    """
    return prompt
```

### 调整评分参数

在 `settings.py` 中修改：

```python
LLM_CONFIG = {
    'temperature': 0.1,    # 更低 = 更稳定
    'max_tokens': 1000,    # 更长的输出
    'timeout': 60,         # 更长的超时
}
```

### 添加缓存

为避免重复评分相同的答案，可以添加缓存：

```python
from django.core.cache import cache

def grade_answer_cached(exercise_id, student_answer):
    cache_key = f"grade_{exercise_id}_{hash(student_answer)}"
    result = cache.get(cache_key)
    if result is None:
        result = grade_subjective_answer(...)
        cache.set(cache_key, result, 3600)  # 缓存1小时
    return result
```

## 常见问题

**Q: AI评分会替代人工批改吗？**  
A: 不会。AI评分仅作为参考建议，最终批改结果由教师决定。

**Q: 如何确保评分的准确性？**  
A: 
- 使用更强大的模型（如 GPT-4）
- 完善参考答案和解析
- 人工审核低置信度的评分
- 定期验证AI评分的准确性

**Q: 支持哪些语言？**  
A: 支持中文、英文等多种语言，具体取决于所选LLM模型。

**Q: 如何处理特殊题型？**  
A: 可以在参考答案和解析中提供详细说明，帮助LLM理解评分标准。

**Q: 可以离线使用吗？**  
A: 不可以，需要网络连接调用LLM API。

## 技术细节

### 请求流程

```
用户点击"AI评分建议"
    ↓
前端发送 POST 请求到 /learning/teacher/api/answer/<log_id>/ai-grade/
    ↓
后端 ai_grade_answer 视图处理请求
    ↓
调用 LLMGrader.grade_answer() 方法
    ↓
根据配置的提供商调用相应的 API
    ↓
解析 LLM 响应
    ↓
返回 JSON 结果给前端
    ↓
前端显示评分结果
```

### 数据流

```
Exercise (题目)
    ├── content (题目内容)
    ├── answer (参考答案)
    └── solution (答案解析)

AnswerLog (答题记录)
    ├── text_answer (学生答案)
    └── is_correct (批改结果)

LLMGrader (评分器)
    ├── grade_answer() (评分方法)
    └── _parse_grading_response() (结果解析)
```

## 贡献

如有改进建议或发现问题，欢迎提交 Issue 或 Pull Request。

## 许可证

本功能遵循项目的许可证。

## 支持

如有问题，请：

1. 查看本文档
2. 查看 `LLM_GRADING_SETUP.md`
3. 运行 `test_llm_grading.py` 测试
4. 查看服务器日志
5. 联系系统管理员
