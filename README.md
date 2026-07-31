# 跨境爆款雷达

联网跨境选品雷达：每天刷新候选商品、展示来源平台和原链接，并为 Temu、Amazon、Shopee 生成可复制的上架资料。

> 当前项目处于第一版测试阶段。平台接口未配置时会明确显示演示模式，不会把模拟数据冒充真实爆款。

## 无银行卡上线方案

本项目现在使用 GitHub Pages + GitHub Actions：

- `docs/`：手机网页。
- `scripts/refresh_products.py`：每日刷新候选商品。
- `.github/workflows/radar-pages.yml`：每天 06:00（北京时间）自动刷新并发布网页。
- `.github/workflows/android-apk.yml`：自动构建 Android 测试 APK。

## 启用网站

进入仓库：

1. Settings
2. Pages
3. Build and deployment
4. Source 选择 GitHub Actions

网站地址：

```text
https://tanbin168.github.io/cross-border-radar/
```

## 下载 APK

进入仓库 Actions，打开“构建 Android 安装包”，运行完成后在 Artifacts 下载：

```text
跨境爆款雷达-Android测试安装包
```

## 接入真实平台数据

在仓库 Settings → Secrets and variables → Actions 中配置平台凭据。当前已支持：

- eBay 官方 Browse API：`EBAY_CLIENT_ID`、`EBAY_CLIENT_SECRET`
- Temu 授权数据接口：`TEMU_DATA_ENDPOINT`、`TEMU_ACCESS_TOKEN`
- Shopee 授权数据接口：`SHOPEE_DATA_ENDPOINT`、`SHOPEE_ACCESS_TOKEN`
- AliExpress 授权数据接口：`ALI_DATA_ENDPOINT`、`ALI_ACCESS_TOKEN`
- Amazon 授权数据接口：`AMAZON_DATA_ENDPOINT`、`AMAZON_ACCESS_TOKEN`

没有配置真实数据接口时，页面会显示“演示模式”。
