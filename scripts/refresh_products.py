from __future__ import annotations

import base64
import datetime as dt
import json
import os
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

OUT = Path("docs/data/products.json")
QUERIES = ["home organization", "cleaning tools", "travel accessories", "pet supplies", "kitchen gadgets"]


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None) -> Any:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def ebay_token() -> str | None:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
    result = request_json(
        "https://api.ebay.com/identity/v1/oauth2/token",
        method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    return result.get("access_token")


def score_item(item: dict[str, Any]) -> int:
    score = 62
    price = float((item.get("price") or {}).get("value") or 0)
    if 5 <= price <= 25:
        score += 10
    elif price <= 45:
        score += 5
    marketing = item.get("marketingPrice") or {}
    discount = float(marketing.get("discountPercentage") or 0)
    score += min(10, int(discount / 4))
    seller = item.get("seller") or {}
    feedback = float(seller.get("feedbackPercentage") or 0)
    if feedback >= 98:
        score += 7
    elif feedback >= 95:
        score += 4
    if item.get("image"):
        score += 3
    if "FIXED_PRICE" in (item.get("buyingOptions") or []):
        score += 3
    return max(50, min(96, score + random.randint(-2, 3)))


def basic_pack(title: str, platform: str) -> str:
    return (
        f"【{platform}候选商品上架资料】\n\n"
        f"原商品方向：{title}\n\n"
        "Temu中文标题：1件装 升级款便携多功能日常用品 小巧易收纳 操作方便 适用于居家 旅行 办公与日常使用\n\n"
        "Temu英文标题：1PC Upgraded Portable Multipurpose Daily Essential, Compact and Easy to Store, Convenient for Home, Travel, Office and Everyday Use\n\n"
        "核心卖点：\n1. 使用场景清晰，便于制作场景主图\n2. 小巧便携，适合跨境轻小件测试\n3. 操作直观，容易通过短视频展示\n4. 可从规格、数量和配色方向做差异化\n5. 上架前需重新核实尺寸、功能、供应链和平台规则\n\n"
        "图片建议：白底主图、核心功能图、使用场景图、尺寸图、细节图、前后对比图。\n\n"
        "注意：资料为选品辅助草稿，不得直接复制竞品品牌、图片、专利设计或受保护文案。"
    )


def fetch_ebay() -> list[dict[str, Any]]:
    token = ebay_token()
    if not token:
        return []
    products: list[dict[str, Any]] = []
    for query in QUERIES:
        params = urllib.parse.urlencode({"q": query, "limit": 8, "filter": "buyingOptions:{FIXED_PRICE}"})
        data = request_json(
            f"https://api.ebay.com/buy/browse/v1/item_summary/search?{params}",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        )
        for item in data.get("itemSummaries", []):
            title = item.get("title") or "未命名商品"
            price_obj = item.get("price") or {}
            price = f"{price_obj.get('currency', 'USD')} {price_obj.get('value', '--')}"
            score = score_item(item)
            products.append({
                "platform": "eBay US",
                "title": title,
                "category": query,
                "price": price,
                "score": score,
                "reason": "来自 eBay 官方 Browse API。当前评分综合价格带、折扣、卖家反馈和商品信息完整度，用于初筛，不代表真实销量预测。",
                "source_url": item.get("itemWebUrl") or "https://www.ebay.com/",
                "image": (item.get("image") or {}).get("imageUrl") or "",
                "demo": False,
                "listing_pack": basic_pack(title, "eBay"),
            })
    products.sort(key=lambda x: x["score"], reverse=True)
    return products[:30]


def fetch_generic(platform: str, endpoint_env: str, token_env: str) -> list[dict[str, Any]]:
    endpoint = os.getenv(endpoint_env, "").strip()
    if not endpoint:
        return []
    headers = {"Accept": "application/json"}
    token = os.getenv(token_env, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = request_json(endpoint, headers=headers)
    rows = data.get("products", data) if isinstance(data, dict) else data
    output = []
    for row in rows[:30]:
        title = str(row.get("title") or row.get("name") or "未命名商品")
        output.append({
            "platform": platform,
            "title": title,
            "category": str(row.get("category") or "未分类"),
            "price": str(row.get("price") or "价格待核"),
            "score": int(row.get("score") or row.get("potential_score") or 75),
            "reason": str(row.get("reason") or "来自已授权的数据接口，评分用于初筛。"),
            "source_url": str(row.get("url") or row.get("source_url") or "#"),
            "image": str(row.get("image") or row.get("image_url") or ""),
            "demo": False,
            "listing_pack": str(row.get("listing_pack") or basic_pack(title, platform)),
        })
    return output


def demo_products() -> list[dict[str, Any]]:
    return [
        {
            "platform": "演示 · Amazon US",
            "title": "可折叠旅行收纳包",
            "category": "旅行收纳",
            "price": "$12.99",
            "score": 88,
            "reason": "演示数据：轻小件、场景清晰、适合通过展开与折叠对比展示卖点。",
            "source_url": "https://www.amazon.com/",
            "image": "https://placehold.co/400x400?text=Demo+Product",
            "demo": True,
            "listing_pack": basic_pack("可折叠旅行收纳包", "演示"),
        },
        {
            "platform": "演示 · Temu",
            "title": "桌面迷你清洁工具",
            "category": "家居清洁",
            "price": "$8.49",
            "score": 84,
            "reason": "演示数据：解决具体清洁痛点，场景图片和短视频容易表达。",
            "source_url": "https://www.temu.com/",
            "image": "https://placehold.co/400x400?text=Demo+Product",
            "demo": True,
            "listing_pack": basic_pack("桌面迷你清洁工具", "演示"),
        },
    ]


def main() -> None:
    products: list[dict[str, Any]] = []
    errors: list[str] = []
    connectors = [
        ("eBay", fetch_ebay),
        ("Temu", lambda: fetch_generic("Temu", "TEMU_DATA_ENDPOINT", "TEMU_ACCESS_TOKEN")),
        ("Shopee", lambda: fetch_generic("Shopee", "SHOPEE_DATA_ENDPOINT", "SHOPEE_ACCESS_TOKEN")),
        ("AliExpress", lambda: fetch_generic("AliExpress", "ALI_DATA_ENDPOINT", "ALI_ACCESS_TOKEN")),
        ("Amazon", lambda: fetch_generic("Amazon", "AMAZON_DATA_ENDPOINT", "AMAZON_ACCESS_TOKEN")),
    ]
    for name, connector in connectors:
        try:
            products.extend(connector())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    mode = "live" if products else "demo"
    if not products:
        products = demo_products()
    products.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    payload = {
        "mode": mode,
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "errors": errors,
        "products": products[:100],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(payload['products'])} products, mode={mode}")


if __name__ == "__main__":
    main()
