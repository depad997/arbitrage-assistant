"use client";

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { LoadingSpinner, RefreshButton, EmptyState } from '@/components/ui/common';
import { usePrices, useBridgeFees } from '@/hooks';
import { formatCurrency, formatPercent, getTimeAgo } from '@/lib/utils';
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
  AreaChart,
  Area,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  ArrowRightLeft,
  Search,
  Filter,
} from 'lucide-react';
import type { TokenPrice, BridgeFee } from '@/types';

const MOCK_PRICE_HISTORY = [
  { time: '00:00', eth: 3450, btc: 67200, sol: 145 },
  { time: '04:00', eth: 3462, btc: 67350, sol: 147 },
  { time: '08:00', eth: 3480, btc: 67500, sol: 149 },
  { time: '12:00', eth: 3510, btc: 67800, sol: 152 },
  { time: '16:00', eth: 3495, btc: 67650, sol: 150 },
  { time: '20:00', eth: 3520, btc: 67900, sol: 153 },
];

const CHAINS = ['ethereum', 'arbitrum', 'optimism', 'polygon', 'bsc', 'avalanche'];

export function PriceMonitor() {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedChain, setSelectedChain] = useState<string>('all');
  const { prices, isLoading: isLoadingPrices, refetch: refetchPrices } = usePrices();
  const { fees, isLoading: isLoadingFees, refetch: refetchFees } = useBridgeFees();

  const filteredPrices = prices.filter((price) => {
    const matchesSearch =
      price.symbol.toLowerCase().includes(searchTerm.toLowerCase()) ||
      price.chain.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesChain = selectedChain === 'all' || price.chain === selectedChain;
    return matchesSearch && matchesChain;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold">价格监控</h2>
          <p className="text-sm text-muted-foreground mt-1">
            实时监控多链代币价格和跨链价差
          </p>
        </div>
        <RefreshButton onRefresh={refetchPrices} isLoading={isLoadingPrices} />
      </div>

      {/* Price Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            价格趋势
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={MOCK_PRICE_HISTORY}>
                <defs>
                  <linearGradient id="colorEth" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8884d8" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#8884d8" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorBtc" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#82ca9d" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#82ca9d" stopOpacity={0} />
                  </linearGradient>
                </defs>
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
                <Area
                  type="monotone"
                  dataKey="eth"
                  stroke="#8884d8"
                  fillOpacity={1}
                  fill="url(#colorEth)"
                  name="ETH ($)"
                />
                <Area
                  type="monotone"
                  dataKey="btc"
                  stroke="#82ca9d"
                  fillOpacity={1}
                  fill="url(#colorBtc)"
                  name="BTC ($)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs defaultValue="prices">
        <TabsList>
          <TabsTrigger value="prices">代币价格</TabsTrigger>
          <TabsTrigger value="spread">跨链价差</TabsTrigger>
        </TabsList>

        <TabsContent value="prices" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <CardTitle className="text-base">实时价格</CardTitle>
                <div className="flex gap-2">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="搜索代币..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="pl-9 w-[200px]"
                    />
                  </div>
                  <select
                    value={selectedChain}
                    onChange={(e) => setSelectedChain(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="all">全部链</option>
                    {CHAINS.map((chain) => (
                      <option key={chain} value={chain}>
                        {chain.charAt(0).toUpperCase() + chain.slice(1)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {isLoadingPrices ? (
                <div className="flex justify-center py-12">
                  <LoadingSpinner />
                </div>
              ) : filteredPrices.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>代币</TableHead>
                      <TableHead>链</TableHead>
                      <TableHead className="text-right">价格</TableHead>
                      <TableHead className="text-right">24h 变化</TableHead>
                      <TableHead className="text-right">24h 成交量</TableHead>
                      <TableHead className="text-right">更新时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredPrices.map((price, index) => (
                      <TableRow key={`${price.chain}-${price.symbol}-${index}`}>
                        <TableCell className="font-medium">{price.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="capitalize">
                            {price.chain}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCurrency(price.price)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            {price.price_change_24h && price.price_change_24h > 0 ? (
                              <TrendingUp className="h-4 w-4 text-green-500" />
                            ) : (
                              <TrendingDown className="h-4 w-4 text-red-500" />
                            )}
                            <span
                              className={
                                price.price_change_24h && price.price_change_24h > 0
                                  ? 'text-green-500'
                                  : 'text-red-500'
                              }
                            >
                              {price.price_change_24h
                                ? formatPercent(price.price_change_24h)
                                : '0%'}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">
                          {price.volume_24h ? formatCurrency(price.volume_24h) : '-'}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground text-xs">
                          {getTimeAgo(price.updated_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  icon={<Search className="h-8 w-8" />}
                  title="暂无价格数据"
                  description="后端服务可能未启动或无价格数据"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="spread" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <ArrowRightLeft className="h-4 w-4" />
                  跨链价差对比
                </CardTitle>
                <RefreshButton onRefresh={refetchFees} isLoading={isLoadingFees} />
              </div>
            </CardHeader>
            <CardContent>
              {isLoadingFees ? (
                <div className="flex justify-center py-12">
                  <LoadingSpinner />
                </div>
              ) : fees && fees.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>跨链桥</TableHead>
                      <TableHead>源链</TableHead>
                      <TableHead>目标链</TableHead>
                      <TableHead className="text-right">费用 (USD)</TableHead>
                      <TableHead className="text-right">费用率</TableHead>
                      <TableHead className="text-right">预计时间</TableHead>
                      <TableHead className="text-right">可靠性</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {fees.map((fee, index) => (
                      <TableRow key={`${fee.bridge}-${fee.source_chain}-${fee.target_chain}-${index}`}>
                        <TableCell className="font-medium">{fee.bridge}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="capitalize">
                            {fee.source_chain}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="capitalize">
                            {fee.target_chain}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatCurrency(fee.fee_usd)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {fee.fee_percentage.toFixed(3)}%
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {fee.estimated_time}
                        </TableCell>
                        <TableCell className="text-right">
                          <Badge
                            variant={fee.reliability > 0.9 ? 'success' : fee.reliability > 0.7 ? 'warning' : 'destructive'}
                          >
                            {(fee.reliability * 100).toFixed(0)}%
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  icon={<ArrowRightLeft className="h-8 w-8" />}
                  title="暂无跨链费用数据"
                  description="请确保后端服务正常运行"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
