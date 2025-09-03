import {REGION_CATALOG} from "@/modules/catalog.jsx";
import {Handle, Position} from "reactflow";
import React from "react";

function RegionNode({ data, selected }) {
    const { typeName, params, isDarkMode, layerInfo } = data;
    const nodeClass = isDarkMode
        ? "rounded-2xl shadow-md border bg-gray-800 border-gray-600 text-white"
        : "rounded-2xl shadow-md border bg-white";

    // Determine layer assignment styling
    const isInCurrentLayer = layerInfo?.isInCurrentLayer;
    const chainName = layerInfo?.chainName;
    const layerBorderClass = isInCurrentLayer
        ? (isDarkMode ? "ring-2 ring-green-400" : "ring-2 ring-green-500")
        : (isDarkMode ? "opacity-60" : "opacity-50");

    return (
        <div
            className={`${nodeClass} ${selected ? "ring-2 ring-indigo-500" : layerBorderClass} p-4 w-[220px] relative`}>
            {/* Layer assignment badge */}
            {isInCurrentLayer && chainName && (
                <div
                    className={`absolute -top-2 -right-2 text-xs px-2 py-1 rounded-full ${layerInfo.chainColorClass} ${layerInfo.chainTextClass}`}>
                    {chainName}
                </div>
            )}
            <div className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-500'}`}>
                {REGION_CATALOG[typeName].label}
            </div>
            <div className={`text-lg font-semibold break-words ${isDarkMode ? 'text-white' : 'text-black'}`}
                 title={params?.name}>
                {params?.name}
            </div>
            {params?.task && (
                <div className={`text-xs mt-1 break-words ${isDarkMode ? 'text-gray-200' : 'text-gray-700'}`}
                     title={params.task}>
                    {params.task}
                </div>
            )}
            {/* Input & Output handles ("pips") - attach mouse handlers to detect hover on handles too */}
            <Handle type="target" position={Position.Left} id="in"
                    onMouseEnter={() => data.onHandleEnter?.(data.nodeId)} onMouseLeave={() => data.onHandleLeave?.()} />
            {/* Hide outgoing handle for ListenerRegion since it doesn't pass messages to other regions */}
            {typeName !== 'ListenerRegion' && (
                <Handle type="source" position={Position.Right} id="out"
                        onMouseEnter={() => data.onHandleEnter?.(data.nodeId)}
                        onMouseLeave={() => data.onHandleLeave?.()} />
            )}
        </div>
    );
}

export const nodeTypes = { regionNode: RegionNode };