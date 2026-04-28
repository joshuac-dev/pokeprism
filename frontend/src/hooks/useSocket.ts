import { useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';

export function useSocket(simulationId: string | null, onEvent: (event: unknown) => void) {
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    if (!simulationId) return;

    const socket = io(window.location.origin, {
      path: '/socket.io',
      transports: ['polling', 'websocket'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });
    socketRef.current = socket;

    socket.on('connect', () => {
      socket.emit('subscribe_simulation', { simulation_id: simulationId });
    });

    socket.on('sim_event', onEvent);

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [simulationId, onEvent]);

  return socketRef;
}
