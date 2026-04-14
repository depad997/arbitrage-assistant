import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatNumber(value: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatPercent(value: number, decimals = 2): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;
}

export function formatCompactNumber(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return value.toFixed(2);
}

export function formatAddress(address: string, chars = 6): string {
  if (!address) return '';
  return `${address.slice(0, chars)}...${address.slice(-chars)}`;
}

export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function getTimeAgo(timestamp: string): string {
  const now = new Date();
  const date = new Date(timestamp);
  const diff = now.getTime() - date.getTime();
  
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  
  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'just now';
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    running: 'text-green-500',
    idle: 'text-gray-500',
    paused: 'text-yellow-500',
    stopping: 'text-orange-500',
    error: 'text-red-500',
    success: 'text-green-500',
    failed: 'text-red-500',
    pending: 'text-yellow-500',
  };
  return colors[status] || 'text-gray-500';
}

export function getStatusBgColor(status: string): string {
  const colors: Record<string, string> = {
    running: 'bg-green-500/20 text-green-500',
    idle: 'bg-gray-500/20 text-gray-500',
    paused: 'bg-yellow-500/20 text-yellow-500',
    stopping: 'bg-orange-500/20 text-orange-500',
    error: 'bg-red-500/20 text-red-500',
    success: 'bg-green-500/20 text-green-500',
    failed: 'bg-red-500/20 text-red-500',
    pending: 'bg-yellow-500/20 text-yellow-500',
  };
  return colors[status] || 'bg-gray-500/20 text-gray-500';
}

export function getRiskColor(level: string): string {
  const colors: Record<string, string> = {
    low: 'text-green-500',
    medium: 'text-yellow-500',
    high: 'text-red-500',
  };
  return colors[level] || 'text-gray-500';
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + '...';
}

export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null;
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

export function calculateProfitColor(profit: number): string {
  if (profit > 100) return 'text-green-500';
  if (profit > 0) return 'text-green-400';
  if (profit === 0) return 'text-gray-500';
  return 'text-red-500';
}
