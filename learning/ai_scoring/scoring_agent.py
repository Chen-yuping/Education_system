import re
import requests
import time
import threading
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from learning.models import Exercise, AnswerLog

BASE_DIR = settings.BASE_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

COMPARISON_FILE = os.path.join(DATA_DIR, "comparison_result.xlsx")
COMPARISON_TXT_FALLBACK = os.path.join(DATA_DIR, "comparison_result.txt")
REFERENCE_FILE = os.path.join(DATA_DIR, "comparison.txt")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "XXX")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "XXX")

XUNFEI_API_URL = "https://spark-api-open.xf-yun.com/agent/v1/chat/completions"
XUNFEI_API_TOKEN = os.environ.get("XUNFEI_API_TOKEN", "XXX")
XUNFEI_MODEL = "spark-x"
XUNFEI_TIMEOUT = 90
XUNFEI_MAX_RETRIES = 3
XUNFEI_RETRY_DELAY = 2

MAX_PARALLEL_QUESTIONS = 2
MAX_RETRIES = 3
REQUEST_INTERVAL = 0.2
KIMI_DELAY = 1.0

last_request_time = 0
time_lock = threading.Lock()

# 评分结果缓存（文件持久化，服务器重启不丢失，不改变数据库）
SCORING_CACHE_FILE = os.path.join(DATA_DIR, "scoring_cache.json")
_cache_lock = threading.Lock()


