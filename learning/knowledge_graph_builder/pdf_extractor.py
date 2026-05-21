"""
PDF文本提取模块
支持直接提取文字和OCR两种方式，从PDF中提取完整文本内容
"""
import io
import os
import sys
import logging
from pathlib import Path

# 解决Windows GBK编码问题
_orig_stdout = sys.stdout
if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer and not sys.stdout.buffer.closed:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = _orig_stdout


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    从PDF文件中提取文本内容

    1. 先尝试使用PyMuPDF直接提取文字
    2. 如果提取的文字太少（< 50字符），判定为扫描版，启用OCR
    """
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"文件不存在: {pdf_path}")

    import fitz  # PyMuPDF

    doc = fitz.open(pdf)
    all_text = []
    for page in doc:
        text = page.get_text().strip()
        if text:
            all_text.append(text)
    direct_text = "\n".join(all_text).strip()

    if len(direct_text) < 50:
        print("  -> 检测到扫描版PDF，启用OCR...")
        final_text = _ocr_pdf(doc)
    else:
        final_text = direct_text

    doc.close()
    return final_text


def _ocr_pdf(doc) -> str:
    """使用PaddleOCR对扫描版PDF进行OCR识别"""
    import numpy as np
    logging.getLogger('ppocr').setLevel(logging.WARNING)
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)

    ocr_pages = []
    total = len(doc)
    for i, page in enumerate(doc, 1):
        print(f"  -> OCR第{i}/{total}页...")
        pix = page.get_pixmap(dpi=300)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        result = ocr.ocr(img, cls=True)
        if result and result[0]:
            page_lines = [line[1][0] for line in result[0]]
            ocr_pages.append("\n".join(page_lines))
        else:
            ocr_pages.append("")

    return "\n\n".join(ocr_pages)
