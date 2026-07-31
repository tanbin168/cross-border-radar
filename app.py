from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="跨境爆款雷达", version="1.1.0")
LOCK = threading.Lock()
STATE: dict[str, Any] = {"updated_at": None, "mode": "演示模式", "products": [], "errors": []}

DEMO_ROWS = [
    ("eBay", "便携折叠收纳袋", "Home Storage", 12.99, 88, "https://www.ebay.com/sch/i.html?_nkw=portable+foldable+storage+bag"),
    ("Amazon", "桌面迷你清洁工具", "Home Cleaning", 15.99, 86, "https://www.amazon.com/s?k=mini+desktop+cleaning+tool"),
    ("AliExpress", "旅行拉链分类收纳包", "Travel Accessories", 7.49, 84, "https://www.aliexpress.com/wholesale?SearchText=travel+zipper+organizer+pouch"),
    ("Temu", "可卷宠物夏季凉垫", "Pet Supplies", 9.99, 83, "https://www.temu.com/search_result.html?search_key=pet%20cooling%20mat"),
    ("Shopee", "旋转桌面化妆收纳架", "Beauty Storage", 11.50, 81, "https://shopee.com/search?keyword=rotating%20makeup%20organizer"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify(authorization: str | None) -> None:
    token = os.getenv("APP_ACCESS_TOKEN", "").strip()
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="访问令牌不正确")


def score_product(row: dict[str, Any]) -> float:
    sales = min(float(row.get("sales", 0)) / 1000, 1) * 30
    reviews = min(float(row.get("reviews", 0)) / 500, 1) * 20
    growth = min(max(float(row.get("growth", 0)), 0) / 100, 1) * 30
    discount = min(max(float(row.get("discount", 0)), 0) / 50, 1) * 10
    competition = (1 - min(max(float(row.get("competition", 50)), 0) / 100, 1)) * 10
    return round(min(100, sales + reviews + growth + discount + competition), 1)


def make_demo() -> list[dict[str, Any]]:
    products = []
    for i, (platform, title, category, price, base_score, url) in enumerate(DEMO_ROWS, start=1):
        products.append({
            "id": f"demo-{i}", "platform": platform, "title": title, "category": category,
            "price": price, "currency": "USD", "sales": 120 + i * 37,
            "reviews": 45 + i * 13, "growth": 28 + i * 4, "discount": 10 + i * 2,
            "competition": 42 + i * 3, "score": base_score, "source_url": url,
            "image_url": "", "reason": "演示候选：用于检查联网、筛选和资料生成功能，不代表真实销量。",
            "is_demo": True,
        })
    return products


def ebay_token() -> str:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("未配置 eBay API")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def fetch_ebay() -> list[dict[str, Any]]:
    token = ebay_token()
    queries = [q.strip() for q in os.getenv(
        "RADAR_QUERIES",
        "portable organizer,home storage,pet cooling mat,desktop cleaner,travel accessories"
    ).split(",") if q.strip()]
    rows: list[dict[str, Any]] = []
    for query in queries[:8]:
        response = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            params={"q": query, "limit": 20, "sort": "newlyListed"},
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            timeout=25,
        )
        response.raise_for_status()
        for item in response.json().get("itemSummaries", []):
            price_obj = item.get("price") or {}
            seller = item.get("seller") or {}
            image = item.get("image") or {}
            rows.append({
                "id": item.get("itemId") or str(uuid.uuid4()), "platform": "eBay",
                "title": item.get("title") or query, "category": query,
                "price": float(price_obj.get("value") or 0), "currency": price_obj.get("currency") or "USD",
                "sales": 0, "reviews": int(seller.get("feedbackScore") or 0), "growth": 35,
                "discount": 0, "competition": 55, "source_url": item.get("itemWebUrl") or "",
                "image_url": image.get("imageUrl") or "",
                "reason": "来自 eBay 官方 Browse API；增长分为第一版模型估算，需结合供应链复核。",
                "is_demo": False,
            })
    return rows


