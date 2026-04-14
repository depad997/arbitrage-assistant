# 链上套利助手 🚀

一个多链套利机会检测和执行系统。

## ✨ 功能特性

- 📊 多链价格监控（16条链支持）
- 💰 套利机会实时检测
- 🔗 跨链桥费用估算
- 📱 飞书通知推送
- 💵 链上真实价格（来自 Uniswap V3）

## 🌐 在线访问

- **前端界面**: https://你的域名/web
- **API文档**: https://你的域名/docs
- **价格API**: https://你的域名/api/prices/onchain/{chain}

## 🚀 一键部署（Railway - 推荐）

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

### 部署步骤：

1. 点击上方按钮或访问 https://railway.app
2. 使用 GitHub 账号登录
3. 点击 "New Project" → "Deploy from GitHub repo"
4. 选择上传的代码仓库
5. 等待部署完成，获得永久访问地址

## 📦 本地运行

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8500
```

## 🔧 支持的链

| 链 | 状态 | 链 | 状态 |
|---|---|---|---|
| Ethereum | ✅ | Arbitrum | ✅ |
| Optimism | ✅ | Base | ✅ |
| BSC | ✅ | Polygon | ✅ |
| Avalanche | ✅ | Fantom | ✅ |
| Scroll | ✅ | Mantle | ✅ |
| Linea | ✅ | Berachain | ✅ |
| Moonbeam | ✅ | Solana | ✅ |
| Sui | ✅ | Aptos | ✅ |

## 📝 更新日志

- **v1.0.0** - 初始版本
  - 多链价格监控
  - 套利机会检测
  - 链上真实价格获取
  - 飞书通知

---

Made with ❤️ for DeFi
