import pandas as pd
import os
import re
import sys
import traceback
import io
import json

# === 依赖库检测 ===
try:
    import docx
except ImportError:
    print("【提示】缺少 python-docx，请运行: pip install python-docx")

try:
    import pdfplumber
except ImportError:
    print("【提示】缺少 pdfplumber，请运行: pip install pdfplumber")

try:
    import dashscope
    from dashscope import Generation

    # TODO: 请务必在这里填入您在阿里云申请的 API-KEY
    dashscope.api_key = "sk-0ddb7aa22f694638ab3c9e4386e7f1b3"
except ImportError:
    print("【提示】缺少 dashscope，请运行: pip install dashscope")

from django.utils import timezone
from django.db import transaction
from learning.models import Exercise, Choice, KnowledgePoint, QMatrix


# ==========================================
# 1. 核心解析函数 (原版)
# ==========================================
def parse_text_to_exercises(text):
    print(f"--- 开始解析文本，长度: {len(text)} ---")
    text = text.replace('\t', ' ')
    lines = text.split('\n')
    exercises = []

    current_exercise = None
    current_options = []

    pattern_question = re.compile(r'^(\d+[\.、\)]|【\d+】|Question\s*\d+)(.*)')
    pattern_option = re.compile(r'^(\(?\s*[A-D]\s*[\.、\)\s]?)(.*)', re.IGNORECASE)
    pattern_answer = re.compile(r'^(答案|Answer)[:：]\s*(.*)', re.IGNORECASE)
    pattern_kp = re.compile(r'^(知识点|考点|Knowledge)[:：]\s*(.*)', re.IGNORECASE)
    pattern_solution = re.compile(r'^(解析|Solution)[:：]\s*(.*)', re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line: continue
        if line.lower() == 'undefined': continue

        q_match = pattern_question.match(line)
        if q_match:
            if current_exercise:
                current_exercise['options'] = current_options
                if not current_exercise['answer']: current_exercise['answer'] = '略'
                exercises.append(current_exercise)

            current_exercise = {
                'title': q_match.group(2).strip(),
                'answer': '',
                'knowledge_point': '',
                'solution': '',
                'options': []
            }
            current_options = []
            continue

        opt_match = pattern_option.match(line)
        if current_exercise and opt_match:
            raw_label = opt_match.group(1)
            label = re.sub(r'[\(\)\.、\s\[\]]', '', raw_label).upper()
            content = opt_match.group(2).strip()

            if label in ['A', 'B', 'C', 'D'] and content:
                current_options.append({'label': label, 'content': content})
            continue

        ans_match = pattern_answer.match(line)
        if current_exercise and ans_match:
            current_exercise['answer'] = ans_match.group(2).strip().upper()
            continue

        kp_match = pattern_kp.match(line)
        if current_exercise and kp_match:
            current_exercise['knowledge_point'] = kp_match.group(2).strip()
            continue

        sol_match = pattern_solution.match(line)
        if current_exercise and sol_match:
            current_exercise['solution'] = sol_match.group(2).strip()
            continue

    if current_exercise:
        current_exercise['options'] = current_options
        if not current_exercise['answer']: current_exercise['answer'] = '略'
        exercises.append(current_exercise)

    print(f"--- 解析完成，共识别出 {len(exercises)} 道题 ---")
    return exercises


# ==========================================
# 2. 文档处理入口 (Word / PDF / TXT) - 维持原样
# ==========================================
def handle_document_file(file_record):
    print(">>> 进入 handle_document_file 函数 (修复对齐版)")
    subject = file_record.subject
    teacher = file_record.teacher
    filename = file_record.original_filename.lower()

    full_text = ""
    count = 0

    try:
        try:
            with file_record.file.open('rb') as f:
                file_content = f.read()
        except Exception:
            with open(file_record.file.path, 'rb') as f:
                file_content = f.read()

        if not file_content: return 0

        if filename.endswith('.pdf'):
            try:
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    full_text = "\n".join([page.extract_text() or '' for page in pdf.pages])
            except Exception as e:
                print(f"PDF 解析失败: {e}")
        elif filename.endswith('.docx'):
            try:
                docx_file = io.BytesIO(file_content)
                doc = docx.Document(docx_file)
                full_text = "\n".join([para.text.strip() for para in doc.paragraphs if para.text.strip()])
            except Exception as e:
                print(f"Word解析异常: {e}")
                try:
                    full_text = file_content.decode('utf-8')
                except:
                    full_text = file_content.decode('gbk', errors='ignore')
        else:
            try:
                full_text = file_content.decode('utf-8')
            except:
                try:
                    full_text = file_content.decode('gbk')
                except:
                    return 0

        if not full_text.strip(): return 0

        exercises_data = parse_text_to_exercises(full_text)

        with transaction.atomic():
            for item in exercises_data:
                try:
                    q_type = 'single'
                    if not item['options']:
                        q_type = 'subjective'
                    elif len(item['answer']) > 1:
                        q_type = 'multiple'

                    opt_dict = {opt['label']: opt['content'] for opt in item['options']}
                    full_option_text = repr(opt_dict) if opt_dict else ""

                    exercise = Exercise.objects.create(
                        subject=subject,
                        title=item['title'][:50],
                        content=item['title'].replace('undefined', '').strip(),
                        question_type=q_type,
                        creator=teacher,
                        option_text=full_option_text,
                        answer=item['answer'],
                        solution=item.get('solution', ''),
                        problemsets="文件导入",
                        created_at=timezone.now()
                    )

                    for idx, opt in enumerate(item['options']):
                        labeled_content = f"{opt['label']}. {opt['content']}"
                        Choice.objects.create(
                            exercise=exercise,
                            content=labeled_content,
                            is_correct=(opt['label'] in item['answer']),
                            order=idx + 1
                        )

                    kp_str = item.get('knowledge_point', '')
                    if not kp_str: kp_str = "导入知识点"
                    kp_list = re.split(r'[，,、\s]+', kp_str)
                    for kp_name in kp_list:
                        if not kp_name: continue
                        kp, _ = KnowledgePoint.objects.get_or_create(subject=subject, name=kp_name,
                                                                     defaults={'parent': None})
                        QMatrix.objects.get_or_create(exercise=exercise, knowledge_point=kp, defaults={'weight': 1.0})
                    count += 1
                except Exception as e:
                    print(f"保存单条习题出错: {e}")
                    continue
    except Exception as e:
        print(f"【处理报错】: {e}")
        traceback.print_exc()
    finally:
        try:
            file_record.file.close()
        except:
            pass
    return count


# ==========================================
# 3. Excel/CSV 处理入口 - 维持原样
# ==========================================
def handle_data_file(file_record):
    count = 0
    file_path = file_record.file.path
    subject = file_record.subject
    teacher = file_record.teacher

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, encoding='utf-8-sig')
        else:
            df = pd.read_excel(file_path)

        with transaction.atomic():
            for _, row in df.iterrows():
                title = str(row.get('题目') or row.iloc[0]).strip()
                if len(title) < 2 or title == 'nan': continue

                def get_val(key, idx):
                    val = row.get(key)
                    if pd.isna(val): val = row.iloc[idx] if idx < len(row) else ''
                    return str(val).strip()

                opt_dict = {}
                for label, idx in [('A', 1), ('B', 2), ('C', 3), ('D', 4)]:
                    txt = get_val(f'选项{label}', idx)
                    if txt and txt != 'nan': opt_dict[label] = txt

                ans = str(row.get('答案') or 'A').strip().upper()

                exercise = Exercise.objects.create(
                    subject=subject,
                    title=title[:50],
                    content=title.replace('undefined', '').strip(),
                    question_type='single' if len(ans) == 1 else 'multiple',
                    creator=teacher,
                    option_text=repr(opt_dict),
                    answer=ans,
                    problemsets="Excel导入",
                    created_at=timezone.now()
                )

                for idx, (label, txt) in enumerate(opt_dict.items()):
                    Choice.objects.create(
                        exercise=exercise,
                        content=f"{label}. {txt}",
                        is_correct=(label in ans),
                        order=idx + 1
                    )
                count += 1
    except Exception as e:
        print(f"【Excel处理报错】: {e}")
        traceback.print_exc()
    return count


