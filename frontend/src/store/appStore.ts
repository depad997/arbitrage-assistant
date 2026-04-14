import { create } from 'zustand';
import type {
  HealthStatus,
  MonitorStatus,
  AutomationStatus,
  ArbitrageOpportunity,
  TokenPrice,
  FundBalance,
  Strategy,
  ExecutionRecord,
  BridgeFee,
} from '@/types';

interface AppState {
  // Connection status
  isConnected: boolean;
  setConnected: (connected: boolean) => void;

  // Health
  health: HealthStatus | null;
  setHealth: (health: HealthStatus) => void;

  // Monitor
  monitorStatus: MonitorStatus | null;
  setMonitorStatus: (status: MonitorStatus) => void;

  // Automation
  automationStatus: AutomationStatus | null;
  setAutomationStatus: (status: AutomationStatus) => void;

  // Prices
  prices: TokenPrice[];
  setPrices: (prices: TokenPrice[]) => void;
  updatePrice: (price: TokenPrice) => void;

  // Opportunities
  opportunities: ArbitrageOpportunity[];
  setOpportunities: (opportunities: ArbitrageOpportunity[]) => void;
  addOpportunity: (opportunity: ArbitrageOpportunity) => void;

  // Bridge Fees
  bridgeFees: BridgeFee[];
  setBridgeFees: (fees: BridgeFee[]) => void;

  // Funds
  fundBalance: FundBalance | null;
  setFundBalance: (balance: FundBalance) => void;

  // Strategies
  strategies: Strategy[];
  setStrategies: (strategies: Strategy[]) => void;
  currentStrategy: string;
  setCurrentStrategy: (strategy: string) => void;

  // History
  history: ExecutionRecord[];
  setHistory: (records: ExecutionRecord[]) => void;
  addHistoryRecord: (record: ExecutionRecord) => void;

  // Settings
  settings: {
    refreshInterval: number;
    minProfitThreshold: number;
    maxPositionSize: number;
    slippageTolerance: number;
    autoExecute: boolean;
  };
  updateSettings: (settings: Partial<AppState['settings']>) => void;

  // Loading states
  isLoading: {
    dashboard: boolean;
    prices: boolean;
    opportunities: boolean;
    history: boolean;
  };
  setLoading: (key: keyof AppState['isLoading'], loading: boolean) => void;

  // Error
  error: string | null;
  setError: (error: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Connection
  isConnected: false,
  setConnected: (connected) => set({ isConnected: connected }),

  // Health
  health: null,
  setHealth: (health) => set({ health }),

  // Monitor
  monitorStatus: null,
  setMonitorStatus: (status) => set({ monitorStatus: status }),

  // Automation
  automationStatus: null,
  setAutomationStatus: (status) => set({ automationStatus: status }),

  // Prices
  prices: [],
  setPrices: (prices) => set({ prices }),
  updatePrice: (price) =>
    set((state) => ({
      prices: state.prices.some((p) => p.chain === price.chain && p.symbol === price.symbol)
        ? state.prices.map((p) =>
            p.chain === price.chain && p.symbol === price.symbol ? price : p
          )
        : [...state.prices, price],
    })),

  // Opportunities
  opportunities: [],
  setOpportunities: (opportunities) => set({ opportunities }),
  addOpportunity: (opportunity) =>
    set((state) => ({
      opportunities: [opportunity, ...state.opportunities].slice(0, 50),
    })),

  // Bridge Fees
  bridgeFees: [],
  setBridgeFees: (fees) => set({ bridgeFees: fees }),

  // Funds
  fundBalance: null,
  setFundBalance: (balance) => set({ fundBalance: balance }),

  // Strategies
  strategies: [],
  setStrategies: (strategies) => set({ strategies }),
  currentStrategy: 'balanced',
  setCurrentStrategy: (strategy) => set({ currentStrategy: strategy }),

  // History
  history: [],
  setHistory: (records) => set({ history: records }),
  addHistoryRecord: (record) =>
    set((state) => ({
      history: [record, ...state.history].slice(0, 100),
    })),

  // Settings
  settings: {
    refreshInterval: 5000,
    minProfitThreshold: 10,
    maxPositionSize: 10000,
    slippageTolerance: 0.5,
    autoExecute: false,
  },
  updateSettings: (newSettings) =>
    set((state) => ({
      settings: { ...state.settings, ...newSettings },
    })),

  // Loading
  isLoading: {
    dashboard: false,
    prices: false,
    opportunities: false,
    history: false,
  },
  setLoading: (key, loading) =>
    set((state) => ({
      isLoading: { ...state.isLoading, [key]: loading },
    })),

  // Error
  error: null,
  setError: (error) => set({ error }),
}));
