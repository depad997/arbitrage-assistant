"use client";

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingSpinner, RefreshButton, EmptyState } from '@/components/ui/common';
import { useOpportunities } from '@/hooks';
import { formatCurrency, formatPercent, getTimeAgo, cn } from '@/lib/utils';
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
} from 'recharts';
import {
  TrendingUp,
  Zap,
  AlertCircle,
  Play,
  ArrowRight,
  Filter,
  BarChart3,
} from 'lucide-react';
import type { ArbitrageOpportunity } from '@/types';

const MOCK_OPPORTUNITY_HISTORY = [
  { time: '00:00', opportunities: 12, avgProfit: 45 },
  { time: '04:00', opportunities: 8, avgProfit: 38 },
  { time: '08:00', opportunities: 15, avgProfit: 52 },
  { time: '12:00', opportunities: 20, avgProfit: 61 },
  { time: '16:00', opportunities: 18, avgProfit: 48 },
  { time: '20:00', opportunities: 14, avgProfit: 55 },
];

interface OpportunityCardProps {
  opportunity: ArbitrageOpportunity;
  onExecute?: (opp: ArbitrageOpportunity) => void;
}

function OpportunityCard({ opportunity, onExecute }: OpportunityCardProps) {
  const isHighProfit = opportunity.profit_usd > 100;
  const isHighConfidence = opportunity.confidence > 0.8;

  return (
    <Card className={cn(
      'transition-all hover:shadow-lg',
      isHighProfit && 'border-green-500/30 bg-green-500/5'
    )}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg">{opportunity.symbol}</span>
              <Badge
                variant={isHighProfit ? 'success' : 'secondary'}
                className="text-xs"
              >
                +{formatCurrency(opportunity.profit_usd)}
              </Badge>
              {isHighConfidence && (
                <Badge variant="outline" className="text-xs">
                  高置信度
                </Badge>
              )}
            </div>
            
            <div className="mt-2 flex items-center gap-2 text-sm">
              <Badge variant="outline" className="capitalize">
                {opportunity.source_chain}
              </Badge>
              <ArrowRight className="h-3 w-3 text-muted-foreground" />
              <Badge variant="outline" className="capitalize">
                {opportunity.target_chain}
              </Badge>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">收益率:</span>
                <span className={cn(
                  'font-medium',
                  opportunity.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'
                )}>
                  {formatPercent(opportunity.profit_percentage)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Gas:</span>
                <span>{formatCurrency(opportunity.estimated_gas)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">买入价:</span>
                <span>{formatCurrency(opportunity.buy_price)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">卖出价:</span>
                <span>{formatCurrency(opportunity.sell_price)}</span>
              </div>
            </div>

            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <span>{opportunity.source_dex}</span>
              <ArrowRight className="h-2 w-2" />
              <span>{opportunity.target_dex}</span>
            </div>
          </div>

          <div className="ml-4 flex flex-col items-end gap-2">
            <div className="text-right">
              <div className="text-xl font-bold text-green-500">
                +{formatCurrency(opportunity.net_profit)}
              </div>
              <div className="text-xs text-muted-foreground">
                净收益
              </div>
            </div>
            <Button
              size="sm"
              variant={isHighProfit ? 'success' : 'secondary'}
              onClick={() => onExecute?.(opportunity)}
              className="gap-1"
            >
              <Zap className="h-3 w-3" />
              执行
            </Button>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
          <span>检测时间: {getTimeAgo(opportunity.timestamp)}</span>
          <span>置信度: {(opportunity.confidence * 100).toFixed(0)}%</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function OpportunityModule() {
  const [viewMode, setViewMode] = useState<'table' | 'cards'>('table');
  const [minProfit, setMinProfit] = useState(10);
  const { opportunities, isLoading, refetch } = useOpportunities(minProfit, 20);

  const handleExecute = (opp: ArbitrageOpportunity) => {
    console.log('Execute opportunity:', opp);
    // TODO: 调用执行 API
  };

  const profitableOpps = opportunities?.filter(o => o.profit_usd > minProfit) || [];
  const totalPotentialProfit = profitableOpps.reduce((sum, o) => sum + o.profit_usd, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold">套利机会</h2>
          <p className="text-sm text-muted-foreground mt-1">
            检测跨链/DEX 套利机会，支持一键执行
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={minProfit}
            onChange={(e) => setMinProfit(Number(e.target.value))}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value={0}>全部机会</option>
            <option value={10}>利润 > $10</option>
            <option value={50}>利润 > $50</option>
            <option value={100}>利润 > $100</option>
            <option value={500}>利润 > $500</option>
          </select>
          <RefreshButton onRefresh={refetch} isLoading={isLoading} />
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">检测到的机会</p>
                <p className="text-2xl font-bold">{profitableOpps.length}</p>
              </div>
              <AlertCircle className="h-8 w-8 text-primary/50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">潜在总利润</p>
                <p className="text-2xl font-bold text-green-500">
                  {formatCurrency(totalPotentialProfit)}
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
                <p className="text-sm text-muted-foreground">平均利润率</p>
                <p className="text-2xl font-bold">
                  {profitableOpps.length > 0
                    ? formatPercent(
                        profitableOpps.reduce((sum, o) => sum + o.profit_percentage, 0) /
                          profitableOpps.length
                      )
                    : '0%'}
                </p>
              </div>
              <BarChart3 className="h-8 w-8 text-yellow-500/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">机会趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[200px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={MOCK_OPPORTUNITY_HISTORY}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px',
                  }}
                />
                <Bar dataKey="opportunities" fill="#8884d8" name="机会数" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* View Mode Toggle */}
      <div className="flex gap-2">
        <Button
          variant={viewMode === 'table' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setViewMode('table')}
        >
          表格视图
        </Button>
        <Button
          variant={viewMode === 'cards' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setViewMode('cards')}
        >
          卡片视图
        </Button>
      </div>

      {/* Opportunities List */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      ) : profitableOpps.length > 0 ? (
        viewMode === 'table' ? (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代币</TableHead>
                    <TableHead>路径</TableHead>
                    <TableHead className="text-right">利润</TableHead>
                    <TableHead className="text-right">收益率</TableHead>
                    <TableHead className="text-right">Gas</TableHead>
                    <TableHead className="text-right">置信度</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profitableOpps.map((opp, index) => (
                    <TableRow key={opp.id || index}>
                      <TableCell className="font-medium">{opp.symbol}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1 text-sm">
                          <Badge variant="outline" className="capitalize text-xs">
                            {opp.source_chain}
                          </Badge>
                          <ArrowRight className="h-3 w-3 text-muted-foreground" />
                          <Badge variant="outline" className="capitalize text-xs">
                            {opp.target_chain}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className="text-right text-green-500 font-medium">
                        +{formatCurrency(opp.profit_usd)}
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={cn(
                          opp.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'
                        )}>
                          {formatPercent(opp.profit_percentage)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {formatCurrency(opp.estimated_gas)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge
                          variant={opp.confidence > 0.8 ? 'success' : opp.confidence > 0.5 ? 'warning' : 'secondary'}
                        >
                          {(opp.confidence * 100).toFixed(0)}%
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="success"
                          onClick={() => handleExecute(opp)}
                        >
                          <Zap className="h-3 w-3 mr-1" />
                          执行
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {profitableOpps.map((opp, index) => (
              <OpportunityCard
                key={opp.id || index}
                opportunity={opp}
                onExecute={handleExecute}
              />
            ))}
          </div>
        )
      ) : (
        <EmptyState
          icon={<TrendingUp className="h-12 w-12" />}
          title="暂无符合条件的套利机会"
          description={`当前没有利润超过 ${formatCurrency(minProfit)} 的机会`}
          action={
            <Button variant="outline" onClick={refetch}>
              重新扫描
            </Button>
          }
        />
      )}
    </div>
  );
}
