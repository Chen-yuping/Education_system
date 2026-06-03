"""
迁移脚本：将已有填空题中的空白占位符替换为 [填空N] 标记
用法: python migrate_fill_blanks.py
"""
import os, sys, re, json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from learning.utils_ai import parse_fill_in_blanks
from learning.models import Exercise

fills = Exercise.objects.filter(question_type='4')
total = fills.count()
fixed = 0
skipped = 0
errors = 0

for e in fills.iterator():
    try:
        content = e.content or ''
        # 跳过已有 [填空N] 标记的
        if re.search(r'\[填空\d+\]', content):
            skipped += 1
            continue

        # 检查是否有原始占位符
        has_blank = bool(re.search(r'_{2,}|[（(]\s*[）)]', content))
        if not has_blank:
            skipped += 1
            continue

        # 解析答案
        answer_text = e.answer
        try:
            # 如果答案已经是 JSON，尝试提取文本值用于分割
            parsed = json.loads(answer_text)
            if isinstance(parsed, dict):
                values = []
                for k in sorted(parsed.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                    v = parsed[k]
                    if isinstance(v, list) and v:
                        values.append(v[0])
                    elif isinstance(v, str):
                        values.append(v)
                answer_text = '，'.join(values)
        except (json.JSONDecodeError, TypeError):
            pass  # 保持原文本

        processed_content, blank_count, blank_answers_json = parse_fill_in_blanks(content, answer_text if answer_text not in ('', '略') else None)

        if blank_count > 0:
            e.content = processed_content
            if blank_answers_json != '{}':
                e.answer = blank_answers_json
            e.save(update_fields=['content', 'answer'])
            fixed += 1
            print(f'  [OK] ID={e.id}: {blank_count}个空 -> {processed_content[:60]}...')
        else:
            skipped += 1

    except Exception as ex:
        errors += 1
        print(f'  [ERR] ID={e.id}: {ex}')

print(f'\n完成! 总数: {total}, 已修复: {fixed}, 已跳过: {skipped}, 错误: {errors}')
