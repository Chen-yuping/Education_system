# 批改作业函数

import re
import requests
import time
import json
import os
import signal
import threading  # 新增这一行
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========= Django 专用导入 =========
from django.conf import settings
from learning.models import AnswerLog, Exercise
from decimal import Decimal

# ====================== API配置 ======================
DEEPSEEK_API_KEY = "sk-0cb6c98144234d9db01b43de710aae28"
KIMI_API_KEY = "sk-jn70MeNzVK3zUn7Cze5GN3VhH9YIrOkmHu7QkVi9t5GWs0BX"

XUNFEI_API_URL = "https://spark-api-open.xf-yun.com/agent/v1/chat/completions"
XUNFEI_API_TOKEN = "jYojZHQoRCTdgXcMVCkZ:KzqqaeosNPDtgErkOMFD"
XUNFEI_MODEL = "spark-x"
XUNFEI_TIMEOUT = 60
XUNFEI_MAX_RETRIES = 2
XUNFEI_RETRY_DELAY = 1

MAX_RETRIES = 3
REQUEST_INTERVAL = 0.2
KIMI_DELAY = 1.0

last_request_time = 0
time_lock = threading.Lock()


def rate_limit():
    global last_request_time
    with time_lock:
        current = time.time()
        elapsed = current - last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        last_request_time = time.time()


def round_to_half(value):
    return round(value * 2) / 2.0


def call_api_with_retry(api_type, prompt, max_retries=MAX_RETRIES):
    if api_type == 'deepseek':
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        model = "deepseek-chat"
    else:
        url = "https://api.moonshot.cn/v1/chat/completions"
        headers = {"Authorization": f"Bearer {KIMI_API_KEY}"}
        model = "moonshot-v1-8k"
        time.sleep(KIMI_DELAY)

    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    for attempt in range(max_retries):
        try:
            rate_limit()
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"⚠️ {api_type} 限流，等待{wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ {api_type} 第{attempt + 1}次失败: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(1 * (attempt + 1))
    return None


