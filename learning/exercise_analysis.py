"""做题记录实时分析模块

为学生分析做题记录中的错题原因，并推荐学习计划：
- 规则分析：基于做题记录统计薄弱知识点、易错题型、难度分布、答题用时与近期趋势
- AI 分析：调用 DeepSeek（OpenAI 兼容接口）生成错因诊断与个性化学习计划
"""
import json
from collections import defaultdict
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .models import AnswerLog

QUESTION_TYPE_MAP = {
    '1': '单选题',
    '2': '多选题',
    '3': '投票题',
    '4': '填空题',
    '5': '简答题',
    '6': '判断题',
    'single': '单选题',
    'multiple': '多选题',
    'fill': '填空题',
    'subjective': '简答题',
    'judgment': '判断题',
}


def difficulty_from_score(score):
    """根据分值判断难度（与做题记录页面保持一致）"""
    try:
        value = float(score or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 1:
        return '简单'
    if value <= 2:
        return '中等'
    return '困难'


def _student_answer_text(log, exercise):
    """获取学生的作答文本（用于展示/AI分析）"""
    if exercise.question_type in ['4', '5', 'fill', 'subjective'] or log.text_answer:
        raw = log.text_answer or ''
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return raw or '未作答'
        if isinstance(parsed, dict):
            return '；'.join(str(v) for v in parsed.values()) if parsed else '未作答'
        if isinstance(parsed, list):
            return '、'.join(str(v) for v in parsed) if parsed else '未作答'
        return str(parsed)

    choices = list(exercise.choices.all().order_by('order', 'id'))
    letters = {choice.id: chr(65 + index) for index, choice in enumerate(choices)}
    selected = [letters.get(c.id, c.content) for c in log.selected_choices.all()]
    return ''.join(selected) if selected else '未作答'


def _correct_answer_text(exercise):
    """获取题目的正确答案文本（用于展示/AI分析）"""
    if exercise.question_type in ['4', '5', 'fill', 'subjective']:
        raw = exercise.answer or ''
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return raw or '未设置'
        if isinstance(parsed, dict):
            return '；'.join(str(v) for v in parsed.values()) if parsed else '未设置'
        if isinstance(parsed, list):
            return '、'.join(str(v) for v in parsed) if parsed else '未设置'
        return str(parsed)

    choices = list(exercise.choices.all().order_by('order', 'id'))
    letters = {choice.id: chr(65 + index) for index, choice in enumerate(choices)}
    correct = [letters.get(c.id, c.content) for c in choices if c.is_correct]
    return ''.join(correct) if correct else (exercise.answer or '未设置')


def build_snapshot(subject, student, limit=60):
    """构建学生在某课程下的做题记录摘要，用于规则分析或 AI 分析"""
    logs = list(
        AnswerLog.objects.filter(student=student, subject=subject)
        .select_related('exercise')
        .prefetch_related('exercise__qmatrix_set__knowledge_point', 'selected_choices')
        .order_by('-submitted_at')[:limit]
    )

    total = len(logs)
    correct = sum(1 for log in logs if log.is_correct is True)
    wrong = sum(1 for log in logs if log.is_correct is False)
    unmarked = total - correct - wrong

    kp_wrong = defaultdict(int)
    kp_total = defaultdict(int)
    type_stats = defaultdict(lambda: {'total': 0, 'wrong': 0})
    diff_stats = defaultdict(lambda: {'total': 0, 'wrong': 0})
    time_spent_list = []
    active_days = set()
    recent_wrong = []

    for log in logs:
        exercise = log.exercise
        qtype = QUESTION_TYPE_MAP.get(exercise.question_type, exercise.question_type or '其他')
        diff = difficulty_from_score(exercise.score)

        type_stats[qtype]['total'] += 1
        diff_stats[diff]['total'] += 1
        if log.time_spent:
            time_spent_list.append(log.time_spent)
        if log.submitted_at:
            active_days.add(log.submitted_at.strftime('%Y-%m-%d'))

        if log.is_correct is False:
            type_stats[qtype]['wrong'] += 1
            diff_stats[diff]['wrong'] += 1
            if len(recent_wrong) < 10:
                kps = [
                    qm.knowledge_point.name
                    for qm in exercise.qmatrix_set.all()
                    if qm.knowledge_point
                ]
                recent_wrong.append({
                    '题目': (exercise.content or '')[:120],
                    '知识点': kps,
                    '题型': qtype,
                    '难度': diff,
                    '我的答案': _student_answer_text(log, exercise),
                    '正确答案': _correct_answer_text(exercise),
                    '解析': (exercise.solution or '')[:200],
                    '提交时间': log.submitted_at.strftime('%Y-%m-%d %H:%M') if log.submitted_at else '',
                })

        for qm in exercise.qmatrix_set.all():
            kp_name = qm.knowledge_point.name if qm.knowledge_point else '未关联知识点'
            kp_total[kp_name] += 1
            if log.is_correct is False:
                kp_wrong[kp_name] += 1

    weak_points = sorted(
        ({'name': kp, 'total': kp_total[kp], 'wrong': kp_wrong[kp]} for kp in kp_total),
        key=lambda x: x['wrong'],
        reverse=True,
    )[:10]

    wrong_types = sorted(
        ({'name': name, 'total': stats['total'], 'wrong': stats['wrong']} for name, stats in type_stats.items()),
        key=lambda x: x['wrong'],
        reverse=True,
    )
    wrong_types = [item for item in wrong_types if item['wrong'] > 0]

    diff_order = {'简单': 0, '中等': 1, '困难': 2}
    difficulty_distribution = [
        {'name': name, 'total': stats['total'], 'wrong': stats['wrong']}
        for name, stats in sorted(diff_stats.items(), key=lambda x: diff_order.get(x[0], 1))
    ]

    overall_rate = round(correct / total * 100, 1) if total else 0

    seven_days_ago = timezone.now() - timedelta(days=7)
    recent7_logs = [log for log in logs if log.submitted_at and log.submitted_at >= seven_days_ago]
    recent7_correct = sum(1 for log in recent7_logs if log.is_correct is True)
    recent7_rate = round(recent7_correct / len(recent7_logs) * 100, 1) if recent7_logs else None

    avg_time = round(sum(time_spent_list) / len(time_spent_list)) if time_spent_list else 0

    return {
        'course': subject.name,
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total': total,
        'correct': correct,
        'wrong': wrong,
        'unmarked': unmarked,
        'correct_rate': overall_rate,
        'active_days': len(active_days),
        'avg_time_per_question_seconds': avg_time,
        'recent7_correct_rate': recent7_rate,
        'weak_points': weak_points,
        'wrong_types': wrong_types,
        'difficulty_distribution': difficulty_distribution,
        'recent_wrong': recent_wrong,
    }


def rule_based_insights(snapshot):
    """基于做题记录生成规则分析结论（无需调用 AI，始终可用）"""
    insights = []
    if not snapshot['total']:
        return insights

    rate = snapshot['correct_rate']
    if rate >= 85:
        insights.append('整体掌握较好，正确率较高，可继续保持并适当挑战更难题目。')
    elif rate >= 60:
        insights.append(f'整体正确率 {rate}%，有一定基础，但仍需重点巩固薄弱知识点。')
    else:
        insights.append(f'整体正确率 {rate}%，基础尚不牢固，建议优先复习薄弱知识点并重做错题。')

    weak = snapshot['weak_points'][:3]
    if weak:
        names = '、'.join(f"{w['name']}（错 {w['wrong']} 次）" for w in weak)
        insights.append(f'薄弱知识点：{names}，建议结合教材和题目解析重点复习。')

    wrong_types = snapshot['wrong_types'][:2]
    if wrong_types:
        names = '、'.join(f"{w['name']}（错 {w['wrong']} 次）" for w in wrong_types)
        insights.append(f'易错题型：{names}，注意归纳该类题型的解题方法。')

    hard = [d for d in snapshot['difficulty_distribution'] if d['name'] == '困难' and d['wrong'] > 0]
    if hard:
        insights.append('困难题错误较多，建议先夯实基础，再逐步挑战难题。')

    recent7 = snapshot['recent7_correct_rate']
    if recent7 is not None and rate is not None:
        if recent7 < rate - 5:
            insights.append(f'最近 7 天正确率（{recent7}%）低于整体水平，可能存在知识点遗忘，建议复盘近期错题。')
        elif recent7 > rate + 5:
            insights.append(f'最近 7 天正确率（{recent7}%）高于整体水平，学习状态良好，请继续保持。')

    avg = snapshot['avg_time_per_question_seconds']
    if avg:
        if avg > 120:
            insights.append(f'平均每题耗时约 {avg} 秒，用时偏长，建议提升知识熟练度与答题速度。')
        elif avg < 30:
            insights.append(f'平均每题耗时约 {avg} 秒，答题较快，注意细心审题避免粗心错误。')
        else:
            insights.append(f'平均每题耗时约 {avg} 秒，答题节奏适中。')

    if not insights:
        insights.append('暂无足够做题数据，继续练习后可生成更完整的分析。')
    return insights


def analyze_with_llm(snapshot):
    """调用 DeepSeek 生成错题原因分析与学习计划建议；失败或未配置时返回 None"""
    config = getattr(settings, 'LLM_CONFIG', {})
    api_key = config.get('deepseek_api_key', '') or config.get('api_key', '')
    base_url = config.get('deepseek_base_url', 'https://api.deepseek.com')
    if not api_key:
        return None

    prompt = (
        "你是学习诊断系统中的智能学习分析师。请根据以下学生的做题记录摘要，输出两部分内容：\n"
        "一、错题原因分析：结合薄弱知识点、易错题型、难度分布、答题用时与近期趋势，"
        "推断可能出错的原因（如概念理解不清、知识点薄弱、题型不熟悉、粗心、时间分配不当等），"
        "并指出最需要改进的地方。\n"
        "二、学习计划建议：给出具体、可执行的短期学习计划（如知识点复习顺序、每日练习安排、"
        "错题重练方法、时间管理建议等）。\n"
        "要求：条理清晰、语言简洁、直接给出结论，使用 Markdown 标题和列表，总字数控制在 600 字以内。\n\n"
        "做题记录摘要（JSON）：\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2)
    )

    try:
        resp = requests.post(
            base_url.rstrip('/') + '/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'deepseek-chat',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 1200,
                'stream': False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        return content.strip() if content and content.strip() else None
    except Exception as exc:
        print(f"[exercise_analysis] LLM 分析失败: {exc}")
        return None
