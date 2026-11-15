import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { KnowledgeGraph } from "./types";

type Props = {
  graph: KnowledgeGraph;
  query: string;
  showWeakOnly: boolean;
  showOrphansOnly: boolean;
};

type Position = { x: number; y: number };

type DragState = { id: number; offsetX: number; offsetY: number } | null;

const WIDTH = 900;
const HEIGHT = 520;
const PADDING = 72;

function createInitialPositions(graph: KnowledgeGraph): Record<number, Position> {
  const positions: Record<number, Position> = {};
  const columns = Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length)));
  graph.nodes.forEach((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    positions[node.id] = {
      x: PADDING + (column / Math.max(1, columns - 1)) * (WIDTH - PADDING * 2),
      y: PADDING + (row / Math.max(1, Math.ceil(graph.nodes.length / columns) - 1)) * (HEIGHT - PADDING * 2),
    };
  });
  return positions;
}

function getPath(graph: KnowledgeGraph, sourceId: number | null, targetId: number | null): number[] {
  if (!sourceId || !targetId || sourceId === targetId) return [];
  const queue: number[] = [sourceId];
  const previous = new Map<number, number | null>([[sourceId, null]]);
  while (queue.length) {
    const current = queue.shift()!;
    if (current === targetId) break;
    for (const edge of graph.edges) {
      const next = edge.source_topic_id === current ? edge.target_topic_id : edge.target_topic_id === current ? edge.source_topic_id : null;
      if (next !== null && !previous.has(next)) {
        previous.set(next, current);
        queue.push(next);
      }
    }
  }
  if (!previous.has(targetId)) return [];
  const path: number[] = [];
  let current: number | null = targetId;
  while (current !== null) {
    path.unshift(current);
    current = previous.get(current) ?? null;
  }
  return path;
}

