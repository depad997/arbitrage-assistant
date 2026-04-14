"use client";

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingSpinner, RefreshButton, EmptyState } from '@/components/ui/common';
import { useExecutionHistory } from '@/hooks';
import { formatCurrency, formatTimestamp, cn } from '@/lib/utils';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from '@/components/ui/table';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  History,
  TrendingUp,
  TrendingDown,
  Filter,
  Download,
  CheckCircle,
  XCircle,
  Clock,
  ExternalLink,
} from 'lucide-react';

const MOCK_PROFIT_HISTORY = [
  { date: '1/1', profit: 120 },
  { date: '1/2', profit: 85 },
  { date: '1/3', profit: 156 },
  { date: '1/4', profit: 92 },
  { date: '1/5', profit: 178 },
  { date: '1/6', profit: 203 },
  { date: '1/7', profit: 145 },
];

const MOCK_STATUS_DISTRIBUTION = [
  { name: '成功', value: 85, color: '#22c55e' },
  { name: '失败', value: 10, color: '#ef4444' },
  { name: '待处理', value: 5, color: '#eab308' },
];

const STATUS_CONFIG = {
  success: { label: '成功', variant: 'success' as const, icon: CheckCircle },
  failed: { label: '失败', variant: 'destructive' as const, icon: XCircle },
  pending: { label: '处理中', variant: 'warning' as const, icon: Clock },
  cancelled: { label: '已取消', variant: 'secondary' as const, icon: XCircle },
};

export function HistoryModule() {
  const [limit, setLimit] = useState(50);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const { history, isLoading, refetch } = useExecutionHistory(limit);

  const filteredHistory = history?.filter((record) => {
    if (statusFilter === 'all') return true;
    return record.status === statusFilter;
  });

  const totalProfit = history?.reduce((sum, r) => sum + (r.net_profit_usd || 0), 0) || 0;
  const successCount = history?.filter((r) => r.status === 'success').length || 0;
  const failCount = history?.filter((r) => r.status === 'failed').length || 0;
  const successRate = history?.length ? (successCount / history.length * 100) : 0;

  const handleExport = () => {
    // TODO: 导出历史记录
    console.log('Export history');
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold">执行历史</h2>
          <p className="text-sm text-muted-foreground mt-1">
            查看所有套利执行的记录和收益统计
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onRefresh={refetch} isLoading={isLoading} />
          <Button variant="outline" className="gap-2" onClick={handleExport}>
            <Download className="h-4 w-4" />
            导出
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">总收益</p>
                <p className="text-2xl font-bold text-green-500">
                  +{formatCurrency(totalProfit)}
                </p>
              </div>
              <TrendingUp className="h-8 w-8 text-green-500/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">总交易数</p>
                <p className="text-2xl font-bold">{history?.length || 0}</p>
              </div>
              <History className="h-8 w-8 text-primary/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">成功率</p>
                <p className="text-2xl font-bold">{successRate.toFixed(1)}%</p>
              </div>
              <CheckCircle className="h-8 w-8 text-green-500/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">失败交易</p>
                <p className="text-2xl font-bold text-red-500">{failCount}</p>
              </div>
              <XCircle className="h-8 w-8 text-red-500/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Profit Trend */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">收益趋势</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[200px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={MOCK_PROFIT_HISTORY}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '8px',
                    }}
                    formatter={(value: number) => [formatCurrency(value), '收益']}
                  />
                  <Line
                    type="monotone"
                    dataKey="profit"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={{ fill: '#22c55e' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Status Distribution */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">交易状态分布</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div className="h-[200px] w-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={MOCK_STATUS_DISTRIBUTION}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                    >
                      {MOCK_STATUS_DISTRIBUTION.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '8px',
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-3">
                {MOCK_STATUS_DISTRIBUTION.map((item) => (
                  <div key={item.name} className="flex items-center gap-2">
                    <div
                      className="h-3 w-3 rounded-full"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="text-sm">{item.name}</span>
                    <span className="font-medium">{item.value}%</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filter */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <History className="h-4 w-4" />
              执行记录
            </CardTitle>
            <div className="flex gap-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="all">全部状态</option>
                <option value="success">成功</option>
                <option value="failed">失败</option>
                <option value="pending">处理中</option>
                <option value="cancelled">已取消</option>
              </select>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value={20}>20条</option>
                <option value={50}>50条</option>
                <option value={100}>100条</option>
              </select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : filteredHistory && filteredHistory.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>代币对</TableHead>
                  <TableHead>链</TableHead>
                  <TableHead className="text-right">利润</TableHead>
                  <TableHead className="text-right">Gas</TableHead>
                  <TableHead className="text-right">净收益</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>交易哈希</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredHistory.map((record, index) => {
                  const status = STATUS_CONFIG[record.status as keyof typeof STATUS_CONFIG] || STATUS_CONFIG.pending;
                  const StatusIcon = status.icon;

                  return (
                    <TableRow key={record.id || index}>
                      <TableCell className="text-xs whitespace-nowrap">
                        {formatTimestamp(record.executed_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Badge variant="outline" className="text-xs">
                            {record.token_in}
                          </Badge>
                          <span className="text-xs text-muted-foreground">→</span>
                          <Badge variant="outline" className="text-xs">
                            {record.token_out}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="capitalize text-xs">
                          {record.chain}
                        </Badge>
                      </TableCell>
                      <TableCell className={cn(
                        'text-right font-medium',
                        record.profit_usd > 0 ? 'text-green-500' : 'text-red-500'
                      )}>
                        {record.profit_usd > 0 ? '+' : ''}
                        {formatCurrency(record.profit_usd)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {formatCurrency(record.gas_cost_usd)}
                      </TableCell>
                      <TableCell className={cn(
                        'text-right font-medium',
                        record.net_profit_usd > 0 ? 'text-green-500' : 'text-red-500'
                      )}>
                        {record.net_profit_usd > 0 ? '+' : ''}
                        {formatCurrency(record.net_profit_usd)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={status.variant} className="gap-1">
                          <StatusIcon className="h-3 w-3" />
                          {status.label}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {record.tx_hash ? (
                          <button className="text-xs text-primary hover:underline">
                            {record.tx_hash.slice(0, 8)}...
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={<History className="h-12 w-12" />}
              title="暂无执行记录"
              description="开始套利后将在此显示执行历史"
            />
          )}
        </CardContent>
      </Card>

      {/* Failed Logs */}
      {failCount > 0 && (
        <Card className="border-red-500/30">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2 text-red-500">
              <XCircle className="h-4 w-4" />
              失败日志
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 font-mono text-sm">
              {history
                ?.filter((r) => r.status === 'failed')
                .slice(0, 5)
                .map((record, index) => (
                  <div
                    key={record.id || index}
                    className="flex items-center justify-between rounded-lg bg-red-500/10 p-3 text-red-500"
                  >
                    <div>
                      <span className="font-medium">{record.chain}</span>
                      <span className="mx-2">→</span>
                      <span>{record.token_in}/{record.token_out}</span>
                    </div>
                    <span>{record.error || 'Unknown error'}</span>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
