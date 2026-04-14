import { useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAppStore } from '@/store';
import api from '@/services/api';

export function useHealthCheck() {
  const { setHealth, setConnected } = useAppStore();

  const { data, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
    refetchInterval: 30000,
    retry: 3,
  });

  useEffect(() => {
    if (data?.success && data.data) {
      setHealth(data.data);
      setConnected(true);
    } else {
      setConnected(false);
    }
  }, [data, setHealth, setConnected]);

  return { health: data?.data, refetch };
}

export function useMonitorStatus() {
  const { monitorStatus, setMonitorStatus } = useAppStore();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['monitor-status'],
    queryFn: () => api.getMonitorStatus(),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (data?.success && data.data) {
      setMonitorStatus(data.data);
    }
  }, [data, setMonitorStatus]);

  const startMutation = useMutation({
    mutationFn: () => api.startMonitor(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor-status'] }),
  });

  const stopMutation = useMutation({
    mutationFn: () => api.stopMonitor(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor-status'] }),
  });

  const pauseMutation = useMutation({
    mutationFn: () => api.pauseMonitor(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor-status'] }),
  });

  const resumeMutation = useMutation({
    mutationFn: () => api.resumeMonitor(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor-status'] }),
  });

  return {
    status: monitorStatus,
    isLoading,
    refetch,
    start: startMutation.mutate,
    stop: stopMutation.mutate,
    pause: pauseMutation.mutate,
    resume: resumeMutation.mutate,
    isStarting: startMutation.isPending,
    isStopping: stopMutation.isPending,
  };
}

export function useAutomationStatus() {
  const { automationStatus, setAutomationStatus } = useAppStore();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['automation-status'],
    queryFn: () => api.getAutomationStatus(),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (data?.success && data.data) {
      setAutomationStatus(data.data);
    }
  }, [data, setAutomationStatus]);

  const startMutation = useMutation({
    mutationFn: (params: { strategy?: string; monitorOnly?: boolean }) =>
      api.startAutomation(params.strategy, params.monitorOnly),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation-status'] }),
  });

  const stopMutation = useMutation({
    mutationFn: (emergency: boolean) => api.stopAutomation(emergency),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation-status'] }),
  });

  const pauseMutation = useMutation({
    mutationFn: () => api.pauseAutomation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation-status'] }),
  });

  const resumeMutation = useMutation({
    mutationFn: () => api.resumeAutomation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation-status'] }),
  });

  return {
    status: automationStatus,
    isLoading,
    refetch,
    start: startMutation.mutate,
    stop: stopMutation.mutate,
    pause: pauseMutation.mutate,
    resume: resumeMutation.mutate,
    isStarting: startMutation.isPending,
    isStopping: stopMutation.isPending,
  };
}

export function usePrices(chain?: string) {
  const { prices, setPrices } = useAppStore();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['prices', chain],
    queryFn: () => api.getPrices(chain),
    refetchInterval: 10000,
  });

  useEffect(() => {
    if (data?.success && data.data?.prices) {
      setPrices(data.data.prices);
    }
  }, [data, setPrices]);

  return { prices, isLoading, refetch };
}

export function useOpportunities(minProfit = 10, limit = 20) {
  const { opportunities, setOpportunities } = useAppStore();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['opportunities', minProfit, limit],
    queryFn: () => api.getOpportunities(minProfit, limit),
    refetchInterval: 15000,
  });

  useEffect(() => {
    if (data?.success && data.data?.opportunities) {
      setOpportunities(data.data.opportunities);
    }
  }, [data, setOpportunities]);

  const scanMutation = useMutation({
    mutationFn: (params: { symbols?: string[]; chains?: string[] }) =>
      api.scanOpportunities(params.symbols, params.chains),
    onSuccess: () => queryClient => queryClient.invalidateQueries({ queryKey: ['opportunities'] }),
  });

  return { opportunities, isLoading, refetch, scan: scanMutation.mutate };
}

export function useFundBalance() {
  const { fundBalance, setFundBalance } = useAppStore();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['fund-balance'],
    queryFn: () => api.getFundBalance(),
    refetchInterval: 30000,
  });

  useEffect(() => {
    if (data?.success && data.data) {
      setFundBalance(data.data);
    }
  }, [data, setFundBalance]);

  return { balance: fundBalance, isLoading, refetch };
}

export function useStrategies() {
  const { strategies, setStrategies, currentStrategy, setCurrentStrategy } = useAppStore();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => api.getStrategies(),
  });

  useEffect(() => {
    if (data?.success && data.data?.strategies) {
      setStrategies(data.data.strategies);
    }
  }, [data, setStrategies]);

  const switchMutation = useMutation({
    mutationFn: (strategy: string) => api.switchStrategy(strategy),
    onSuccess: (response) => {
      if (response.success) {
        setCurrentStrategy(currentStrategy);
        queryClient.invalidateQueries({ queryKey: ['automation-status'] });
      }
    },
  });

  return {
    strategies,
    currentStrategy,
    isLoading,
    refetch,
    switchStrategy: switchMutation.mutate,
  };
}

export function useExecutionHistory(limit = 100) {
  const { history, setHistory } = useAppStore();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['execution-history', limit],
    queryFn: () => api.getExecutionHistory(limit),
    refetchInterval: 30000,
  });

  useEffect(() => {
    if (data?.success && data.data) {
      setHistory(data.data.data || []);
    }
  }, [data, setHistory]);

  return { history, isLoading, refetch };
}

export function useBridgeFees(srcChain?: string, dstChain?: string) {
  const { bridgeFees, setBridgeFees } = useAppStore();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['bridge-fees', srcChain, dstChain],
    queryFn: () =>
      srcChain && dstChain
        ? api.getBridgeFees(srcChain, dstChain)
        : api.getAllBridgeFees(),
    refetchInterval: 60000,
  });

  useEffect(() => {
    if (data?.success && data.data?.fees) {
      setBridgeFees(data.data.fees);
    }
  }, [data, setBridgeFees]);

  return { fees: bridgeFees, isLoading, refetch };
}
