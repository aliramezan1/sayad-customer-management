import ddddocr
import io
import re
from PIL import Image
import numpy as np

ocr = ddddocr.DdddOcr(show_ad=False)

def solve_math_captcha_auto(img: Image.Image) -> str | None:
    """
    100% Automated solver for CBI math captchas.
    Takes PIL Image, preprocesses with optimal thresholding, uses OCR and evaluates math.
    """
    gray = img.convert('L')
    arr = np.array(gray)

    # Test thresholds to get the cleanest formula
    candidates = []
    for th in [170, 180, 150, 190]:
        t_arr = np.where(arr < th, 0, 255).astype(np.uint8)
        t_img = Image.fromarray(t_arr).resize((img.width * 2, img.height * 2), Image.LANCZOS)
        buf = io.BytesIO()
        t_img.save(buf, format='PNG')
        res = ocr.classification(buf.getvalue())
        candidates.append(res)

    # Also test original
    buf_orig = io.BytesIO()
    img.save(buf_orig, format='PNG')
    candidates.append(ocr.classification(buf_orig.getvalue()))

    print(f"OCR Candidates: {candidates}")

    for text in candidates:
        # Standardize operator characters
        norm = text.replace("十", "+").replace("t", "+").replace("T", "+")
        norm = norm.replace("一", "-").replace("—", "-")
        norm = norm.replace("x", "*").replace("X", "*").replace("×", "*")
        norm = norm.replace("o", "0").replace("O", "0")
        
        # Look for <num1> <op> <num2>
        m = re.search(r"(\d+)\s*([\+\-\*])\s*(\d+)", norm)
        if m:
            n1 = int(m.group(1))
            op = m.group(2)
            n2 = int(m.group(3))
            if op == '+':
                ans = n1 + n2
            elif op == '-':
                ans = n1 - n2
            elif op == '*':
                ans = n1 * n2
            print(f"Solved: {n1} {op} {n2} = {ans}")
            return str(ans)

    # Fallback regex on just finding numbers
    for text in candidates:
        nums = re.findall(r"\d+", text)
        if len(nums) >= 2:
            ans = int(nums[0]) + int(nums[1])
            print(f"Fallback addition: {nums[0]} + {nums[1]} = {ans}")
            return str(ans)

    return None

img = Image.open('sample_captcha_0.png')
ans = solve_math_captcha_auto(img)
print(f"Final Answer for sample_captcha_0.png: {ans}")
