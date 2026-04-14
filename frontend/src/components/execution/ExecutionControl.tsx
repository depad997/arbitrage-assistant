"use client";

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { StatusIndicator } from '@/components/ui/common';
import { useAutomationStatus, useStrategies, useMonitorStatus } from '@/hooks';
import { useAppStore } from '@/store';
import { cn } from '@/lib/utils';
import {
  Play,
  Pause,
  Square,
  AlertTriangle,
  Settings,
  Shield,
  Zap,
  Activity,
} from 'lucide-react';

const STRATEGIES = [
  { id: 'conservative', name: '保守策略', risk: 'low', description: '低风险低收益，适合新手' },
  { id: 'balanced', name: '平衡策略', risk: 'medium', description: '风险收益平衡' },
  { id: 'aggressive', name: '激进策略', risk: 'high', description: '高风险高收益' },
];

export function ExecutionControl() {
  const { status: automationStatus, start, stop, pause, resume, isStarting, isStopping } = useAutomationStatus();
  const { status: monitorStatus, start: startMonitor, stop: stopMonitor } = useMonitorStatus();
  const { strategies, currentStrategy, switchStrategy } = useStrategies();
  const { settings, updateSettings } = useAppStore();

  const [showSettings, setShowSettings] = useState(false);
  const [emergencyStop, setEmergencyStop] = useState(false);

  const isRunning = automationStatus?.state === 'running';
  const isPaused = automationStatus?.state === 'paused';
  const isIdle = automationStatus?.state === 'idle';

  const handleEmergencyStop = () => {
    if (confirm('确定要紧急停止所有操作吗？')) {
      setEmergencyStop(true);
      stop(true);
    }
  };

  const handleStart = () => {
    start({ strategy: currentStrategy, monitorOnly: false });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold">执行控制</h2>
          <p className="text-sm text-muted-foreground mt-1">
            控制套利系统运行状态和策略配置
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusIndicator
            status={isRunning ? 'running' : isPaused ? 'paused' : 'idle'}
            label={isRunning ? '运行中' : isPaused ? '已暂停' : '已停止'}
            size="lg"
          />
        </div>
      </div>

      {/* Control Panel */}
      <Card className={cn(
        'transition-all',
        isRunning && 'border-green-500/30 bg-green-500/5',
        isPaused && 'border-yellow-500/30 bg-yellow-500/5'
      )}>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" />
            运行控制
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Main Controls */}
          <div className="flex flex-wrap gap-3">
            {!isRunning ? (
              <Button
                variant="success"
                size="lg"
                onClick={handleStart}
                disabled={isStarting}
                className="gap-2"
              >
                {isStarting ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                启动
              </Button>
            ) : (
              <>
                <Button
                  variant="warning"
                  size="lg"
                  onClick={pause}
                  className="gap-2"
                >
                  <Pause className="h-4 w-4" />
                  暂停
                </Button>
                <Button
                  variant="secondary"
                  size="lg"
                  onClick={() => stop(false)}
                  disabled={isStopping}
                  className="gap-2"
                >
                  <Square className="h-4 w-4" />
                  停止
                </Button>
              </>
            )}

            {isPaused && (
              <Button
                variant="success"
                size="lg"
                onClick={resume}
                className="gap-2"
              >
                <Play className="h-4 w-4" />
                恢复
              </Button>
            )}

            <Button
              variant="danger"
              size="lg"
              onClick={handleEmergencyStop}
              disabled={!isRunning && !isPaused}
              className="gap-2"
            >
              <AlertTriangle className="h-4 w-4" />
              紧急停止
            </Button>
          </div>

          {/* Monitor Control */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="flex items-center gap-3">
              <div className={cn(
                'flex h-10 w-10 items-center justify-center rounded-full',
                monitorStatus?.is_running ? 'bg-green-500/20' : 'bg-muted'
              )}>
                <Activity className={cn(
                  'h-5 w-5',
                  monitorStatus?.is_running ? 'text-green-500' : 'text-muted-foreground'
                )} />
              </div>
              <div>
                <p className="font-medium">价格监控</p>
                <p className="text-sm text-muted-foreground">
                  {monitorStatus?.is_running ? '监控中' : '已停止'}
                </p>
              </div>
            </div>
            <Switch
              checked={monitorStatus?.is_running}
              onCheckedChange={(checked) => {
                if (checked) {
                  startMonitor();
                } else {
                  stopMonitor();
                }
              }}
            />
          </div>

          {/* Auto Execute */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="flex items-center gap-3">
              <div className={cn(
                'flex h-10 w-10 items-center justify-center rounded-full',
                settings.autoExecute ? 'bg-green-500/20' : 'bg-muted'
              )}>
                <Zap className={cn(
                  'h-5 w-5',
                  settings.autoExecute ? 'text-green-500' : 'text-muted-foreground'
                )} />
              </div>
              <div>
                <p className="font-medium">自动执行</p>
                <p className="text-sm text-muted-foreground">
                  {settings.autoExecute ? '检测到机会自动执行' : '仅监控不自动执行'}
                </p>
              </div>
            </div>
            <Switch
              checked={settings.autoExecute}
              onCheckedChange={(checked) => updateSettings({ autoExecute: checked })}
            />
          </div>

          {/* Stats */}
          {automationStatus && (
            <div className="grid gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-sm text-muted-foreground">处理机会</p>
                <p className="text-xl font-bold">{automationStatus.opportunities_processed}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-sm text-muted-foreground">成功执行</p>
                <p className="text-xl font-bold text-green-500">{automationStatus.successful_executions}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-sm text-muted-foreground">失败执行</p>
                <p className="text-xl font-bold text-red-500">{automationStatus.failed_executions}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-sm text-muted-foreground">总收益</p>
                <p className="text-xl font-bold text-green-500">
                  ${automationStatus.total_profit_usd?.toFixed(2) || '0.00'}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Strategy Selection */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Shield className="h-4 w-4" />
            策略选择
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            {STRATEGIES.map((strategy) => (
              <button
                key={strategy.id}
                onClick={() => switchStrategy(strategy.id)}
                className={cn(
                  'rounded-lg border p-4 text-left transition-all hover:border-primary',
                  currentStrategy === strategy.id
                    ? 'border-primary bg-primary/10'
                    : 'border-border'
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{strategy.name}</span>
                  <Badge
                    variant={
                      strategy.risk === 'low' ? 'success' :
                      strategy.risk === 'medium' ? 'warning' : 'destructive'
                    }
                  >
                    {strategy.risk === 'low' ? '低风险' :
                     strategy.risk === 'medium' ? '中风险' : '高风险'}
                  </Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{strategy.description}</p>
                {currentStrategy === strategy.id && (
                  <div className="mt-3 flex items-center gap-1 text-primary">
                    <div className="h-1 flex-1 rounded-full bg-primary" />
                    <div className="h-1 flex-1 rounded-full bg-primary" />
                    <div className="h-1 flex-1 rounded-full bg-primary" />
                  </div>
                )}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Settings */}
      <Card>
        <CardHeader>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="flex items-center justify-between w-full"
          >
            <CardTitle className="text-base flex items-center gap-2">
              <Settings className="h-4 w-4" />
              执行参数
            </CardTitle>
            <Badge variant="outline">{showSettings ? '收起' : '展开'}</Badge>
          </button>
        </CardHeader>
        {showSettings && (
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium">最小利润阈值 ($)</label>
                <Input
                  type="number"
                  value={settings.minProfitThreshold}
                  onChange={(e) => updateSettings({ minProfitThreshold: Number(e.target.value) })}
                  min={0}
                  step={10}
                />
                <p className="text-xs text-muted-foreground">只执行利润大于此值的套利</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">最大仓位 ($)</label>
                <Input
                  type="number"
                  value={settings.maxPositionSize}
                  onChange={(e) => updateSettings({ maxPositionSize: Number(e.target.value) })}
                  min={0}
                  step={100}
                />
                <p className="text-xs text-muted-foreground">单笔交易最大金额</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">滑点容忍 (%)</label>
                <Input
                  type="number"
                  value={settings.slippageTolerance}
                  onChange={(e) => updateSettings({ slippageTolerance: Number(e.target.value) })}
                  min={0.1}
                  max={10}
                  step={0.1}
                />
                <p className="text-xs text-muted-foreground">允许的价格偏差</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">刷新间隔 (ms)</label>
                <Input
                  type="number"
                  value={settings.refreshInterval}
                  onChange={(e) => updateSettings({ refreshInterval: Number(e.target.value) })}
                  min={1000}
                  max={60000}
                  step={1000}
                />
                <p className="text-xs text-muted-foreground">价格数据刷新频率</p>
              </div>
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}
