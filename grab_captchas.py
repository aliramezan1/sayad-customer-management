import time
import base64
import io
import os
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from PIL import Image

opts = EdgeOptions()
opts.add_argument('--headless=new')
opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')
opts.add_argument('--disable-blink-features=AutomationControlled')
opts.add_experimental_option('excludeSwitches', ['enable-automation'])
opts.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Edge(options=opts)
try:
    os.makedirs('captcha_samples', exist_ok=True)
    driver.get('https://www.cbi.ir/EstelamSayad/24090.aspx')
    time.sleep(5)
    
    for i in range(10):
        # Refresh page or get image
        driver.get('https://www.cbi.ir/EstelamSayad/24090.aspx')
        time.sleep(3)
        img_el = driver.find_element(By.ID, 'ctl00_ucBody_ucContent_ctl00_imgcpatcha')
        src = img_el.get_attribute('src') or ''
        if 'base64,' in src:
            b64 = src.split('base64,')[1]
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img.save(f'captcha_samples/cap_{i+1}.png')
            print(f'Saved cap_{i+1}.png')
finally:
    driver.quit()
