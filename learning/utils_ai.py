import pandas as pd
import os
from django.utils import timezone
# 引入所有需要的模型
from learning.models import Exercise, Choice, KnowledgePoint, QMatrix


def handle_data_file(file_record):
    """
    处理结构化数据 (Excel/CSV)：精准入库
    """
    count = 0
    file_path = file_record.file.path
    subject = file_record.subject
    teacher = file_record.teacher

    try:
        # 1. 读取文件
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, encoding='utf-8-sig')
        else:
            df = pd.read_excel(file_path)

        for _, row in df.iterrows():
            # 基础校验
            title = str(row.get('题目') or row.iloc[0])
            if len(title) < 2: continue

            # 获取选项和答案
            op_a = str(row.get('选项A') or row.iloc[1])
            op_b = str(row.get('选项B') or row.iloc[2])
            op_c = str(row.get('选项C') or row.iloc[3])
            op_d = str(row.get('选项D') or row.iloc[4])
            ans = str(row.get('答案') or 'A').strip().upper()

            # 获取知识点
            kp_name = str(row.get('知识点') or '综合知识点').strip()

            full_option_text = f"A.{op_a} B.{op_b} C.{op_c} D.{op_d}"

            # 2. 创建习题
            exercise = Exercise.objects.create(
                subject=subject,
                title=title,
                content=title,
                question_type='single',
                creator=teacher,
                option_text=full_option_text,
                answer=ans,
                problemsets="Excel导入",
                created_at=timezone.now()
            )

            # 3. 创建选项
            choices_list = [(op_a, 'A'), (op_b, 'B'), (op_c, 'C'), (op_d, 'D')]
            for idx, (txt, label) in enumerate(choices_list):
                Choice.objects.create(
                    exercise=exercise,
                    content=txt,
                    is_correct=(label == ans),
                    order=idx + 1
                )

            # 4. 处理知识点 (不存在则创建)
            kp, _ = KnowledgePoint.objects.get_or_create(
                subject=subject,
                name=kp_name,
                defaults={'parent': None}
            )

            # 5. 建立 QMatrix 关联
            QMatrix.objects.create(
                exercise=exercise,
                knowledge_point=kp,
                weight=1.0
            )

            count += 1

    except Exception as e:
        print(f"数据文件处理出错: {e}")

    return count


def handle_document_file(file_record):
    """
    处理文档 (PDF/Word/TXT)：Mock AI 生成 + 自动关联
    """
    subject = file_record.subject
    teacher = file_record.teacher
    filename = file_record.original_filename
    file_path = file_record.file.path

    # === TXT 特殊处理：读取前20个字 ===
    content_preview = ""
    if filename.lower().endswith('.txt'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content_preview = f.read(20).strip()
        except:
            content_preview = "文本内容"

    # 根据文件类型生成不同的题目文案
    if content_preview:
        topic_base = f"（AI分析TXT）关于“{content_preview}...”的理解"
    else:
        topic_base = f"（AI生成-{filename}）核心概念是？"

    # 演示数据
    mock_data = [
        (topic_base, "概念A", "概念B", "概念C", "概念D", "A"),
        (f"（AI生成-{filename}）文中提到的关键数据是？", "10%", "20%", "30%", "40%", "B"),
        (f"（AI生成-{filename}）作者的观点倾向于？", "支持", "反对", "中立", "无关", "C"),
    ]

    # 创建一个默认知识点
    kp, _ = KnowledgePoint.objects.get_or_create(
        subject=subject,
        name="AI自动提取知识点"
    )

    count = 0
    for item in mock_data:
        # 1. 创建习题
        full_option_text = f"A.{item[1]} B.{item[2]} C.{item[3]} D.{item[4]}"
        exercise = Exercise.objects.create(
            subject=subject,
            title=item[0],
            content=item[0],
            question_type='single',
            creator=teacher,
            option_text=full_option_text,
            answer=item[5],
            problemsets="AI智能生成",
            created_at=timezone.now()
        )

        # 2. 创建选项
        options = [item[1], item[2], item[3], item[4]]
        labels = ['A', 'B', 'C', 'D']
        for idx, op_text in enumerate(options):
            Choice.objects.create(
                exercise=exercise,
                content=op_text,
                is_correct=(labels[idx] == item[5]),
                order=idx + 1
            )

        # 3. 关联知识点 (QMatrix)
        QMatrix.objects.create(
            exercise=exercise,
            knowledge_point=kp,
            weight=1.0
        )

        count += 1
    return count