export default function KnowledgeGraphCanvas({ graph, query, showWeakOnly, showOrphansOnly }: Props) {
  const [positions, setPositions] = useState<Record<number, Position>>(() => createInitialPositions(graph));
  const [zoom, setZoom] = useState(1);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [targetId, setTargetId] = useState<number | null>(null);
  const [dragging, setDragging] = useState<DragState>(null);
  const [layoutLoaded, setLayoutLoaded] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.graphLayout().then(layout => {
      if (cancelled) return;
      setPositions(current => {
        const next = createInitialPositions(graph);
        for (const node of graph.nodes) next[node.id] = layout.node_positions[String(node.id)] ?? current[node.id] ?? next[node.id];
        return next;
      });
      setZoom(layout.zoom);
      setLayoutLoaded(true);
    }).catch(() => setLayoutLoaded(true));
    return () => { cancelled = true; };
  }, [graph.nodes.map(node => node.id).join(",")]);

  useEffect(() => {
    if (!layoutLoaded) return;
    const timer = window.setTimeout(() => {
      void api.updateGraphLayout({ node_positions: Object.fromEntries(Object.entries(positions).map(([id, position]) => [id, { x: position.x, y: position.y }])), zoom });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [positions, zoom, layoutLoaded]);

  const visibleNodes = useMemo(() => graph.nodes.filter(node => {
    const matchesQuery = !query.trim() || `${node.name} ${node.domain}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (!showWeakOnly || Boolean(node.weak)) && (!showOrphansOnly || Boolean(node.orphan));
  }), [graph.nodes, query, showWeakOnly, showOrphansOnly]);
  const visibleIds = new Set(visibleNodes.map(node => node.id));
  const path = useMemo(() => getPath(graph, sourceId, targetId), [graph, sourceId, targetId]);
  const pathIds = new Set(path);
  const pathEdges = new Set(path.slice(0, -1).map((id, index) => `${id}-${path[index + 1]}`));
  const nodeById = new Map(graph.nodes.map(node => [node.id, node]));

  function pointFromEvent(event: React.PointerEvent<SVGElement>): Position | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    return {
      x: Math.max(26, Math.min(WIDTH - 26, ((event.clientX - rect.left) / rect.width) * WIDTH / zoom)),
      y: Math.max(26, Math.min(HEIGHT - 26, ((event.clientY - rect.top) / rect.height) * HEIGHT / zoom)),
    };
  }

  function beginDrag(event: React.PointerEvent<SVGElement>, id: number) {
    const point = pointFromEvent(event);
    const position = positions[id];
    if (!point || !position) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging({ id, offsetX: position.x - point.x, offsetY: position.y - point.y });
    setSourceId(id);
  }

  function moveDrag(event: React.PointerEvent<SVGSVGElement>) {
    if (!dragging) return;
    const point = pointFromEvent(event);
    if (!point) return;
    setPositions(current => ({ ...current, [dragging.id]: { x: point.x + dragging.offsetX, y: point.y + dragging.offsetY } }));
  }

  function endDrag() { setDragging(null); }

  function toggleTarget(id: number) {
    if (sourceId === null) setSourceId(id);
    else if (targetId === id) setTargetId(null);
    else setTargetId(id);
  }

  return <div className="graph-canvas-shell">
    <div className="graph-toolbar">
      <span>拖拽节点调整布局 · 点击两个节点查看路径</span>
      <div className="graph-zoom-controls"><button className="ghost-button sf-button--compact" onClick={() => setZoom(value => Math.min(1.8, Number((value + 0.1).toFixed(1))))}>放大</button><button className="ghost-button sf-button--compact" onClick={() => setZoom(value => Math.max(0.6, Number((value - 0.1).toFixed(1))))}>缩小</button><button className="ghost-button sf-button--compact" onClick={() => { setZoom(1); setPositions(createInitialPositions(graph)); }}>重置布局</button></div>
    </div>
    <div className="graph-canvas-wrap">
      <svg ref={svgRef} className="graph-canvas" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="可交互知识图谱" onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
        <defs><marker id="knowledge-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#617565" /></marker></defs>
        <g transform={`scale(${zoom})`}>
          {graph.edges.filter(edge => visibleIds.has(edge.source_topic_id) && visibleIds.has(edge.target_topic_id)).map(edge => {
            const source = positions[edge.source_topic_id];
            const target = positions[edge.target_topic_id];
            if (!source || !target) return null;
            const inPath = pathEdges.has(`${edge.source_topic_id}-${edge.target_topic_id}`) || pathEdges.has(`${edge.target_topic_id}-${edge.source_topic_id}`);
            return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={`graph-edge ${inPath ? "path" : ""}`} markerEnd="url(#knowledge-arrow)" />;
          })}
          {visibleNodes.map(node => {
            const position = positions[node.id] ?? { x: WIDTH / 2, y: HEIGHT / 2 };
            const selected = node.id === sourceId || node.id === targetId;
            const inPath = pathIds.has(node.id);
            return <g key={node.id} className={`graph-svg-node ${node.weak ? "weak" : ""} ${selected ? "selected" : ""} ${inPath ? "path" : ""}`} transform={`translate(${position.x} ${position.y})`} onPointerDown={event => beginDrag(event, node.id)} onClick={() => toggleTarget(node.id)}>
              <circle r={selected ? 25 : 22} />
              <text y={-31} textAnchor="middle">{node.name.length > 14 ? `${node.name.slice(0, 14)}…` : node.name}</text>
              <text className="graph-svg-meta" y={39} textAnchor="middle">{node.verified_level}/8 · {node.degree ?? 0} 连</text>
            </g>;
          })}
        </g>
      </svg>
    </div>
    <div className="graph-path-status" aria-live="polite">{sourceId && targetId ? path.length ? `路径：${path.map(id => nodeById.get(id)?.name ?? `#${id}`).join(" → ")}` : "未找到两个主题之间的关系路径。" : "选择两个主题，查看它们之间的关系路径。"}</div>
  </div>;
}
