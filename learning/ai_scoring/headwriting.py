# 暂时没使用，手写识别

import base64
import json
import os
import tempfile
import time
import uuid

import requests
from PIL import Image, ImageEnhance, ImageFilter

from django.conf import settings
from learning.models import AnswerLog, Exercise, User

# ==================== 配置 ====================
API_KEY = "cfEHl6knqWydoBVBIhhuRft6"
SECRET_KEY = "y2yVQWV4XByE2UPYmyedJA4ErnGAqTS0"
OCR_API_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"

TARGET_DIR = "D:/End_test/anwser"
OUTPUT_TXT = "D:/End_test/ocr_result.txt"
SUPPORT_EXT = (".jpg", ".jpeg", ".png", ".bmp")


def get_access_token():
    token_url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={API_KEY}&client_secret={SECRET_KEY}"
    try:
        response = requests.post(token_url, timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        print(f"[ERROR] 获取 AccessToken 失败：{str(e)}")
        return None


def preprocess_image(image_path, output_path="./temp_preprocess.jpg"):
    try:
        img = Image.open(image_path)
        img = img.convert("L")
        img = img.filter(ImageFilter.MedianFilter())
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.8)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.8)
        img.save(output_path)
        return output_path
    except Exception as e:
        print(f"[WARN] 预处理失败：{image_path}，{str(e)}，使用原始图片")
        return image_path


def ocr_single_image(image_path, access_token):
    processed_path = preprocess_image(image_path)
    try:
        with open(processed_path, "rb") as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode("utf-8")
    except Exception as e:
        print(f"[ERROR] 读取图片失败：{image_path}，{str(e)}")
        return ""

    try:
        request_url = f"{OCR_API_URL}?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        params = {
            "image": image_base64,
            "detect_direction": "true",
            "language_type": "CHN_ENG",
            "probability": "true"
        }
        response = requests.post(request_url, headers=headers, data=params, timeout=20)
        response.raise_for_status()
        result = response.json()
        if "words_result" in result and result["words_result"]:
            ocr_text = "".join(item["words"] for item in result["words_result"])
            if os.path.exists(processed_path) and processed_path != image_path:
                os.remove(processed_path)
            return ocr_text.strip().replace('\n', ' ').replace('\r', ' ')
        else:
            return ""
    except Exception as e:
        print(f"[ERROR] API 调用失败：{image_path}，{str(e)}")
        return ""


def batch_ocr_to_django():
    access_token = get_access_token()
    if not access_token:
        print("[ERROR] 无法获取 access_token")
        return

    if os.path.exists(OUTPUT_TXT):
        os.remove(OUTPUT_TXT)

    image_files = []
    for file in os.listdir(TARGET_DIR):
        if file.lower().endswith(SUPPORT_EXT):
            name_without_ext = os.path.splitext(file)[0]
            if '-' in name_without_ext:
                image_files.append((file, name_without_ext))

    if not image_files:
        print("[WARN] 未找到符合格式的图片")
        return

    total = len(image_files)
    success_count = 0

    for idx, (file_name, name_part) in enumerate(image_files, 1):
        img_path = os.path.join(TARGET_DIR, file_name)
        print(f"\n[OCR] 识别 [{idx}/{total}]：{file_name}")

        try:
            question_id, student_id = name_part.split('-', 1)
            question_id = question_id.strip()
            student_id = student_id.strip()
        except ValueError:
            print("[WARN] 文件名格式错误，跳过")
            continue

        ocr_text = ocr_single_image(img_path, access_token)
        if not ocr_text:
            print("[WARN] 识别为空，跳过")
            continue

        try:
            exercise = Exercise.objects.get(id=question_id)
            student = User.objects.get(username=student_id)

            AnswerLog.objects.update_or_create(
                student=student,
                exercise=exercise,
                defaults={
                    "text_answer": ocr_text,
                    "subject": exercise.subject
                }
            )
            success_count += 1
            with open(OUTPUT_TXT, 'a', encoding='utf-8') as f:
                f.write(f"{student_id}-{question_id}-{ocr_text}\n")
        except Exercise.DoesNotExist:
            print(f"[ERROR] 题号{question_id} 不存在")
        except User.DoesNotExist:
            print(f"[ERROR] 学号{student_id} 不存在")
        except Exception as e:
            print(f"[ERROR] 入库失败：{e}")

        time.sleep(0.8)

    print(f"\n[OK] OCR 完成！成功入库 {success_count}/{total} 条")


if __name__ == "__main__":
    batch_ocr_to_django()
