"use client";

import { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner, RefreshButton, MetricCard } from '@/components/ui/common';
import { useFundBalance } from '@/hooks';
import { formatCurrency, formatAddress, cn } from '@/lib/utils';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from '@/components/ui/table';
import {
  Wallet,
  Copy,
  Eye,
  EyeOff,
  ExternalLink,
  Plus,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

const MOCK_WALLET = {
  address: '0x1234567890abcdef1234567890abcdef12345678',
  isConfigured: true,
};

const CHAINS = [
  { id: 'ethereum', name: 'Ethereum', symbol: 'ETH', color: '#627EEA' },
  { id: 'arbitrum', name: 'Arbitrum', symbol: 'ETH', color: '#28A0F0' },
  { id: 'optimism', name: 'Optimism', symbol: 'ETH', color: '#FF0420' },
  { id: 'polygon', name: 'Polygon', symbol: 'MATIC', color: '#8247E5' },
  { id: 'bsc', name: 'BNB Chain', symbol: 'BNB', color: '#F3BA2F' },
  { id: 'avalanche', name: 'Avalanche', symbol: 'AVAX', color: '#E84142' },
];

export function WalletManager() {
  const { balance, isLoading, refetch } = useFundBalance();
  const [showPrivateKey, setShowPrivateKey] = useState(false);
  const [expandedChain, setExpandedChain] = useState<string | null>(null);

  const totalValue = balance?.total_value_usd || 0;

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold">钱包管理</h2>
          <p className="text-sm text-muted-foreground mt-1">
            管理多链钱包地址和资产余额
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onRefresh={refetch} isLoading={isLoading} />
          <Button variant="outline" className="gap-2">
            <Plus className="h-4 w-4" />
            添加钱包
          </Button>
        </div>
      </div>

      {/* Total Value */}
      <Card className="bg-gradient-to-r from-primary/10 to-transparent">
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">总资产价值</p>
              <p className="text-3xl font-bold mt-1">
                {isLoading ? (
                  <span className="animate-pulse">Loading...</span>
                ) : (
                  formatCurrency(totalValue)
                )}
              </p>
            </div>
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/20">
              <Wallet className="h-7 w-7 text-primary" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Main Wallet Address */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Wallet className="h-4 w-4" />
            主钱包
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                <Wallet className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="font-medium font-mono">
                  {formatAddress(MOCK_WALLET.address, 10)}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant={MOCK_WALLET.isConfigured ? 'success' : 'warning'}>
                    {MOCK_WALLET.isConfigured ? '已配置' : '未配置'}
                  </Badge>
                  <Badge variant="outline">EVM 兼容</Badge>
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => handleCopy(MOCK_WALLET.address)}
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowPrivateKey(!showPrivateKey)}
              >
                {showPrivateKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </Button>
              <Button variant="ghost" size="icon">
                <ExternalLink className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {showPrivateKey && (
            <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5" />
                <div>
                  <p className="font-medium text-yellow-500">警告：敏感信息</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    请勿与任何人分享您的私钥
                  </p>
                  <div className="mt-3 flex items-center gap-2">
                    <code className="flex-1 rounded bg-black/50 px-3 py-2 font-mono text-sm">
                      •••••••••••••••••••••••••••••••
                    </code>
                    <Button variant="outline" size="sm" className="gap-1">
                      <Copy className="h-3 w-3" />
                      复制
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Chain Balances */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">各链资产</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : (
            <div className="space-y-3">
              {CHAINS.map((chain) => {
                const chainBalance = balance?.chains?.find(
                  (b) => b.chain.toLowerCase() === chain.id.toLowerCase()
                );
                const isExpanded = expandedChain === chain.id;

                return (
                  <div
                    key={chain.id}
                    className="rounded-lg border transition-all"
                  >
                    <button
                      onClick={() => setExpandedChain(isExpanded ? null : chain.id)}
                      className="flex w-full items-center justify-between p-4 hover:bg-muted/50"
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className="h-10 w-10 rounded-full flex items-center justify-center text-white font-bold"
                          style={{ backgroundColor: chain.color }}
                        >
                          {chain.symbol.charAt(0)}
                        </div>
                        <div className="text-left">
                          <p className="font-medium">{chain.name}</p>
                          <p className="text-sm text-muted-foreground">
                            {chainBalance ? (
                              <>
                                {chainBalance.native_balance.toFixed(4)} {chain.symbol}
                              </>
                            ) : (
                              '未连接'
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <p className="font-medium">
                            {chainBalance
                              ? formatCurrency(chainBalance.total_value_usd)
                              : '-'}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            ≈ ${chainBalance?.native_balance_usd?.toFixed(2) || '0.00'}
                          </p>
                        </div>
                        {isExpanded ? (
                          <ChevronUp className="h-5 w-5 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-5 w-5 text-muted-foreground" />
                        )}
                      </div>
                    </button>

                    {isExpanded && chainBalance && (
                      <div className="border-t p-4">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>代币</TableHead>
                              <TableHead className="text-right">余额</TableHead>
                              <TableHead className="text-right">价值</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            <TableRow>
                              <TableCell className="font-medium">
                                <div className="flex items-center gap-2">
                                  <div
                                    className="h-6 w-6 rounded-full"
                                    style={{ backgroundColor: chain.color }}
                                  />
                                  {chain.symbol}
                                </div>
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {chainBalance.native_balance.toFixed(6)}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {formatCurrency(chainBalance.native_balance_usd)}
                              </TableCell>
                            </TableRow>
                            {chainBalance.tokens?.map((token, index) => (
                              <TableRow key={`${token.symbol}-${index}`}>
                                <TableCell className="font-medium">
                                  <div className="flex items-center gap-2">
                                    <div className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-xs">
                                      {token.symbol.slice(0, 2)}
                                    </div>
                                    {token.symbol}
                                  </div>
                                </TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {token.balance.toFixed(6)}
                                </TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {formatCurrency(token.balance_usd)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Private Key Configuration */}
      <Card className="border-yellow-500/30">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-yellow-500" />
            私钥配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            配置您的钱包私钥以启用自动交易。密钥将安全存储在本地。
          </p>
          <div className="space-y-2">
            <label className="text-sm font-medium">私钥</label>
            <Input
              type="password"
              placeholder="请输入私钥 (0x...)"
              className="font-mono"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">确认密码</label>
            <Input type="password" placeholder="请输入确认密码" />
          </div>
          <Button className="gap-2">
            <RefreshCw className="h-4 w-4" />
            更新配置
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function AlertTriangle({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}
