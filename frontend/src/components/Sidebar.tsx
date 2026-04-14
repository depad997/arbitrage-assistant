"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { StatusIndicator } from '@/components/ui/common';
import { useHealthCheck, useAutomationStatus } from '@/hooks';
import {
  LayoutDashboard,
  LineChart,
  TrendingUp,
  Play,
  Wallet,
  History,
  Settings,
  HelpCircle,
  Activity,
} from 'lucide-react';

const NAV_ITEMS = [
  { href: '/', label: '仪表盘', icon: LayoutDashboard },
  { href: '/prices', label: '价格监控', icon: LineChart },
  { href: '/opportunities', label: '套利机会', icon: TrendingUp },
  { href: '/execution', label: '执行控制', icon: Play },
  { href: '/wallet', label: '钱包管理', icon: Wallet },
  { href: '/history', label: '执行历史', icon: History },
];

export function Sidebar() {
  const pathname = usePathname();
  const { health } = useHealthCheck();
  const { status: automationStatus } = useAutomationStatus();

  const isSystemRunning = automationStatus?.state === 'running';

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-64 border-r bg-card">
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex h-16 items-center gap-3 border-b px-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <Activity className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="font-bold">套利助手</h1>
            <p className="text-xs text-muted-foreground">Chain Arbitrage</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-4">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* System Status */}
        <div className="border-t p-4">
          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium">系统状态</span>
              <StatusIndicator
                status={isSystemRunning ? 'running' : 'idle'}
                size="sm"
                pulse={isSystemRunning}
              />
            </div>
            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>版本</span>
                <span>v{health?.version || '1.0.0'}</span>
              </div>
              <div className="flex justify-between">
                <span>策略</span>
                <span>{automationStatus?.current_strategy || 'balanced'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Links */}
        <div className="border-t p-4">
          <div className="space-y-1">
            <Link
              href="/settings"
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <Settings className="h-4 w-4" />
              设置
            </Link>
            <Link
              href="/docs"
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <HelpCircle className="h-4 w-4" />
              API 文档
            </Link>
          </div>
        </div>
      </div>
    </aside>
  );
}