def _load_cache():
    """从文件加载缓存"""
    if os.path.exists(SCORING_CACHE_FILE):
        try:
            with open(SCORING_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache):
    """保存缓存到文件"""
    try:
        with open(SCORING_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


_scoring_result_cache = _load_cache()

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    print("[WARN] 未安装 openpyxl，将使用 TXT 格式输出对比结果。如需 Excel 格式，请运行: pip install openpyxl")


def rate_limit():
    global last_request_time
    with time_lock:
        current = time.time()
        elapsed = current - last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        last_request_time = time.time()


def clean_qid(qid):
    return re.sub(r'[^0-9]', '', str(qid))


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

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    for attempt in range(max_retries):
        try:
            rate_limit()
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"[WARN] {api_type} 触发限流(429)，等待 {wait} 秒后重试...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[WARN] {api_type} 第{attempt + 1}次尝试失败：{e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(1 * (attempt + 1))


def call_xunfei_api(prompt, max_retries=XUNFEI_MAX_RETRIES):
    headers = {
        "Authorization": f"Bearer {XUNFEI_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": XUNFEI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800
    }

    for attempt in range(max_retries):
        try:
            rate_limit()
            resp = requests.post(
                XUNFEI_API_URL,
                headers=headers,
                json=payload,
                timeout=XUNFEI_TIMEOUT
            )
            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                wait = 2 ** attempt
                print(f"[WARN] 讯飞星火触发限流(429)，等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"[WARN] 讯飞星火返回错误 {resp.status_code}: {resp.text[:200]}")
        except requests.exceptions.RequestException as e:
            print(f"[WARN] 讯飞星火第 {attempt + 1} 次请求异常：{e}")
        except (KeyError, json.JSONDecodeError) as e:
            print(f"[WARN] 讯飞星火响应解析失败：{e}")

        if attempt < max_retries - 1:
            time.sleep(XUNFEI_RETRY_DELAY * (attempt + 1))

    print("[ERROR] 讯飞星火调用失败（已达最大重试次数）")
    return None


def parse_score_response(content):
    score_match = re.search(r"得分[:：]\s*(\d+\.?\d*)", content)
    reason_match = re.search(r"给分理由[:：]\s*(.*)", content, re.DOTALL)
    if score_match:
        score = float(score_match.group(1))
    else:
        score = 0.0
    reason = reason_match.group(1).strip() if reason_match else "无理由"
    return score, reason


def extract_rubric_components(question, key_points, std_answer, answer):
    extract_prompt = f"""
你是一个评分要点提取专家。请分析学生答案，与评分标准进行逐点比对。
【题目】{question}
【评分标准】{key_points}
【标准答案】{std_answer if std_answer else "无"}
【学生答案】{answer}
【输出要求】严格JSON格式：{{"covered_points":[],"missing_points":[],"partial_points":[],"confidence":0.85}}
"""
    try:
        response = call_api_with_retry('deepseek', extract_prompt)
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"[WARN] 组件提取失败：{e}")
    return {"covered_points": [], "missing_points": [], "partial_points": [], "confidence": 0.5}


def clean_for_dictation(text):
    return re.sub(r'[^一-龥a-zA-Z0-9]', '', text)


def exact_word_match_scoring(question, answer, full, key_points, std_answer):
    if not std_answer:
        return None, None, None, None
    std_clean = clean_for_dictation(std_answer.strip())
    ans_clean = clean_for_dictation(answer.strip())
    correct_count = 0
    min_len = min(len(std_clean), len(ans_clean))
    for i in range(min_len):
        if ans_clean[i] == std_clean[i]:
            correct_count += 1
    unit_score = 1.0
    match = re.search(r'每写对一[个字]得(\d+(?:\.\d+)?)分', key_points)
    if match:
        unit_score = float(match.group(1))
    else:
        unit_score = full / len(std_clean) if len(std_clean) > 0 else 1.0
    raw_score = correct_count * unit_score
    final_score = round_to_half(min(raw_score, full))
    process = f"【逐字比对】正确{correct_count}/{len(std_clean)}，得分{final_score:.1f}"
    return final_score, final_score, final_score, process


def arbitrate_scores(question, answer, full, key_points, std_answer,
                     ds_score, ds_reason, km_score, km_reason, xf_score, xf_reason):
    scores = [("DeepSeek", ds_score, ds_reason), ("Kimi", km_score, km_reason)]
    if xf_score is not None:
        scores.append(("讯飞星火", xf_score, xf_reason))
    min_score = min(s[1] for s in scores)
    max_score = max(s[1] for s in scores)
    diff_points = [f"最高分{max_score}，最低分{min_score}"] if max_score - min_score > 0 else ["无分歧"]
    dispute_desc = "；".join(diff_points)

    prompt = f"""你是阅卷仲裁官，裁决最终得分，四舍五入到0.5倍
【题目】{question}【评分标准】{key_points}【标准答案】{std_answer}【学生答案】{answer}【满分】{full}
【评分】DeepSeek:{ds_score}({ds_reason})，Kimi:{km_score}({km_reason})，讯飞:{xf_score}({xf_reason})
【分歧】{dispute_desc}
输出：得分: X.X 裁决理由: ..."""
    try:
        response = call_api_with_retry('deepseek', prompt)
        score, reason = parse_score_response(response)
        return round_to_half(score), reason
    except Exception as e:
        print(f"[WARN] 仲裁失败：{e}")
        return None, None


def score_with_autoscore(question, answer, full, key_points, std_answer=""):
    full = float(full)
    components = extract_rubric_components(question, key_points, std_answer, answer)
    covered = components.get('covered_points', [])
    partial = components.get('partial_points', [])
    missing = components.get('missing_points', [])
    confidence = components.get('confidence', 0.5)

    components_text = f"已覆盖:{covered} 部分:{partial} 缺失:{missing}"
    enhanced_prompt = f"""【评分标准】{key_points}\n【覆盖情况】{components_text}\n【学生答案】{answer}\n【满分】{full}
按要点评分，输出：得分: X.X 给分理由: ..."""

    ds_raw = call_api_with_retry('deepseek', enhanced_prompt)
    ds_score, ds_reason = parse_score_response(ds_raw)
    ds_score = round_to_half(ds_score)

    km_raw = call_api_with_retry('kimi', enhanced_prompt)
    km_score, km_reason = parse_score_response(km_raw)
    km_score = round_to_half(km_score)

    xf_raw = call_xunfei_api(enhanced_prompt)
    xf_score, xf_reason = (parse_score_response(xf_raw) if xf_raw else (None, "调用失败"))
    xf_score = round_to_half(xf_score) if xf_score is not None else None

    scores = [s for s in [ds_score, km_score, xf_score] if s is not None]
    max_diff = max(scores) - min(scores) if len(scores) >= 2 else 0
    threshold = full * 0.1

    if max_diff > threshold:
        final_score, arb_reason = arbitrate_scores(
            question, answer, full, key_points, std_answer,
            ds_score, ds_reason, km_score, km_reason, xf_score, xf_reason
        )
        if final_score is not None:
            total = final_score
        else:
            total = round_to_half(ds_score * 0.5 + km_score * 0.3 + (xf_score or 0) * 0.2)
    else:
        total = round_to_half(ds_score * 0.5 + km_score * 0.3 + (xf_score or 0) * 0.2)

    process = f"【三模型评分】DS:{ds_score} KM:{km_score} XF:{xf_score} -> 最终:{total}\n【理由】{ds_reason[:200]}"
    return ds_score, km_score, xf_score, total, process


def score_one(question, answer, full, key_points, std_answer=""):
    full = float(full)
    if std_answer and any(kw in key_points for kw in ["每写错一个字", "每写对一个字", "逐字"]):
        return exact_word_match_scoring(question, answer, full, key_points, std_answer)
    return score_with_autoscore(question, answer, full, key_points, std_answer)


def score_baseline(question, answer, full, key_points, std_answer=""):
    full = float(full)
    prompt = f"阅卷评分：【题目】{question}【标准】{key_points}【满分】{full}【答案】{answer}，输出得分+理由"
    try:
        ds_raw = call_api_with_retry('deepseek', prompt)
        ds_score, ds_reason = parse_score_response(ds_raw)
        km_raw = call_api_with_retry('kimi', prompt)
        km_score, km_reason = parse_score_response(km_raw)
        total = round_to_half(ds_score * 0.6 + km_score * 0.4)
        return total, ds_reason, km_reason
    except:
        return 0.0, "错误", "错误"


def auto_score_answer(answer_log_id):
    """读取答题记录，三模型仲裁评分，返回结果字典（不写数据库）"""
    try:
        answer_log = AnswerLog.objects.get(id=answer_log_id)
        exercise = answer_log.exercise

        question = exercise.content
        full_score = float(exercise.score)
        key_points = exercise.solution or ""
        std_answer = exercise.answer or ""
        student_answer = answer_log.text_answer or ""

        ds_score, km_score, xf_score, final_score, process = score_one(
            question=question,
            answer=student_answer,
            full=full_score,
            key_points=key_points,
            std_answer=std_answer
        )

        print(f"[OK] 判分完成！ID:{answer_log_id} 得分:{final_score}")
        result = {
            'success': True,
            'final_score': round(final_score, 1) if final_score is not None else 0.0,
            'full_score': full_score,
            'ds_score': round(ds_score, 1) if ds_score is not None else None,
            'km_score': round(km_score, 1) if km_score is not None else None,
            'xf_score': round(xf_score, 1) if xf_score is not None else None,
            'process': process,
            'question': question,
            'student_answer': student_answer,
            'std_answer': std_answer,
            'key_points': key_points,
        }
        _scoring_result_cache[str(answer_log_id)] = result
        _save_cache(_scoring_result_cache)
        return result

    except AnswerLog.DoesNotExist:
        return {'success': False, 'error': f'答题记录 {answer_log_id} 不存在'}
    except Exception as e:
        print(f"[ERROR] 判分失败 ID:{answer_log_id} 错误:{str(e)}")
        return {'success': False, 'error': str(e), 'final_score': 0.0}


def get_cached_score(answer_log_id):
    """读取缓存的评分结果（不调用 API，不写数据库）"""
    return _scoring_result_cache.get(str(answer_log_id))


def batch_auto_score(subject_id=None):
    """批量评分，返回结果列表（不写数据库）"""
    logs = AnswerLog.objects.filter(
        exercise__question_type__in=['5', 'subjective'],
        text_answer__isnull=False,
    ).exclude(text_answer='')
    if subject_id:
        logs = logs.filter(exercise__subject_id=subject_id)

    results = []
    for log in logs:
        result = auto_score_answer(log.id)
        result['log_id'] = log.id
        results.append(result)
    return results


if __name__ == "__main__":
    print("[INFO] 请在 Django 项目中通过视图调用此模块的功能。")