def fetch_generic(prefix: str, platform: str) -> list[dict[str, Any]]:
    endpoint = os.getenv(f"{prefix}_DATA_ENDPOINT", "").strip()
    if not endpoint:
        return []
    token = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(endpoint, headers=headers, timeout=35)
    response.raise_for_status()
    payload = response.json()
    source_rows = payload.get("products", payload) if isinstance(payload, dict) else payload
    results = []
    for item in source_rows[:100]:
        row = {
            "id": str(item.get("id") or item.get("item_id") or uuid.uuid4()),
            "platform": platform, "title": str(item.get("title") or item.get("name") or "未命名商品"),
            "category": str(item.get("category") or "未分类"), "price": float(item.get("price") or 0),
            "currency": str(item.get("currency") or "USD"),
            "sales": int(item.get("sales") or item.get("orders") or 0),
            "reviews": int(item.get("reviews") or item.get("rating_count") or 0),
            "growth": float(item.get("growth") or item.get("growth_rate") or 0),
            "discount": float(item.get("discount") or 0), "competition": float(item.get("competition") or 50),
            "source_url": str(item.get("url") or item.get("source_url") or ""),
            "image_url": str(item.get("image") or item.get("image_url") or ""),
            "reason": f"来自已授权的 {platform} 数据端点。", "is_demo": False,
        }
        row["score"] = score_product(row)
        results.append(row)
    return results


def refresh_data() -> dict[str, Any]:
    errors: list[str] = []
    products: list[dict[str, Any]] = []
    if os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET"):
        try:
            products.extend(fetch_ebay())
        except Exception as exc:
            errors.append(f"eBay：{exc}")
    for prefix, platform in [("TEMU", "Temu"), ("SHOPEE", "Shopee"), ("ALI", "AliExpress"), ("AMAZON", "Amazon")]:
        try:
            products.extend(fetch_generic(prefix, platform))
        except Exception as exc:
            errors.append(f"{platform}：{exc}")
    if not products:
        products = make_demo()
        mode = "演示模式"
    else:
        for row in products:
            row["score"] = score_product(row)
        mode = "真实接口模式"
    products.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    STATE.update({"updated_at": now_iso(), "mode": mode, "products": products[:300], "errors": errors})
    return STATE


class PackRequest(BaseModel):
    product_id: str
    source_platform: str | None = None
    target_platform: str = "Temu"


def fallback_pack(product: dict[str, Any], target: str) -> dict[str, Any]:
    title = product["title"]
    return {
        "target_platform": target,
        "cn_title": f"1件装 升级款 {title} 便携实用 多场景收纳整理用品 适用于家居旅行办公室日常使用",
        "en_title": f"1PC Upgraded {title}, Portable Practical Multi-Purpose Organizer for Home, Travel, Office and Daily Use",
        "selling_points": [
            "结构直观，核心用途容易通过主图展示",
            "体积和使用场景清晰，适合移动端浏览",
            "可围绕便携、整理和日常使用制作差异化内容",
            "上架前需核实尺寸、材质、包装数量与供应链信息",
            "不得复制竞品图片、商标、品牌词或受保护文案",
        ],
        "keywords": [title, product.get("category", ""), "portable", "organizer", "daily use"],
        "description": f"根据来源商品的公开信息重新整理的 {target} 上架草稿。请以实际采购样品和供应商参数为准，并完成侵权、资质和平台规则核查。",
        "image_plan": ["纯白背景产品主图", "核心功能展示图", "真实比例尺寸图", "家居使用场景图", "结构细节与包装清单图"],
        "risk_notice": "这是重新撰写的资料草稿，不代表可直接复制竞品素材；上架前必须核实知识产权、资质、尺寸、材质和功效表述。",
    }


def generate_with_openai(product: dict[str, Any], target: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    prompt = f"""你是跨境电商合规选品编辑。根据以下商品信息，为 {target} 重新生成一套全新、不可照抄竞品的上架资料。
商品：{json.dumps(product, ensure_ascii=False)}
只返回JSON，字段必须为 cn_title,en_title,selling_points,keywords,description,image_plan,risk_notice。不得使用品牌词、医疗功效、绝对化承诺，不得声称销量和爆款必然性。"""
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": os.getenv("OPENAI_MODEL", "gpt-5-mini"), "input": prompt},
        timeout=70,
    )
    response.raise_for_status()
    payload = response.json()
    text = payload.get("output_text")
    if not text:
        for block in payload.get("output", []):
            for content in block.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text")
                    break
    if not text:
        return None
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    result = json.loads(text)
    result["target_platform"] = target
    return result


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "mode": STATE.get("mode"), "updated_at": STATE.get("updated_at")}


