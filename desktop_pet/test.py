import requests
import re

def get_embedding(text, api_key, model="bge-large"): # 修改 2：将默认 model 改为 'bge-large'
    url = "https://api.deepseek.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 修改 1：增加文本预处理，移除控制字符
    # 正则表达式解释：匹配十六进制 ASCII 码在 \x00 到 \x1f 范围内的控制字符并移除
    cleaned_text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)

    data = {
        "model": model,
        "input": [cleaned_text]  # 重要：input 是一个列表
    }

    try:
        # 建议显式设置连接和读取超时
        response = requests.post(url, headers=headers, json=data, timeout=(5, 20))
        response.raise_for_status()  # 检查 HTTP 请求是否成功 (404 等错误会在这里被捕获)
        result = response.json()
        embedding = result["data"][0]["embedding"]
        return embedding
    except requests.exceptions.RequestException as e:
        print(f"API 请求失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"响应状态码: {e.response.status_code}")
            print(f"响应内容: {e.response.text}")  # 打印服务器返回的详细信息
        return None

# 使用示例
YOUR_API_KEY = "sk-1d792515bb7e4fa9b8ed206fa6e613e2"
vector = get_embedding("你好，世界！", YOUR_API_KEY)
print(vector[:5])  # 打印前5个维度