import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { MemoryGraph, MemoryNode, MemoryEdge } from '../../types/memory';

interface Props {
  graph: MemoryGraph;
  onNodeClick: (cardId: string) => void;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  category: string | null;
  weight: number | null;
  games_observed: number | null;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  weight: number;
}

function nodeColor(weight: number | null): string {
  if (weight === null) return '#60a5fa';
  const r = Math.round((1 - Math.min(1, weight)) * 220);
  const g = Math.round(Math.min(1, weight) * 180);
  return `rgb(${r},${g},60)`;
}

function nodeRadius(gamesObserved: number | null): number {
  if (gamesObserved == null) return 5;
  return Math.min(22, 5 + Math.sqrt(gamesObserved) * 0.9);
}

function edgeWidth(weight: number): number {
  return Math.min(6, 0.5 + weight * 5);
}

export default function MindMapGraph({ graph, onNodeClick }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || !graph.nodes.length) return;

    const el = svgRef.current;
    const width = el.clientWidth || 700;
    const height = 560;

    d3.select(el).selectAll('*').remove();

    const svg = d3.select(el)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('width', width)
      .attr('height', height);

    const g = svg.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    const nodeById = new Map<string, SimNode>();
    const nodes: SimNode[] = (graph.nodes as MemoryNode[]).map(n => {
      const sn: SimNode = {
        id: n.id, name: n.name, category: n.category,
        weight: n.weight, games_observed: n.games_observed,
      };
      nodeById.set(n.id, sn);
      return sn;
    });

    const links: SimLink[] = (graph.edges as MemoryEdge[])
      .filter(e => nodeById.has(e.source) && nodeById.has(e.target))
      .map(e => ({ source: nodeById.get(e.source)!, target: nodeById.get(e.target)!, weight: e.weight }));

    const sim = d3.forceSimulation<SimNode>(nodes)
      .force('link', d3.forceLink<SimNode, SimLink>(links).id(d => d.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-180))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<SimNode>(d => nodeRadius(d.games_observed) + 4));

    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#475569')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', d => edgeWidth(d.weight));

    link.append('title').text(d => {
      const src = d.source as SimNode;
      const tgt = d.target as SimNode;
      return `${src.name} \u2014 ${tgt.name}: ${d.weight.toFixed(3)}`;
    });

    const node = g.append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(nodes)
      .join('g')
      .style('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0);
            d.fx = null; d.fy = null;
          })
      )
      .on('click', (_event, d) => onNodeClick(d.id));

    node.append('circle')
      .attr('r', d => nodeRadius(d.games_observed))
      .attr('fill', d => nodeColor(d.weight))
      .attr('stroke', (_d, i) => i === 0 ? '#f8fafc' : '#1e293b')
      .attr('stroke-width', (_d, i) => i === 0 ? 2.5 : 1);

    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', d => nodeRadius(d.games_observed) + 12)
      .attr('fill', '#475569')
      .attr('font-size', '10px')
      .text(d => d.name.length > 14 ? d.name.slice(0, 13) + '\u2026' : d.name);

    node.append('title').text(d => {
      const wr = d.weight != null ? ` | Weight: ${d.weight.toFixed(3)}` : '';
      const games = d.games_observed != null ? `Games: ${d.games_observed}` : '';
      return `${d.name}\n${games}${wr}`;
    });

    sim.on('tick', () => {
      link
        .attr('x1', d => (d.source as SimNode).x ?? 0)
        .attr('y1', d => (d.source as SimNode).y ?? 0)
        .attr('x2', d => (d.target as SimNode).x ?? 0)
        .attr('y2', d => (d.target as SimNode).y ?? 0);

      node.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => { sim.stop(); };
  }, [graph, onNodeClick]);

  return (
    <div className="bg-app-bg-secondary border border-app-border rounded-2xl p-4">
      <div className="text-app-text-muted text-xs mb-2 flex items-center gap-4">
        <span>Scroll to zoom &bull; Drag nodes &bull; Click to navigate</span>
        <div className="flex items-center gap-2 ml-auto">
          <div className="w-3 h-3 rounded-full bg-red-500 inline-block" />
          <span>Low</span>
          <div className="w-3 h-3 rounded-full bg-green-500 inline-block ml-1" />
          <span>High synergy</span>
        </div>
      </div>
      <svg ref={svgRef} className="w-full" style={{ height: 560 }} />
      {graph.nodes.length === 0 && (
        <div className="text-center text-app-text-muted py-10">No synergy data available.</div>
      )}
    </div>
  );
}
