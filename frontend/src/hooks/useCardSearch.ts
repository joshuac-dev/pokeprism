import { useCallback, useEffect, useRef, useState } from 'react';
import { searchCards, CardSummary } from '../api/cards';

export function useCardSearch(debounceMs = 300) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CardSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchCards(query);
        setResults(data);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, debounceMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query, debounceMs]);

  const clearResults = useCallback(() => {
    setQuery('');
    setResults([]);
  }, []);

  return { query, setQuery, results, loading, clearResults };
}
