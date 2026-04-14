# 链上套利助手 - 前端应用

基于 Next.js 14 的链上套利助手 Web 界面。

## 功能特性

### 1. 仪表盘 (Dashboard)
- 实时系统状态监控
- 总资产价值概览
- 今日收益统计
- 最近套利机会展示
- 服务健康状态

### 2. 价格监控 (Price Monitor)
- 多链代币实时价格
- 价格趋势图表
- 跨链价差对比
- 跨链桥费用监控

### 3. 套利机会 (Arbitrage Opportunities)
- 套利机会列表展示
- 卡片/表格视图切换
- 机会详情查看
- 一键执行功能
- 收益率排序

### 4. 执行控制 (Execution Control)
- 启动/暂停/停止控制
- 策略选择（保守/平衡/激进）
- 参数配置（滑点、金额限制）
- 实时状态显示

### 5. 钱包管理 (Wallet Manager)
- 多链钱包地址展示
- 资产余额查询
- 私钥配置

### 6. 执行历史 (Execution History)
- 交易记录列表
- 收益统计图表
- 成功率分析
- 失败日志查看
- 数据导出功能

## 技术栈

- **框架**: Next.js 14 (App Router)
- **UI**: Tailwind CSS + Radix UI
- **图表**: Recharts
- **状态管理**: Zustand
- **数据请求**: TanStack Query (React Query)
- **类型**: TypeScript

## 快速开始

### 环境要求
- Node.js >= 18.0.0
- 后端服务运行在 http://localhost:8500

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

访问 http://localhost:3000

### 构建生产版本

```bash
npm run build
npm start
```

## 项目结构

```
frontend/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── layout.tsx          # 根布局
│   │   ├── page.tsx            # 仪表盘首页
│   │   ├── prices/             # 价格监控页
│   │   ├── opportunities/     # 套利机会页
│   │   ├── execution/          # 执行控制页
│   │   ├── wallet/             # 钱包管理页
│   │   └── history/            # 执行历史页
│   ├── components/
│   │   ├── ui/                 # UI 基础组件
│   │   ├── dashboard/          # 仪表盘组件
│   │   ├── monitor/            # 价格监控组件
│   │   ├── execution/          # 执行相关组件
│   │   ├── wallet/             # 钱包组件
│   │   └── history/            # 历史记录组件
│   ├── hooks/                  # 自定义 Hooks
│   ├── services/               # API 服务
│   ├── store/                  # Zustand 状态管理
│   ├── types/                  # TypeScript 类型
│   └── lib/                    # 工具函数
├── public/                     # 静态资源
└── package.json
```

## 环境变量

创建 `.env.local` 文件:

```env
NEXT_PUBLIC_API_URL=http://localhost:8500
```

## API 对接

前端会自动代理请求到后端服务:
- 开发环境: http://localhost:3000 → http://localhost:8500
- 生产环境: 配置相应的后端地址

### 主要 API 端点

| 功能 | 端点 |
|------|------|
| 健康检查 | GET /health |
| 系统状态 | GET /api/monitor/status |
| 价格数据 | GET /api/prices/all |
| 套利机会 | GET /api/opportunities |
| 自动化状态 | GET /api/automation/status |
| 资金余额 | GET /api/funds/balance |
| 执行历史 | GET /api/automation/history |

## 设计规范

### 配色方案
- 背景: 深色主题 (#0a0a0f)
- 主色: 蓝色 (#3b82f6)
- 成功: 绿色 (#22c55e)
- 警告: 黄色 (#eab308)
- 错误: 红色 (#ef4444)

### 状态颜色
- 运行中: 绿色 + 脉冲动画
- 已暂停: 黄色
- 已停止: 灰色
- 错误: 红色

## 部署

### Vercel 部署

```bash
npm run build
```

然后在 Vercel 控制台配置:
- Build Command: `npm run build`
- Output Directory: `.next`

### Docker 部署

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:18-alpine AS runner
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

## 许可证

MIT
