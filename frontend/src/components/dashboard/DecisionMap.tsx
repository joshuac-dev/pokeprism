import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { getSimulationDecisions } from '../../api/simulations';
import type { DecisionRow } from '../../types/simulation';

interface Props {
  simulationId: string;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  count: number;
  winRate: number | null;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  count: number;
}

function nodeColor(winRate: number | null): string {
  if (winRate === null) return '#60a5fa';
  const r = Math.round((1 - winRate) * 255);
  const g = Math.round(winRate * 180);
  return `rgb(${r},${g},60)`;
}

function nodeRadius(count: number): number {
  return Math.min(40, 8 + Math.sqrt(count) * 2);
}

function edgeWidth(count: number): number {
  return Math.min(6, 1 + Math.log(Math.max(1, count)) * 0.5);
}

export default function DecisionMap({ simulationId }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [loading, setLoading] = useState(false);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [fetched, setFetched] = useState(false);

  useEffect(() => {
    setLoading(true);
    getSimulationDecisions(simulationId, { limit: 200, offset: 0 })
      .then((r) => setDecisions(r.decisions))
      .catch(() => setDecisions([]))
      .finally(() => {
        setLoading(false);
        setFetched(true);
      });
  }, [simulationId]);

  useEffect(() => {
    if (!fetched || !decisions.length || !svgRef.current) return;

    const el = svgRef.current;
    const width = el.clientWidth || 600;
    const height = 320;

    // Build nodes map
    const nodeMap = new Map<string, { count: number; wins: number; total: number }>();
    for (const d of decisions) {
      const key = d.action_type;
      const cur = nodeMap.get(key) ?? { count: 0, wins: 0, total: 0 };
      nodeMap.set(key, { count: cur.count + 1, wins: cur.wins, total: cur.total + 1 });
    }

    const nodes: SimNode[] = [...nodeMap.entries()].map(([id, { count }]) => ({
      id,
      count,
      winRate: null,
    }));

    // Build edges: consecutive decisions within same match
    const edgeMap = new Map<string, number>();
    const byMatch = new Map<string, DecisionRow[]>();
    for (const d of decisions) {
      const mid = d.match_id ?? '__unknown__';
      const arr = byMatch.get(mid) ?? [];
      arr.push(d);
      byMatch.set(mid, arr);
    }
    for (const [, rows] of byMatch) {
      for (let i = 0; i < rows.length - 1; i++) {
        const src = rows[i].action_type;
        const tgt = rows[i + 1].action_type;
        if (src === tgt) continue;
        const key = `${src}→${tgt}`;
        edgeMap.set(key, (edgeMap.get(key) ?? 0) + 1);
      }
    }

    const nodeIndex = new Map(nodes.map((n, i) => [n.id, i]));
    const links: SimLink[] = [];
    for (const [key, count] of edgeMap.entries()) {
      const [src, tgt] = key.split('→');
      const si = nodeIndex.get(src);
      const ti = nodeIndex.get(tgt);
      if (si !== undefined && ti !== undefined) {
        links.push({ source: si, target: ti, count });
      }
    }

    // Clear SVG
    d3.select(el).selectAll('*').remove();

    const svg = d3
      .select(el)
      .attr('width', width)
      .attr('height', height);

    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -3 6 6')
      .attr('refX', 6)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-3L6,0L0,3')
      .attr('fill', '#475569');

    const linkEl = svg
      .append('g')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(links)
      .join('line')
      .attr('stroke', '#475569')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', (d) => edgeWidth(d.count))
      .attr('marker-end', 'url(#arrow)');

    const nodeG = svg
      .append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(nodes)
      .join('g')
      .style('cursor', 'pointer');

    nodeG
      .append('circle')
      .attr('r', (d) => nodeRadius(d.count))
      .attr('fill', (d) => nodeColor(d.winRate))
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 1.5);

    nodeG.append('title').text((d) => `${d.id}\nCount: ${d.count}`);

    nodeG
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('font-size', 9)
      .attr('font-family', 'monospace')
      .attr('fill', 'white')
      .attr('pointer-events', 'none')
      .text((d) => (d.id.length > 10 ? `${d.id.slice(0, 9)}…` : d.id));

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force('link', d3.forceLink<SimNode, SimLink>(links).id((_, i) => i).distance(80))
      .force('charge', d3.forceManyBody<SimNode>().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide<SimNode>(40))
      .alphaDecay(0.02)
      .on('tick', () => {
        linkEl
          .attr('x1', (d) => (d.source as SimNode).x ?? 0)
          .attr('y1', (d) => (d.source as SimNode).y ?? 0)
          .attr('x2', (d) => (d.target as SimNode).x ?? 0)
          .attr('y2', (d) => (d.target as SimNode).y ?? 0);

        nodeG.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });

    // Drag behaviour
    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeG.call(drag);

    return () => {
      simulation.stop();
    };
  }, [decisions, fetched]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        Loading decisions…
      </div>
    );
  }

  if (fetched && !decisions.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        No AI decisions recorded for this simulation.
      </div>
    );
  }

  return <svg ref={svgRef} className="w-full" style={{ height: 320 }} />;
}
