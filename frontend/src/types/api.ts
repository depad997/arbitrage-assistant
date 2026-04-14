// API Response Types
export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// Health Check
export interface HealthStatus {
  status: string;
  version: string;
  services: {
    price_monitor: boolean;
    alert: boolean;
    bridge_fee: boolean;
    opportunity: boolean;
    monitor: boolean;
  };
}

// Monitor Status
export interface MonitorStatus {
  is_running: boolean;
  is_paused: boolean;
  start_time?: string;
  last_scan_time?: string;
  opportunities_found: number;
  alerts_sent: number;
}

// Token Price
export interface TokenPrice {
  symbol: string;
  chain: string;
  price: number;
  price_change_24h?: number;
  volume_24h?: number;
  liquidity?: number;
  updated_at: string;
}

// Arbitrage Opportunity
export interface ArbitrageOpportunity {
  id: string;
  symbol: string;
  source_chain: string;
  target_chain: string;
  source_dex: string;
  target_dex: string;
  buy_price: number;
  sell_price: number;
  profit_usd: number;
  profit_percentage: number;
  confidence: number;
  estimated_gas: number;
  net_profit: number;
  timestamp: string;
  route?: string[];
}

// Bridge Fee
export interface BridgeFee {
  bridge: string;
  source_chain: string;
  target_chain: string;
  fee_usd: number;
  fee_percentage: number;
  estimated_time: string;
  reliability: number;
}

// Fund Balance
export interface ChainBalance {
  chain: string;
  address: string;
  native_balance: number;
  native_balance_usd: number;
  tokens: TokenBalance[];
  total_value_usd: number;
}

export interface TokenBalance {
  symbol: string;
  address: string;
  balance: number;
  balance_usd: number;
  price: number;
}

export interface FundBalance {
  total_value_usd: number;
  chains: ChainBalance[];
  last_updated: string;
}

// Automation Status
export interface AutomationStatus {
  state: 'idle' | 'starting' | 'running' | 'paused' | 'stopping' | 'error';
  current_strategy: string;
  opportunities_processed: number;
  successful_executions: number;
  failed_executions: number;
  total_profit_usd: number;
  uptime_seconds: number;
}

// Strategy
export interface Strategy {
  id: string;
  name: string;
  description: string;
  risk_level: 'low' | 'medium' | 'high';
  min_profit_threshold: number;
  max_position_size: number;
  enabled: boolean;
}

// Execution History
export interface ExecutionRecord {
  id: string;
  opportunity_id: string;
  chain: string;
  token_in: string;
  token_out: string;
  amount_in: number;
  amount_out: number;
  profit_usd: number;
  profit_pct: number;
  gas_cost_usd: number;
  net_profit_usd: number;
  status: 'pending' | 'success' | 'failed' | 'cancelled';
  execution_mode: string;
  tx_hash?: string;
  error?: string;
  executed_at: string;
}

// System Stats
export interface SystemStats {
  system: {
    uptime_seconds: number;
    opportunities_found: number;
    successful_trades: number;
    failed_trades: number;
    total_profit_usd: number;
  };
  strategy: {
    current_strategy: string;
    strategies_used: string[];
    performance_by_strategy: Record<string, number>;
  };
  funds: {
    total_value_usd: number;
    available_usd: number;
    locked_usd: number;
  };
  scheduler: {
    queued_tasks: number;
    completed_tasks: number;
    failed_tasks: number;
  };
}

// Chain Config
export interface ChainConfig {
  chain_id: number;
  chain_name: string;
  native_token: string;
  is_evm: boolean;
  explorer_url: string;
  dex_list: string[];
  rpc_url: string;
}

// Alert
export interface Alert {
  id: string;
  level: 'debug' | 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  data?: any;
  created_at: string;
}

// WebSocket Message
export interface WSMessage {
  type: 'price' | 'opportunity' | 'alert' | 'status';
  data: any;
  timestamp: string;
}
