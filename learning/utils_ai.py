import pandas as pd
import os
import re
import sys
import traceback
import io
import zipfile

# === 依赖库检测 ===
try:
    import docx
except ImportError:
    print("【提示】缺少 python-docx，请运行: pip install python-docx")

try:
    import pdfplumber  # <--- 新增 PDF 支持
except ImportError:
    print("【提示】缺少 pdfplumber，请运行: pip install pdfplumber")

from django.utils import timezone
from learning.models import Exercise, Choice, KnowledgePoint, QMatrix


# ==========================================
# 1. 核心解析函数 (通用逻辑)
# ==========================================
def parse_text_to_exercises(text):
    print(f"--- 开始解析文本，长度: {len(text)} ---")
    lines = text.split('\n')
    exercises = []

    current_exercise = None
    current_options = []

    # 正则规则
    pattern_question = re.compile(r'^(\d+[\.、\)]|【\d+】|Question\s*\d+)(.*)')
    pattern_option = re.compile(r'^([A-D])[\.、\)](.*)')
    pattern_answer = re.compile(r'^(答案|Answer)[:：]\s*(.*)', re.IGNORECASE)
    pattern_kp = re.compile(r'^(知识点|考点|Knowledge)[:：]\s*(.*)', re.IGNORECASE)
    pattern_solution = re.compile(r'^(解析|Solution)[:：]\s*(.*)', re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line: continue

        # 识别题目
        q_match = pattern_question.match(line)
        if q_match:
            if current_exercise:
                current_exercise['options'] = current_options
                if not current_exercise['answer']: current_exercise['answer'] = '略'
                exercises.append(current_exercise)

            current_exercise = {
                'title': q_match.group(2).strip(),
                'answer': '', 'knowledge_point': '', 'solution': '', 'options': []
            }
            current_options = []
            continue

        # 识别选项
        opt_match = pattern_option.match(line)
        if current_exercise and opt_match:
            current_options.append({'label': opt_match.group(1).upper(), 'content': opt_match.group(2).strip()})
            continue

        # 识别答案
        ans_match = pattern_answer.match(line)
        if current_exercise and ans_match:
            current_exercise['answer'] = ans_match.group(2).strip().upper()
            continue

        # 识别知识点
        kp_match = pattern_kp.match(line)
        if current_exercise and kp_match:
            current_exercise['knowledge_point'] = kp_match.group(2).strip()
            continue

        # 识别解析
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
# 2. 文档处理入口 (支持 Word / PDF / TXT)
# ==========================================
def handle_document_file(file_record):
    print(">>> 进入 handle_document_file 函数 (全能版)")
    subject = file_record.subject
    teacher = file_record.teacher
    filename = file_record.original_filename.lower()

    full_text = ""
    count = 0

    try:
        # A. 读取文件内容到内存
        try:
            with file_record.file.open('rb') as f:
                file_content = f.read()
        except Exception as e:
            # 备用：路径读取
            with open(file_record.file.path, 'rb') as f:
                file_content = f.read()

        if not file_content:
            print("错误：文件内容为空")
            return 0

        # === 分支 1：处理 PDF ===
        if filename.endswith('.pdf'):
            print("正在尝试解析 PDF ...")
            try:
                # 使用 pdfplumber 读取内存中的 PDF
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    text_pages = []
                    for page in pdf.pages:
                        # 提取每一页的文字
                        page_text = page.extract_text()
                        if page_text:
                            text_pages.append(page_text)
                    full_text = "\n".join(text_pages)
                print(">>> PDF 解析成功！")
            except Exception as e:
                print(f"PDF 解析失败: {e}")
                traceback.print_exc()

        # === 分支 2：处理 Word (.docx) ===
        elif filename.endswith('.docx'):
            print("正在尝试解析 Word ...")
            try:
                docx_file = io.BytesIO(file_content)
                doc = docx.Document(docx_file)
                full_text = "\n".join([para.text.strip() for para in doc.paragraphs if para.text.strip()])
                print(">>> Word 解析成功！")
            except Exception as e:
                print(f"Word解析异常，尝试纯文本模式: {e}")
                # 容错：如果是伪装成docx的txt
                try:
                    full_text = file_content.decode('utf-8')
                except:
                    full_text = file_content.decode('gbk', errors='ignore')

        # === 分支 3：处理 TXT ===
        else:
            print("正在尝试解析 TXT ...")
            try:
                full_text = file_content.decode('utf-8')
            except:
                try:
                    full_text = file_content.decode('gbk')
                except:
                    print("文本编码无法识别")
                    return 0

        if not full_text.strip():
            print("警告：提取的文本为空")
            return 0

        # --- B. 调用解析逻辑 ---
        exercises_data = parse_text_to_exercises(full_text)

        if not exercises_data:
            print("警告：未识别出习题，请检查题目格式（需以 '1.' 开头）")

        # --- C. 写入数据库 ---
        for item in exercises_data:
            q_type = 'single'
            if not item['options']:
                q_type = 'subjective'
            elif len(item['answer']) > 1:
                q_type = 'multiple'

            full_option_text = ""
            for opt in item['options']:
                full_option_text += f"{opt['label']}.{opt['content']} "

            exercise = Exercise.objects.create(
                subject=subject,
                title=item['title'][:50],
                content=item['title'],
                question_type=q_type,
                creator=teacher,
                option_text=full_option_text,
                answer=item['answer'],
                solution=item.get('solution', ''),
                problemsets="文件导入",
                created_at=timezone.now()
            )

            for idx, opt in enumerate(item['options']):
                Choice.objects.create(
                    exercise=exercise,
                    content=opt['content'],
                    is_correct=(opt['label'] in item['answer']),
                    order=idx + 1
                )

            kp_str = item.get('knowledge_point', '')
            if not kp_str: kp_str = "导入知识点"

            kp_list = re.split(r'[，,、\s]+', kp_str)
            for kp_name in kp_list:
                if not kp_name: continue
                kp, _ = KnowledgePoint.objects.get_or_create(subject=subject, name=kp_name, defaults={'parent': None})
                QMatrix.objects.get_or_create(exercise=exercise, knowledge_point=kp, defaults={'weight': 1.0})

            count += 1

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
# 3. Excel/CSV 处理入口 (保持不变)
# ==========================================
def handle_data_file(file_record):
    # ... (Excel 部分代码保持原样，为了节省篇幅这里省略，您保留原来的即可) ...
    # 如果您原来的 Excel 代码没了，请告诉我，我再发一遍完整的
    count = 0
    file_path = file_record.file.path
    subject = file_record.subject
    teacher = file_record.teacher

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, encoding='utf-8-sig')
        else:
            df = pd.read_excel(file_path)

        for _, row in df.iterrows():
            title = str(row.get('题目') or row.iloc[0]).strip()
            if len(title) < 2 or title == 'nan': continue

            def get_val(key, idx):
                val = row.get(key)
                if pd.isna(val):
                    val = row.iloc[idx] if idx < len(row) else ''
                return str(val).strip()

            op_a = get_val('选项A', 1)
            op_b = get_val('选项B', 2)
            op_c = get_val('选项C', 3)
            op_d = get_val('选项D', 4)
            ans = str(row.get('答案') or 'A').strip().upper()

            kp_raw = str(row.get('知识点') or '综合知识点').strip()
            if kp_raw == 'nan' or not kp_raw: kp_raw = '综合知识点'
            kp_names = re.split(r'[，,、\s]+', kp_raw)

            full_option_text = f"A.{op_a} B.{op_b} C.{op_c} D.{op_d}"

            q_type = 'single'
            if len(ans) > 1: q_type = 'multiple'

            exercise = Exercise.objects.create(
                subject=subject,
                title=title[:50],
                content=title,
                question_type=q_type,
                creator=teacher,
                option_text=full_option_text,
                answer=ans,
                problemsets="Excel导入",
                created_at=timezone.now()
            )

            choices_list = [(op_a, 'A'), (op_b, 'B'), (op_c, 'C'), (op_d, 'D')]
            for idx, (txt, label) in enumerate(choices_list):
                if txt:
                    Choice.objects.create(
                        exercise=exercise,
                        content=txt,
                        is_correct=(label in ans),
                        order=idx + 1
                    )

            for name in kp_names:
                if not name: continue
                kp, _ = KnowledgePoint.objects.get_or_create(subject=subject, name=name, defaults={'parent': None})
                QMatrix.objects.get_or_create(exercise=exercise, knowledge_point=kp, defaults={'weight': 1.0})

            count += 1

    except Exception as e:
        print(f"【Excel处理报错】: {e}")
        traceback.print_exc()

    return count