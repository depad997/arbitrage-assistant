import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  ApiResponse,
  HealthStatus,
  MonitorStatus,
  TokenPrice,
  ArbitrageOpportunity,
  BridgeFee,
  FundBalance,
  AutomationStatus,
  Strategy,
  ExecutionRecord,
  SystemStats,
  ChainConfig,
} from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8500';

class ApiService {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        console.error('API Error:', error.message);
        return Promise.reject(error);
      }
    );
  }

  // ==================== System ====================

  async getHealth(): Promise<ApiResponse<HealthStatus>> {
    const response = await this.client.get('/health');
    return response.data;
  }

  async getStatus(): Promise<ApiResponse<any>> {
    const response = await this.client.get('/api/status');
    return response.data;
  }

  // ==================== Monitor ====================

  async getMonitorStatus(): Promise<ApiResponse<MonitorStatus>> {
    const response = await this.client.get('/api/monitor/status');
    return response.data;
  }

  async startMonitor(): Promise<ApiResponse<MonitorStatus>> {
    const response = await this.client.post('/api/monitor/start');
    return response.data;
  }

  async stopMonitor(): Promise<ApiResponse<MonitorStatus>> {
    const response = await this.client.post('/api/monitor/stop');
    return response.data;
  }

  async pauseMonitor(): Promise<ApiResponse<MonitorStatus>> {
    const response = await this.client.post('/api/monitor/pause');
    return response.data;
  }

  async resumeMonitor(): Promise<ApiResponse<MonitorStatus>> {
    const response = await this.client.post('/api/monitor/resume');
    return response.data;
  }

  // ==================== Prices ====================

  async getPrices(chain?: string): Promise<ApiResponse<{ prices: TokenPrice[] }>> {
    const url = chain ? `/api/prices/${chain}` : '/api/prices/all';
    const response = await this.client.get(url);
    return response.data;
  }

  async getPrice(chain: string, token: string): Promise<ApiResponse<TokenPrice>> {
    const response = await this.client.get(`/api/v1/prices/${chain}/${token}`);
    return response.data;
  }

  // ==================== Opportunities ====================

  async getOpportunities(
    minProfit = 10,
    limit = 10
  ): Promise<ApiResponse<{ opportunities: ArbitrageOpportunity[]; count: number }>> {
    const response = await this.client.get('/api/opportunities', {
      params: { min_profit: minProfit, limit },
    });
    return response.data;
  }

  async scanOpportunities(
    symbols?: string[],
    chains?: string[]
  ): Promise<ApiResponse<{ opportunities: ArbitrageOpportunity[]; count: number }>> {
    const response = await this.client.post('/api/opportunities/scan', null, {
      params: {
        symbols: symbols?.join(','),
        chains: chains?.join(','),
      },
    });
    return response.data;
  }

  async getOpportunityDetail(id: string): Promise<ApiResponse<ArbitrageOpportunity>> {
    const response = await this.client.get(`/api/opportunities/${id}`);
    return response.data;
  }

  // ==================== Bridge Fees ====================

  async getBridgeFees(
    src: string,
    dst: string
  ): Promise<ApiResponse<{ fees: BridgeFee[] }>> {
    const response = await this.client.get(`/api/bridge-fees/compare/${src}/${dst}`);
    return response.data;
  }

  async getAllBridgeFees(): Promise<ApiResponse<{ fees: BridgeFee[] }>> {
    const response = await this.client.get('/api/bridge-fees/all');
    return response.data;
  }

  // ==================== Config ====================

  async getChains(): Promise<ApiResponse<{ chains: ChainConfig[] }>> {
    const response = await this.client.get('/api/v1/config/chains');
    return response.data;
  }

  // ==================== Automation ====================

  async startAutomation(
    strategy?: string,
    monitorOnly = false
  ): Promise<ApiResponse<AutomationStatus>> {
    const response = await this.client.post('/api/automation/start', {
      strategy,
      monitor_only: monitorOnly,
    });
    return response.data;
  }

  async stopAutomation(emergency = false): Promise<ApiResponse<AutomationStatus>> {
    const response = await this.client.post('/api/automation/stop', { emergency });
    return response.data;
  }

  async pauseAutomation(): Promise<ApiResponse<AutomationStatus>> {
    const response = await this.client.post('/api/automation/pause');
    return response.data;
  }

  async resumeAutomation(): Promise<ApiResponse<AutomationStatus>> {
    const response = await this.client.post('/api/automation/resume');
    return response.data;
  }

  async getAutomationStatus(): Promise<ApiResponse<AutomationStatus>> {
    const response = await this.client.get('/api/automation/status');
    return response.data;
  }

  async getAutomationStats(): Promise<ApiResponse<SystemStats>> {
    const response = await this.client.get('/api/automation/stats');
    return response.data;
  }

  // ==================== Funds ====================

  async getFundBalance(): Promise<ApiResponse<FundBalance>> {
    const response = await this.client.get('/api/funds/balance');
    return response.data;
  }

  // ==================== Strategies ====================

  async getStrategies(): Promise<ApiResponse<{ strategies: Strategy[] }>> {
    const response = await this.client.get('/api/strategy/list');
    return response.data;
  }

  async switchStrategy(strategy: string): Promise<ApiResponse<any>> {
    const response = await this.client.post('/api/strategy/switch', { strategy });
    return response.data;
  }

  // ==================== History ====================

  async getExecutionHistory(
    limit = 100,
    chain?: string,
    startDate?: string,
    endDate?: string
  ): Promise<ApiResponse<{ records: ExecutionRecord[]; count: number }>> {
    const response = await this.client.get('/api/automation/history', {
      params: { limit, chain, start_date: startDate, end_date: endDate },
    });
    return response.data;
  }
}

export const api = new ApiService();
export default api;