def call_xunfei_api(prompt, max_retries=XUNFEI_MAX_RETRIES):
    headers = {"Authorization": f"Bearer {XUNFEI_API_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "model": XUNFEI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800
    }
    for attempt in range(max_retries):
        try:
            rate_limit()
            resp = requests.post(XUNFEI_API_URL, headers=headers, json=payload, timeout=XUNFEI_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                wait = 2 ** attempt
                print(f"⚠️ 讯飞限流，等待{wait}s")
                time.sleep(wait)
        except Exception as e:
            print(f"⚠️ 讯飞第{attempt + 1}次异常: {e}")
        if attempt < max_retries - 1:
            time.sleep(XUNFEI_RETRY_DELAY * (attempt + 1))
    return None


def parse_score_response(content):
    if not content or not isinstance(content, str) or len(content.strip()) == 0:
        return None, "模型返回为空/失败"
    score_match = re.search(r"得分[:：]\s*(\d+\.?\d*)", content)
    reason_match = re.search(r"给分理由[:：]\s*(.*)", content, re.DOTALL)
    score = float(score_match.group(1)) if score_match else None
    reason = reason_match.group(1).strip() if reason_match else "无理由"
    return score, reason


def extract_rubric_components(question, key_points, std_answer, answer):
    print("\n[AutoSCORE] 🔍 开始提取评分要点...")
    extract_prompt = f"""
你是评分要点提取专家。比对学生答案与评分标准。
【题目】{question}
【评分标准】{key_points}
【标准答案】{std_answer if std_answer else "无"}
【学生答案】{answer}
输出JSON：{{"covered_points":[""], "missing_points":[""], "partial_points":[""], "confidence":0.85}}
"""
    try:
        response = call_api_with_retry('deepseek', extract_prompt)
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            res = json.loads(json_match.group())
            print(f"[AutoSCORE] ✅ 要点提取完成：覆盖{len(res['covered_points'])}个，缺失{len(res['missing_points'])}个")
            return res
    except Exception as e:
        print(f"[AutoSCORE] ⚠️ 要点提取失败：{e}")
    return {"covered_points": [], "missing_points": [], "partial_points": [], "confidence": 0.5}


def arbitrate_scores(question, answer, full, key_points, std_answer, ds_score, ds_reason, km_score, km_reason,
                     xf_score, xf_reason):
    valid = []
    if ds_score is not None:
        valid.append(("DeepSeek", ds_score, ds_reason))
    if km_score is not None:
        valid.append(("Kimi", km_score, km_reason))
    if xf_score is not None:
        valid.append(("讯飞", xf_score, xf_reason))
    if len(valid) < 2:
        return None, "有效评分不足，跳过仲裁"

    min_s = min(x[1] for x in valid)
    max_s = max(x[1] for x in valid)
    print(f"[仲裁] ⚖️ 分差过大({max_s}-{min_s})，启动仲裁...")

    prompt = f"""
你是阅卷仲裁官，结合评分标准裁决最终分，精度0.5。
满分{full}
DeepSeek:{ds_score}，理由：{ds_reason}
Kimi:{km_score}，理由：{km_reason}
讯飞:{xf_score}，理由：{xf_reason}
输出：得分: X.X 裁决理由:xxx
"""
    try:
        resp = call_api_with_retry("deepseek", prompt)
        score, reason = parse_score_response(resp)
        final = round_to_half(score) if score else None
        print(f"[仲裁] ✅ 仲裁完成，得分：{final}")
        return final, reason
    except Exception as e:
        print(f"[仲裁] ❌ 仲裁失败：{e}，切换平均分")
        return None, None


def score_with_autoscore(question, answer, full, key_points, std_answer=""):
    full = float(full)
    components = extract_rubric_components(question, key_points, std_answer, answer)
    covered, partial, missing, confidence = (
        components['covered_points'],
        components['partial_points'],
        components['missing_points'],
        components['confidence']
    )

    components_text = ""
    if covered:
        components_text += f"✅ 已覆盖：{', '.join(covered)}\n"
    if partial:
        components_text += f"⚠️ 部分覆盖：{', '.join(partial)}\n"
    if missing:
        components_text += f"❌ 缺失：{', '.join(missing)}\n"

    enhanced_prompt = f"""
【评分标准】{key_points}
【要点覆盖】{components_text}
【学生答案】{answer}
【满分】{full}
输出：得分: X.X 给分理由:逐点说明
"""
    print("[评分] 🔄 调用DeepSeek...")
    ds_raw = call_api_with_retry('deepseek', enhanced_prompt)
    ds_score, ds_reason = parse_score_response(ds_raw)
    ds_score = round_to_half(ds_score) if ds_score is not None else None
    print(f"[评分] ✅ DeepSeek完成：{ds_score}分")

    print("[评分] 🔄 调用Kimi...")
    km_raw = call_api_with_retry('kimi', enhanced_prompt)
    km_score, km_reason = parse_score_response(km_raw)
    km_score = round_to_half(km_score) if km_score is not None else None
    print(f"[评分] ✅ Kimi完成：{km_score}分")

    print("[评分] 🔄 调用讯飞星火...")
    xf_raw = call_xunfei_api(enhanced_prompt)
    xf_score, xf_reason = None, "调用失败"
    if xf_raw:
        xf_score, xf_reason = parse_score_response(xf_raw)
        xf_score = round_to_half(xf_score) if xf_score is not None else None
        print(f"[评分] ✅ 讯飞完成：{xf_score}分")
    else:
        print("[评分] ⚠️ 讯飞调用失败")

    scores = []
    model_info = []
    if ds_score is not None:
        scores.append(ds_score)
        model_info.append(("DS", ds_score, ds_reason))
    if km_score is not None:
        scores.append(km_score)
        model_info.append(("KM", km_score, km_reason))
    if xf_score is not None:
        scores.append(xf_score)
        model_info.append(("XF", xf_score, xf_reason))

    threshold = full * 0.1
    max_diff = max(scores) - min(scores) if len(scores) >= 2 else 0
    print(f"[汇总] 📊 有效得分：{dict([(m, s) for m, s, r in model_info])} | 最大分差：{max_diff:.1f} | 阈值：{threshold:.1f}")

    total, final_method, arb_text = None, "", ""
    if len(scores) >= 2 and max_diff > threshold:
        final_score, arb_reason = arbitrate_scores(
            question, answer, full, key_points, std_answer,
            ds_score, ds_reason, km_score, km_reason, xf_score, xf_reason
        )
        if final_score is not None:
            total = final_score
            final_method = "仲裁裁决"
            arb_text = f"\n【仲裁理由】{arb_reason}"
        else:
            total = round_to_half(sum(scores) / len(scores))
            final_method = "仲裁失败，平均分兜底"
    elif len(scores) >= 1:
        total = round_to_half(sum(scores) / len(scores))
        final_method = "加权平均分"
    else:
        # 取消保底，直接0分
        total = 0.0
        final_method = "全部模型调用失败，判定0分"

    print(f"[结果] 🎯 {final_method} | 最终得分：{total}分\n")

    process = f"""
【AutoSCORE 评分详细过程】
要点提取置信度: {confidence:.2f}
{components_text}
【三模型独立评分】
[DeepSeek] 得分: {ds_score if ds_score is not None else '失败'} 分 | 理由: {ds_reason[:600]}
[Kimi] 得分: {km_score if km_score is not None else '失败'} 分 | 理由: {km_reason[:600]}
[讯飞星火] 得分: {xf_score if xf_score is not None else '失败'} 分 | 理由: {xf_reason[:600] if xf_score else '无'}
{arb_text}
【最终得分确定方式】{final_method}
最终得分: {total} 分 (满分{full})
"""
    return ds_score, km_score, total, process


def score_one(question, answer, full, key_points, std_answer=""):
    full = float(full)
    return score_with_autoscore(question, answer, full, key_points, std_answer)


def grade_single_answer(answer_log_id):
    import signal
    def timeout_handler(signum, frame):
        raise TimeoutError("单题阅卷超时")
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)  # 单题最长10秒，卡死直接0分

        answer_log = AnswerLog.objects.get(id=answer_log_id)
        exercise = answer_log.exercise
        print(f"\n===== 开始批改：题号{exercise.id} | 满分{exercise.score} =====")
        d_score, k_score, final_score, process_text = score_one(
            question=exercise.content,
            answer=answer_log.text_answer,
            full=exercise.score,
            key_points=exercise.solution or "按要点给分",
            std_answer=exercise.answer
        )
        signal.alarm(0)

        answer_log.key_score = Decimal(str(d_score)) if d_score is not None else Decimal(0)
        answer_log.ai_score = Decimal(str(k_score)) if k_score is not None else Decimal(0)
        answer_log.score = Decimal(str(final_score))
        answer_log.ai_feedback = process_text
        answer_log.grading_confidence = Decimal("0.85")
        answer_log.is_correct = None
        answer_log.save()
        print(f"✅ 批改完成，最终得分：{final_score}\n")
        return final_score
    except Exception as e:
        print(f"❌ 单题异常/超时：{e}，直接0分")
        try:
            answer_log = AnswerLog.objects.get(id=answer_log_id)
            answer_log.score = Decimal(0)
            answer_log.ai_feedback = "阅卷超时/异常，判定0分"
            answer_log.save()
        except:
            pass
        return 0.0