# ==========================================
# 4. AI 基于资料自动生成习题与知识点 (新增)
# ==========================================
def auto_generate_exercises_from_text(text):
    """
    调用通义千问，让它阅读资料并自动出题
    """
    print(">>> 开始调用通义千问基于资料自动生成习题...")

    # 截取前 4000 字（大模型阅读材料的范围，防止 Token 超限）
    content = text[:4000]

    # 专门针对计算机科学类的出题 Prompt
    prompt = f"""
    你是一个专业的计算机科学大学教师。请阅读以下教学资料，并根据资料中的核心内容，生成 3 道高质量的单选题。
    要求：
    1. 题目要有针对性，选项要有迷惑性。
    2. 为每道题提取 1-2 个核心知识点短语。
    3. 必须且只能返回一个纯 JSON 数组格式，不要包含任何前缀、后缀或 Markdown 代码块标记（如```json）。

    返回的 JSON 必须严格遵守以下格式示例：
    [
        {{
            "title": "MVC设计模式中，负责处理业务逻辑和数据库交互的是哪一部分？",
            "options": {{
                "A": "Model (模型)",
                "B": "View (视图)",
                "C": "Controller (控制器)",
                "D": "Template (模板)"
            }},
            "answer": "A",
            "solution": "在MVC架构中，Model负责数据的封装和业务逻辑处理。",
            "knowledge_points": ["MVC架构", "后端开发基础"]
        }}
    ]

    请根据以下资料内容出题：
    {content}
    """

    try:
        response = Generation.call(
            model="qwen-turbo",
            prompt=prompt,
            result_format='message'
        )

        if response.status_code == 200:
            result_text = response.output.choices[0].message.content.strip()

            # 清洗并解析 JSON
            clean_json = result_text.replace('```json', '').replace('```', '').strip()
            exercise_list = json.loads(clean_json)

            return exercise_list if isinstance(exercise_list, list) else []
        else:
            print(f"大模型调用失败: {response.code} - {response.message}")
            return []
    except Exception as e:
        print(f"AI 生成习题解析异常: {e}")
        return []