@app.get("/api/products")
def products(
    limit: int = Query(100, ge=1, le=300), platform: str | None = None,
    min_score: float = 0, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    verify(authorization)
    if not STATE["products"]:
        refresh_data()
    rows = STATE["products"]
    if platform:
        rows = [r for r in rows if r["platform"].lower() == platform.lower()]
    rows = [r for r in rows if float(r.get("score", 0)) >= min_score][:limit]
    return {"ok": True, "updated_at": STATE["updated_at"], "mode": STATE["mode"], "errors": STATE["errors"], "products": rows}


@app.post("/api/refresh")
def refresh(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify(authorization)
    if not LOCK.acquire(blocking=False):
        return {"ok": True, "message": "刷新任务正在运行"}
    try:
        data = refresh_data()
        return {"ok": True, "updated_at": data["updated_at"], "mode": data["mode"], "count": len(data["products"]), "errors": data["errors"]}
    finally:
        LOCK.release()


@app.post("/api/listing-pack")
def listing_pack(request: PackRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    verify(authorization)
    if not STATE["products"]:
        refresh_data()
    product = next((r for r in STATE["products"] if str(r["id"]) == str(request.product_id)), None)
    if not product:
        raise HTTPException(status_code=404, detail="未找到商品，请刷新后重试")
    try:
        pack = generate_with_openai(product, request.target_platform) or fallback_pack(product, request.target_platform)
    except Exception as exc:
        pack = fallback_pack(product, request.target_platform)
        pack["ai_error"] = str(exc)
    return {"ok": True, "product": product, "listing_pack": pack}


HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>跨境爆款雷达</title>
<style>
:root{color-scheme:dark;--bg:#06111f;--card:#0e2035;--line:#294865;--text:#f5f8fc;--muted:#93a8bd;--accent:#ff9f2f;--green:#42d3a1}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#071321,#020a13);font-family:system-ui,-apple-system,"PingFang SC",sans-serif;color:var(--text)}main{max-width:820px;margin:auto;padding:24px 16px 90px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px}.eyebrow{letter-spacing:3px;color:#ffb13b;font-weight:800;font-size:12px}h1{font-size:34px;margin:8px 0 18px}.btn{border:0;border-radius:18px;padding:14px 18px;font-weight:800;background:var(--accent);color:#08111b;font-size:16px}.status,.filters,.product,.pack{background:rgba(14,32,53,.92);border:1px solid var(--line);border-radius:22px;padding:16px;margin:14px 0}.status{display:flex;justify-content:space-between;gap:10px}.good{color:var(--green)}.bad{color:#ff7474}.muted{color:var(--muted);font-size:13px}.filters{display:grid;grid-template-columns:1fr 130px;gap:10px}input,select{width:100%;border:1px solid var(--line);border-radius:14px;background:#08182a;color:var(--text);padding:13px;font-size:16px}.product{display:grid;grid-template-columns:88px 1fr;gap:14px}.thumb{width:88px;height:88px;border-radius:16px;background:#142a42;object-fit:cover}.score{font-size:26px;color:#ffb13b;font-weight:900}.row{display:flex;justify-content:space-between;gap:12px}.tags{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0}.tag{border:1px solid #385978;border-radius:999px;padding:4px 9px;font-size:12px;color:#bcd0e3}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.actions button,.actions a{border:1px solid #3e607e;background:#102942;color:white;text-decoration:none;border-radius:12px;padding:10px 12px;font-weight:700}.pack pre{white-space:pre-wrap;word-break:break-word;background:#071422;border-radius:14px;padding:12px;color:#dcecff}.notice{border:1px solid #17634f;background:#092c2a;border-radius:18px;padding:13px;color:#bfeade;margin:16px 0}@media(max-width:520px){h1{font-size:30px}.filters{grid-template-columns:1fr}.product{grid-template-columns:72px 1fr}.thumb{width:72px;height:72px}}
</style></head><body><main>
<div class="head"><div><div class="eyebrow">AI CROSS-BORDER RADAR</div><h1>今日潜力爆款</h1></div><button class="btn" onclick="refreshNow()">↻ 刷新</button></div>
<div class="status"><div><b id="state">正在连接</b><div class="muted" id="detail">请稍候</div></div><div><b id="count">0</b><div class="muted">候选商品</div></div></div>
<div class="filters"><input id="search" placeholder="搜索商品或类目" oninput="render()"><select id="platform" onchange="render()"><option value="">全部平台</option><option>eBay</option><option>Amazon</option><option>AliExpress</option><option>Temu</option><option>Shopee</option></select></div>
<div class="notice">⚡ 潜力概率是模型估算，用于缩小选品范围；上架前仍需核实供应链、侵权、资质和平台规则。演示模式数据不会冒充真实销量。</div>
<div id="list"></div><div id="pack"></div>
</main><script>
let rows=[];const api='';function headers(){const t=localStorage.getItem('radarToken')||'';return t?{'Authorization':'Bearer '+t,'Content-Type':'application/json'}:{'Content-Type':'application/json'}}
async function load(){try{const r=await fetch(api+'/api/products',{headers:headers()});if(r.status===401){const t=prompt('请输入 APP_ACCESS_TOKEN');if(t){localStorage.setItem('radarToken',t);return load()}}if(!r.ok)throw new Error(await r.text());const d=await r.json();rows=d.products||[];document.getElementById('state').textContent=d.mode;document.getElementById('state').className=d.mode==='真实接口模式'?'good':'';document.getElementById('detail').textContent='更新：'+new Date(d.updated_at).toLocaleString();document.getElementById('count').textContent=rows.length;render()}catch(e){document.getElementById('state').textContent='连接失败';document.getElementById('state').className='bad';document.getElementById('detail').textContent=e.message}}
async function refreshNow(){document.getElementById('state').textContent='正在刷新…';try{const r=await fetch(api+'/api/refresh',{method:'POST',headers:headers()});if(!r.ok)throw new Error(await r.text());await load()}catch(e){document.getElementById('state').textContent='刷新失败';document.getElementById('detail').textContent=e.message}}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function render(){const q=document.getElementById('search').value.toLowerCase(),p=document.getElementById('platform').value;const data=rows.filter(x=>(!p||x.platform===p)&&(!q||(x.title+x.category).toLowerCase().includes(q)));document.getElementById('list').innerHTML=data.map(x=>`<article class="product"><img class="thumb" src="${esc(x.image_url||'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2288%22 height=%2288%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%23142a42%22/%3E%3Ctext x=%2250%25%22 y=%2255%25%22 fill=%22%2393a8bd%22 font-size=%2214%22 text-anchor=%22middle%22%3E商品图%3C/text%3E%3C/svg%3E')}"><div><div class="row"><b>${esc(x.title)}</b><span class="score">${esc(x.score)}%</span></div><div class="tags"><span class="tag">${esc(x.platform)}</span><span class="tag">${esc(x.category)}</span><span class="tag">${esc(x.currency)} ${esc(x.price)}</span>${x.is_demo?'<span class="tag">演示</span>':''}</div><div class="muted">${esc(x.reason)}</div><div class="actions"><a href="${esc(x.source_url)}" target="_blank" rel="noopener">查看原链接</a><button onclick="makePack('${esc(x.id)}','Temu')">生成 Temu 资料</button><button onclick="makePack('${esc(x.id)}','Amazon')">生成 Amazon 资料</button><button onclick="makePack('${esc(x.id)}','Shopee')">生成 Shopee 资料</button></div></div></article>`).join('')||'<div class="status">没有符合条件的商品</div>'}
async function makePack(id,target){document.getElementById('pack').innerHTML='<div class="pack">正在生成 '+target+' 资料…</div>';try{const r=await fetch(api+'/api/listing-pack',{method:'POST',headers:headers(),body:JSON.stringify({product_id:id,target_platform:target})});if(!r.ok)throw new Error(await r.text());const d=await r.json();const text=JSON.stringify(d.listing_pack,null,2);document.getElementById('pack').innerHTML=`<div class="pack"><div class="row"><b>${target} 上架资料</b><button class="btn" onclick='navigator.clipboard.writeText(${JSON.stringify(text)})'>复制整套</button></div><pre>${esc(text)}</pre></div>`;document.getElementById('pack').scrollIntoView({behavior:'smooth'})}catch(e){document.getElementById('pack').innerHTML='<div class="pack bad">生成失败：'+esc(e.message)+'</div>'}}
load();
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return HTML


def scheduler() -> None:
    while True:
        time.sleep(max(3600, int(os.getenv("REFRESH_INTERVAL_HOURS", "6")) * 3600))
        try:
            refresh_data()
        except Exception as exc:
            print("scheduled refresh failed", exc)


@app.on_event("startup")
def startup() -> None:
    refresh_data()
    threading.Thread(target=scheduler, daemon=True, name="radar-scheduler").start()
