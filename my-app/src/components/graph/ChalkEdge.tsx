"use client";

import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";

export type ChalkEdgeData = {
  relation: string;
  state: "normal" | "hit" | "dim";
  dashed: boolean;
  showLabel: boolean;
};
export type ChalkFlowEdge = Edge<ChalkEdgeData, "chalk">;

export const ChalkEdge = memo(function ChalkEdge(props: EdgeProps<ChalkFlowEdge>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={`chalk-edge ${data?.state ?? "normal"} ${data?.dashed ? "dashed" : ""}`}
      />
      {data?.showLabel ? (
        <EdgeLabelRenderer>
          <i
            className={`chalk-note edge-label ${data.state}`}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data.relation.replace(/_/g, " ")}
          </i>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
});

export const edgeTypes = { chalk: ChalkEdge };