# ==========================================
# 5. 资料处理入口 (提取文字 -> AI出题 -> 存入题库) (新增)
# ==========================================
def handle_material_generation(file_record):
    """
    读取上传的资料，调用 AI 出题，并将题目和知识点无缝存入现有的数据库
    需要传入的文件记录对象应包含: file, original_filename, subject, teacher
    """
    print(">>> 进入 handle_material_generation 函数")
    subject = file_record.subject
    # 兼容处理：如果你传入的模型没有 teacher 字段，可以默认给个 1 或者从 request 取
    teacher = getattr(file_record, 'teacher', getattr(file_record, 'uploader', None))
    filename = file_record.original_filename.lower()
    full_text = ""

    # 1. 提取资料文本 (复用稳健的读取逻辑)
    try:
        try:
            with file_record.file.open('rb') as f:
                file_content = f.read()
        except Exception:
            with open(file_record.file.path, 'rb') as f:
                file_content = f.read()

        if not file_content: return 0

        if filename.endswith('.pdf'):
            try:
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    full_text = "\n".join([page.extract_text() or '' for page in pdf.pages])
            except Exception as e:
                print(f"资料 PDF 解析失败: {e}")
        elif filename.endswith('.docx'):
            try:
                docx_file = io.BytesIO(file_content)
                doc = docx.Document(docx_file)
                full_text = "\n".join([para.text.strip() for para in doc.paragraphs if para.text.strip()])
            except Exception as e:
                print(f"资料 Word 解析异常: {e}")
                try:
                    full_text = file_content.decode('utf-8')
                except:
                    full_text = file_content.decode('gbk', errors='ignore')
        else:
            try:
                full_text = file_content.decode('utf-8')
            except:
                try:
                    full_text = file_content.decode('gbk')
                except:
                    return 0

        if not full_text.strip(): return 0

        # 2. 召唤 AI 自动出题
        generated_exercises = auto_generate_exercises_from_text(full_text)
        print(f"--- AI 成功生成了 {len(generated_exercises)} 道题 ---")

        count = 0
        with transaction.atomic():
            for item in generated_exercises:
                try:
                    # 3. 兼容前端：将生成的 options 字典直接转为 repr 字符串
                    opt_dict = item.get('options', {})
                    full_option_text = repr(opt_dict) if opt_dict else ""

                    # 4. 创建习题 (存入现有的 Exercise 表)
                    exercise = Exercise.objects.create(
                        subject=subject,
                        title=item.get('title', '')[:200],
                        content=item.get('title', ''),
                        question_type='single',
                        creator_id=teacher.id if teacher else 1,  # 容错处理
                        option_text=full_option_text,
                        answer=item.get('answer', 'A'),
                        solution=item.get('solution', ''),
                        problemsets="AI智能生成",  # 标记这是AI生成的题
                        created_at=timezone.now()
                    )

                    # 5. 创建选项 (存入现有的 Choice 表)
                    for idx, (label, content) in enumerate(opt_dict.items()):
                        Choice.objects.create(
                            exercise=exercise,
                            content=f"{label}. {content}",
                            is_correct=(label == item.get('answer')),
                            order=idx + 1
                        )

                    # 6. 处理知识点及 Q矩阵
                    kps = item.get('knowledge_points', [])
                    for kp_name in kps:
                        if not kp_name.strip(): continue
                        # 检查是否有这个知识点，没有就新建
                        kp, _ = KnowledgePoint.objects.get_or_create(
                            subject=subject,
                            name=kp_name.strip(),
                            defaults={'parent': None}
                        )
                        # 将这道 AI 生成的题与该知识点关联起来
                        QMatrix.objects.get_or_create(exercise=exercise, knowledge_point=kp, defaults={'weight': 1.0})

                    count += 1
                except Exception as e:
                    print(f"保存单条 AI 生成习题出错: {e}")
                    continue

        return count

    except Exception as e:
        print(f"处理资料出题出错: {e}")
        traceback.print_exc()
        return 0