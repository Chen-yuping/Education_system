# 导出指定科目的训练数据


import os
import json
import csv
from django.db.models import Q
from collections import defaultdict
from ..models import AnswerLog, QMatrix, KnowledgePoint, Exercise, User


def export_training_data(subject_id):
    """
    导出指定科目的训练数据

    Args:
        subject_id: 科目ID

    Returns:
        dict: 包含导出统计信息
    """
    # 1. 创建目录
    base_dir = os.path.join(os.path.dirname(__file__), 'data', str(subject_id))
    os.makedirs(base_dir, exist_ok=True)

    # 2. 获取该科目下所有有答题记录的学生
    students_with_logs = User.objects.filter(
        id__in=AnswerLog.objects.filter(
            exercise__subject_id=subject_id,
            is_correct__isnull=False
        ).values_list('student_id', flat=True).distinct(),
        user_type='student'
    )

    # 3. 获取该科目下所有习题
    exercises = Exercise.objects.filter(subject_id=subject_id)

    # 4. 获取该科目下所有知识点
    knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)

    # 5. 构建映射
    user_mapping = {}  # 新id -> 原id
    exer_mapping = {}  # 新id -> 原id
    kp_mapping = {}  # 新id -> 原id

    for idx, user in enumerate(students_with_logs, start=1):
        user_mapping[idx] = user.id

    for idx, exer in enumerate(exercises, start=1):
        exer_mapping[idx] = exer.id

    for idx, kp in enumerate(knowledge_points, start=1):
        kp_mapping[idx] = kp.id

    # 反向映射（原id -> 新id）
    user_reverse = {v: k for k, v in user_mapping.items()}
    exer_reverse = {v: k for k, v in exer_mapping.items()}
    kp_reverse = {v: k for k, v in kp_mapping.items()}

    # 6. 构建习题->知识点列表的映射（新ID）
    exer_to_kps = defaultdict(list)
    qmatrices = QMatrix.objects.filter(
        exercise__subject_id=subject_id
    ).values_list('exercise_id', 'knowledge_point_id')

    for exer_id, kp_id in qmatrices:
        new_exer_id = exer_reverse.get(exer_id)
        new_kp_id = kp_reverse.get(kp_id)
        if new_exer_id and new_kp_id:
            exer_to_kps[new_exer_id].append(new_kp_id)

    # 7. 获取所有答题记录，按学生分组
    answer_logs = AnswerLog.objects.filter(
        exercise__subject_id=subject_id,
        is_correct__isnull=False
    ).select_related('exercise').order_by('student_id', 'submitted_at')

    # 按学生分组，保存记录
    student_records = defaultdict(list)
    for log in answer_logs:
        new_student_id = user_reverse.get(log.student_id)
        new_exer_id = exer_reverse.get(log.exercise_id)

        if new_student_id and new_exer_id:
            student_records[new_student_id].append({
                'exer_id': new_exer_id,
                'score': 1 if log.is_correct else 0,
                'knowledge_code': exer_to_kps.get(new_exer_id, [])
            })

    # 8. 按学生8:2拆分
    train_data = []  # 扁平结构
    val_data = []  # 按学生聚合

    for student_id, records in student_records.items():
        n = len(records)
        split_idx = int(n * 0.8)

        # 前80%放入训练集
        for record in records[:split_idx]:
            train_data.append({
                'user_id': student_id,
                'exer_id': record['exer_id'],
                'score': record['score'],
                'knowledge_code': record['knowledge_code']
            })

        # 后20%也放入验证集（扁平结构，不聚合）
        for record in records[split_idx:]:
            val_data.append({
                'user_id': student_id,
                'exer_id': record['exer_id'],
                'score': record['score'],
                'knowledge_code': record['knowledge_code']
            })

    # 9. 保存文件
    # 保存 config.txt
    config_path = os.path.join(base_dir, 'config.txt')
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write("# Number of Students, Number of Exercises, Number of Knowledge Concepts\n")
        f.write(f"{len(user_mapping)}, {len(exer_mapping)}, {len(kp_mapping)}")

    # 保存 train.json
    train_path = os.path.join(base_dir, 'train.json')
    with open(train_path, 'w', encoding='utf-8') as f:
        json.dump(train_data, f, indent=2, ensure_ascii=False)

    # 保存 val.json
    val_path = os.path.join(base_dir, 'val.json')
    with open(val_path, 'w', encoding='utf-8') as f:
        json.dump(val_data, f, indent=2, ensure_ascii=False)

    # 保存 log_data.json（所有记录，不拆分）
    log_data_path = os.path.join(base_dir, 'log_data.json')
    all_records = []
    for student_id, records in student_records.items():
        for record in records:
            all_records.append({
                'user_id': student_id,
                'exer_id': record['exer_id'],
                'score': record['score'],
                'knowledge_code': record['knowledge_code']
            })

    with open(log_data_path, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    # 保存 homologous.csv（映射表）
    csv_path = os.path.join(base_dir, 'homologous.csv')
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        # 写入表头
        writer.writerow(['new_user_id', 'original_user_id',
                         'new_exer_id', 'original_exer_id',
                         'new_knowledge_code', 'original_knowledge_code'])

        # 获取最大长度用于对齐
        max_len = max(len(user_mapping), len(exer_mapping), len(kp_mapping))

        for i in range(1, max_len + 1):
            new_user = i if i <= len(user_mapping) else ''
            orig_user = user_mapping.get(i, '')
            new_exer = i if i <= len(exer_mapping) else ''
            orig_exer = exer_mapping.get(i, '')
            new_kp = i if i <= len(kp_mapping) else ''
            orig_kp = kp_mapping.get(i, '')
            writer.writerow([new_user, orig_user, new_exer, orig_exer, new_kp, orig_kp])

    return {
        'success': True,
        'data_dir': base_dir,
        'student_count': len(user_mapping),
        'exercise_count': len(exer_mapping),
        'knowledge_count': len(kp_mapping),
        'train_count': len(train_data),
        'val_count': len(val_data)
    }