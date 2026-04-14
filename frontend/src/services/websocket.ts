import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '@/store';
import type { WSMessage } from '@/types';

class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 3000;
  private url: string;

  constructor(url: string) {
    this.url = url;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[WS] Connected');
        this.reconnectAttempts = 0;
        useAppStore.getState().setConnected(true);
      };

      this.ws.onclose = () => {
        console.log('[WS] Disconnected');
        useAppStore.getState().setConnected(false);
        this.reconnect();
      };

      this.ws.onerror = (error) => {
        console.error('[WS] Error:', error);
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WSMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };
    } catch (error) {
      console.error('[WS] Connection error:', error);
      this.reconnect();
    }
  }

  private reconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.log('[WS] Max reconnect attempts reached');
      return;
    }

    this.reconnectAttempts++;
    console.log(`[WS] Reconnecting... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
  }

  private handleMessage(message: WSMessage) {
    const store = useAppStore.getState();

    switch (message.type) {
      case 'price':
        store.updatePrice(message.data);
        break;
      case 'opportunity':
        store.addOpportunity(message.data);
        break;
      case 'alert':
        console.log('[WS] Alert:', message.data);
        break;
      case 'status':
        console.log('[WS] Status update:', message.data);
        break;
      default:
        console.log('[WS] Unknown message type:', message.type);
    }
  }

  send(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

// Singleton instance
let wsService: WebSocketService | null = null;

export function getWebSocketService(): WebSocketService {
  if (!wsService) {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8500/ws/prices';
    wsService = new WebSocketService(wsUrl);
  }
  return wsService;
}

// React hook for WebSocket
export function useWebSocket() {
  const wsRef = useRef<WebSocketService | null>(null);
  const { setConnected } = useAppStore();

  useEffect(() => {
    wsRef.current = getWebSocketService();
    wsRef.current.connect();

    return () => {
      wsRef.current?.disconnect();
    };
  }, []);

  const send = useCallback((data: any) => {
    wsRef.current?.send(data);
  }, []);

  return {
    send,
    isConnected: useAppStore((state) => state.isConnected),
  };
}
