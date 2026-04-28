import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { getDecisionGraph } from '../../api/simulations';
import type { DecisionGraphNode, DecisionGraphEdge } from '../../api/simulations';

interface Props {
  simulationId: string;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  count: number;
  top_card_name: string | null;
  top_3_cards: { name: string; count: number; pct: number }[];
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  count: number;
}

function nodeColor(id: string): string {
  const colors: Record<string, string> = {
    ATTACK: '#ef4444',
    PLAY_SUPPORTER: '#8b5cf6',
    PLAY_ITEM: '#3b82f6',
    PLAY_TOOL: '#f59e0b',
    ATTACH_ENERGY: '#22c55e',
    RETREAT: '#06b6d4',
    PASS: '#64748b',
    EVOLVE: '#ec4899',
  };
  return colors[id] ?? '#60a5fa';
}

function nodeRadius(count: number): number {
  return Math.min(24, 6 + Math.sqrt(count) * 1.2);
}

function edgeWidth(count: number): number {
  return Math.min(6, 1 + Math.log(Math.max(1, count)) * 0.5);
}

function nodeLabel(node: SimNode): string {
  const base = node.id.length > 12 ? node.id.slice(0, 11) + '…' : node.id;
  return node.top_card_name ? `${base}\n(${node.top_card_name.slice(0, 14)})` : base;
}

function tooltipText(node: SimNode): string {
  const lines = [`${node.id}  ×${node.count}`];
  if (node.top_3_cards.length) {
    lines.push('Top cards:');
    for (const c of node.top_3_cards) {
      lines.push(`  ${c.name} — ${c.count} (${c.pct}%)`);
    }
  }
  return lines.join('\n');
}

export default function DecisionMap({ simulationId }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [loading, setLoading] = useState(false);
  const [graphData, setGraphData] = useState<{ nodes: DecisionGraphNode[]; edges: DecisionGraphEdge[] } | null>(null);
  const [fetched, setFetched] = useState(false);

  useEffect(() => {
    setLoading(true);
    getDecisionGraph(simulationId)
      .then((r) => setGraphData(r))
      .catch(() => setGraphData(null))
      .finally(() => {
        setLoading(false);
        setFetched(true);
      });
  }, [simulationId]);

  useEffect(() => {
    if (!fetched || !graphData?.nodes.length || !svgRef.current) return;

    const el = svgRef.current;
    const width = el.clientWidth || 800;
    const height = 500;

    const nodes: SimNode[] = graphData.nodes.map((n) => ({
      id: n.action_type,
      count: n.count,
      top_card_name: n.top_card_name,
      top_3_cards: n.top_3_cards,
    }));

    const nodeIndex = new Map(nodes.map((n, i) => [n.id, i]));
    const links: SimLink[] = graphData.edges
      .map((e) => {
        const si = nodeIndex.get(e.source);
        const ti = nodeIndex.get(e.target);
        if (si === undefined || ti === undefined) return null;
        return { source: si, target: ti, count: e.count } as SimLink;
      })
      .filter((l): l is SimLink => l !== null);

    // Clear SVG
    d3.select(el).selectAll('*').remove();

    const svg = d3.select(el).attr('width', width).attr('height', height);

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
      .attr('fill', '#64748b');

    const linkEl = svg
      .append('g')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(links)
      .join('line')
      .attr('stroke', '#64748b')
      .attr('stroke-opacity', 0.5)
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
      .attr('fill', (d) => nodeColor(d.id))
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 1.5);

    // Tooltip
    nodeG.append('title').text((d) => tooltipText(d));

    // Two-line label
    nodeG.each(function (d) {
      const g = d3.select(this);
      const lines = nodeLabel(d).split('\n');
      const textEl = g.append('text')
        .attr('text-anchor', 'middle')
        .attr('font-size', 8)
        .attr('font-family', 'monospace')
        .attr('fill', 'white')
        .attr('pointer-events', 'none');
      if (lines.length === 1) {
        textEl.attr('dy', '0.35em').text(lines[0]);
      } else {
        textEl.append('tspan').attr('x', 0).attr('dy', '-0.4em').text(lines[0]);
        textEl.append('tspan').attr('x', 0).attr('dy', '1.1em').attr('fill', '#e2e8f0').text(lines[1]);
      }
    });

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force('link', d3.forceLink<SimNode, SimLink>(links).id((_, i) => i).distance(100))
      .force('charge', d3.forceManyBody<SimNode>().strength(-250))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide<SimNode>(30))
      .alphaDecay(0.02)
      .on('tick', () => {
        linkEl
          .attr('x1', (d) => (d.source as SimNode).x ?? 0)
          .attr('y1', (d) => (d.source as SimNode).y ?? 0)
          .attr('x2', (d) => (d.target as SimNode).x ?? 0)
          .attr('y2', (d) => (d.target as SimNode).y ?? 0);
        nodeG.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });

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
  }, [graphData, fetched]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        Loading decision graph…
      </div>
    );
  }

  if (fetched && !graphData?.nodes.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        No AI decisions recorded for this simulation.
      </div>
    );
  }

  return <svg ref={svgRef} className="w-full" style={{ height: 500 }} />;
}
