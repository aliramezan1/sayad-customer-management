import urllib.request, json, os, zipfile, io

# Get the latest chromedriver version for Chrome 151
url = 'https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json'
try:
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    # Find matching version for 151.0.7922
    matching = [v for v in data['versions'] if v['version'].startswith('151.0.7922')]
    if matching:
        latest = matching[-1]
        ver = latest['version']
        print(f'Found version: {ver}')
        # Get win64 chromedriver download URL
        dl_url = None
        for d in latest.get('downloads', {}).get('chromedriver', []):
            if d['platform'] == 'win64':
                dl_url = d['url']
                break
        if dl_url:
            print(f'Downloading: {dl_url}')
            dest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chromedriver')
            os.makedirs(dest_dir, exist_ok=True)
            resp2 = urllib.request.urlopen(dl_url, timeout=60)
            zip_data = resp2.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for member in zf.namelist():
                    if member.endswith('chromedriver.exe'):
                        # Extract to dest_dir
                        content = zf.read(member)
                        dest_path = os.path.join(dest_dir, 'chromedriver.exe')
                        with open(dest_path, 'wb') as f:
                            f.write(content)
                        print(f'Saved to: {dest_path}')
                        break
        else:
            print('No win64 download found')
    else:
        print('No matching version for 151.0.7922')
        for v in data['versions'][-5:]:
            print(f'  Available: {v["version"]}')
except Exception as e:
    print(f'Error: {e}')
