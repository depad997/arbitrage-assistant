"use client";

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { StatusIndicator, MetricCard, LoadingSpinner } from '@/components/ui/common';
import { useHealthCheck, useAutomationStatus, useFundBalance, useOpportunities } from '@/hooks';
import { formatCurrency, formatCompactNumber, getTimeAgo } from '@/lib/utils';
import {
  Activity,
  Wallet,
  TrendingUp,
  Zap,
  AlertCircle,
  ArrowRight,
} from 'lucide-react';

export function DashboardOverview() {
  const { health, refetch: refetchHealth } = useHealthCheck();
  const { status: automationStatus } = useAutomationStatus();
  const { balance } = useFundBalance();
  const { opportunities, isLoading: isLoadingOpps } = useOpportunities(10, 5);

  const isSystemRunning = automationStatus?.state === 'running';

  return (
    <div className="space-y-6">
      {/* Status Header */}
      <Card className="border-primary/20 bg-gradient-to-r from-primary/5 to-transparent">
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                <Activity className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h2 className="text-xl font-bold">链上套利助手</h2>
                <div className="flex items-center gap-2 mt-1">
                  <StatusIndicator
                    status={isSystemRunning ? 'running' : 'idle'}
                    label={isSystemRunning ? '运行中' : '已停止'}
                  />
                  {health && (
                    <span className="text-sm text-muted-foreground">
                      v{health.version}
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <Badge variant={isSystemRunning ? 'success' : 'secondary'}>
                {automationStatus?.current_strategy || 'balanced'}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Metrics Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="总资产价值"
          value={formatCurrency(balance?.total_value_usd || 0)}
          icon={<Wallet className="h-4 w-4" />}
        />
        <MetricCard
          title="今日收益"
          value={formatCurrency(automationStatus?.total_profit_usd || 0)}
          change={2.5}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <MetricCard
          title="成功交易"
          value={automationStatus?.successful_executions || 0}
          icon={<Zap className="h-4 w-4" />}
        />
        <MetricCard
          title="待处理机会"
          value={opportunities?.length || 0}
          icon={<AlertCircle className="h-4 w-4" />}
        />
      </div>

      {/* Quick Actions & Recent Activity */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent Opportunities */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">最近套利机会</CardTitle>
            <Badge variant="outline">{opportunities?.length || 0} 个</Badge>
          </CardHeader>
          <CardContent>
            {isLoadingOpps ? (
              <div className="flex justify-center py-8">
                <LoadingSpinner />
              </div>
            ) : opportunities && opportunities.length > 0 ? (
              <div className="space-y-3">
                {opportunities.slice(0, 5).map((opp, index) => (
                  <div
                    key={opp.id || index}
                    className="flex items-center justify-between rounded-lg border p-3 hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{opp.symbol}</span>
                        <Badge variant={opp.profit_usd > 100 ? 'success' : 'secondary'} className="text-xs">
                          {opp.profit_percentage?.toFixed(2)}%
                        </Badge>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{opp.source_chain}</span>
                        <ArrowRight className="h-3 w-3" />
                        <span>{opp.target_chain}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-medium text-green-500">
                        +{formatCurrency(opp.profit_usd)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {getTimeAgo(opp.timestamp)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-muted-foreground">
                暂无套利机会
              </div>
            )}
          </CardContent>
        </Card>

        {/* System Stats */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">系统统计</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">运行时间</span>
                <span className="font-medium">
                  {automationStatus?.uptime_seconds
                    ? `${Math.floor(automationStatus.uptime_seconds / 3600)}h ${Math.floor((automationStatus.uptime_seconds % 3600) / 60)}m`
                    : '0h 0m'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">处理机会数</span>
                <span className="font-medium">
                  {automationStatus?.opportunities_processed || 0}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">成功执行</span>
                <span className="font-medium text-green-500">
                  {automationStatus?.successful_executions || 0}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">失败执行</span>
                <span className="font-medium text-red-500">
                  {automationStatus?.failed_executions || 0}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">成功率</span>
                <span className="font-medium">
                  {automationStatus?.successful_executions && automationStatus?.failed_executions
                    ? `${(
                        (automationStatus.successful_executions /
                          (automationStatus.successful_executions + automationStatus.failed_executions)) *
                        100
                      ).toFixed(1)}%`
                    : '0%'}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Service Status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">服务状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {health?.services &&
              Object.entries(health.services).map(([service, isHealthy]) => (
                <div
                  key={service}
                  className="flex items-center justify-between rounded-lg border p-3"
                >
                  <span className="text-sm capitalize">
                    {service.replace('_', ' ')}
                  </span>
                  <StatusIndicator
                    status={isHealthy ? 'running' : 'error'}
                    size="sm"
                  />
                </div>
              ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
