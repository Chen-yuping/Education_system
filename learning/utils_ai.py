import pandas as pd
import os
import re
import sys
import traceback
import io

# === 依赖库检测 ===
try:
    import docx
except ImportError:
    print("【提示】缺少 python-docx，请运行: pip install python-docx")

try:
    import pdfplumber
except ImportError:
    print("【提示】缺少 pdfplumber，请运行: pip install pdfplumber")

from django.utils import timezone
from django.db import transaction
from learning.models import Exercise, Choice, KnowledgePoint, QMatrix


# ==========================================
# 1. 核心解析函数
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
# 2. 文档处理入口 (Word / PDF / TXT)
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
                # 增强：使用 io.BytesIO 包裹
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

                    # --- 修改点 1：核心适配 HTML 的解析逻辑 ---
                    # 构建字典字符串，触发 HTML 第 455 行的 startsWith('{') 逻辑
                    opt_dict = {opt['label']: opt['content'] for opt in item['options']}
                    full_option_text = repr(opt_dict) if opt_dict else ""

                    exercise = Exercise.objects.create(
                        subject=subject,
                        title=item['title'][:50],
                        # --- 修改点 2：彻底清除题目末尾的 undefined ---
                        content=item['title'].replace('undefined', '').strip(),
                        question_type=q_type,
                        creator=teacher,
                        option_text=full_option_text,  # 存入全量字典格式字符串
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
# 3. Excel/CSV 处理入口
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

                # 获取 Excel 选项
                opt_dict = {}
                for label, idx in [('A', 1), ('B', 2), ('C', 3), ('D', 4)]:
                    txt = get_val(f'选项{label}', idx)
                    if txt and txt != 'nan': opt_dict[label] = txt

                ans = str(row.get('答案') or 'A').strip().upper()

                # 同样同步 option_text 为字典格式
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
