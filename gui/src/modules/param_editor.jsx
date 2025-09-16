// FIXED: ParamEditor component extracted outside to prevent recreation on every render
import {Label} from "@/components/ui/label.jsx";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select.jsx";
import React from "react";

export function ParamEditor({
                                selectedNode,
                                updateParam,
                                edges,
                                nodes,
                                draggingSourceId,
                                hoverTargetId,
                                connectionsEditingNodeId,
                                connectionsEditBuffer,
                                setConnectionsEditingNodeId,
                                setConnectionsEditBuffer,
                                selectedNodeId,
                                syncEdgesWithConnections,
                                isDarkMode
                            }) {
    if (!selectedNode) return <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>Select a
        region to edit parameters.</div>;

    const {params} = selectedNode.data;
    const flat = [];
    Object.entries(params || {}).forEach(([k, v]) => {
        if (v && typeof v === "object" && !Array.isArray(v)) {
            Object.entries(v).forEach(([kk, vv]) => flat.push({key: `${k}.${kk}`, value: vv}));
        } else {
            flat.push({key: k, value: v});
        }
    });

    // Compute connections that are derived from edges (auto-populated)
    const derivedConnections = {};
    edges
        .filter((e) => e.source === selectedNode.id)
        .forEach((e) => {
            const targetNode = nodes.find((n) => n.id === e.target);
            if (targetNode) derivedConnections[targetNode.data.params.name] = targetNode.data.params.task ?? "";
        });

    // If user is currently dragging a connection from this node and hovering over another node,
    // include the hovered target as a transient connection in the preview.
    if (draggingSourceId === selectedNode.id && hoverTargetId) {
        const hovered = nodes.find((n) => n.id === hoverTargetId);
        if (hovered) derivedConnections[hovered.data.params.name] = hovered.data.params.task ?? "";
    }

    // Merge derived (from edges + transient) with any explicit connections user saved in params.
    // Explicit overrides win.
    const explicitConnections = params?.connections || {};
    const previewConnections = {...derivedConnections, ...explicitConnections};

    // Decide what to render into the textarea: if user is actively editing this node, show their buffer;
    // otherwise show the live preview (derived+explicit).
    const textareaValue = (connectionsEditingNodeId === selectedNode.id) ? connectionsEditBuffer : JSON.stringify(previewConnections || {}, null, 2);

    return (
        <div className="space-y-3">
            {flat
                .filter(({key}) => !(key.includes('connections') || key.includes('type')))
                .map(({key, value}) => (
                    <div key={`${selectedNode.id}-${key}`} className="grid grid-cols-3 gap-2 items-center">
                        <Label className={`text-xs col-span-1 truncate ${isDarkMode ? 'text-gray-300' : ''}`}
                               title={key}>{key}</Label>
                        {key === 'task' ? (
                            <textarea
                                key={`${selectedNode.id}-${key}-textarea`}
                                value={value}
                                onChange={(e) => updateParam(key, e.target.value)}
                                className={`col-span-3 border rounded px-2 py-1 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}
                                rows={3}
                            />
                        ) : typeof value === "string" ? (
                            <input
                                key={`${selectedNode.id}-${key}-input`}
                                value={value}
                                onChange={(e) => updateParam(key, e.target.value)}
                                className={`col-span-2 border rounded px-2 py-1 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}
                            />
                        ) : typeof value === "boolean" ? (
                            <Select
                                key={`${selectedNode.id}-${key}-select`}
                                value={value ? "true" : "false"}
                                onValueChange={(v) => updateParam(key, v === "true")}
                            >
                                <SelectTrigger
                                    className={`col-span-2 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}>
                                    <SelectValue/>
                                </SelectTrigger>
                                <SelectContent className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                    <SelectItem value="true"
                                                className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>true</SelectItem>
                                    <SelectItem value="false"
                                                className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>false</SelectItem>
                                </SelectContent>
                            </Select>
                        ) : (
                            <input
                                key={`${selectedNode.id}-${key}-input-other`}
                                value={String(value)}
                                onChange={(e) => updateParam(key, e.target.value)}
                                className={`col-span-2 border rounded px-2 py-1 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}
                            />
                        )}
                    </div>
                ))}
            {/* Connections editor (JSON) - hidden for ListenerRegion since it doesn't pass messages to other regions */}
            {selectedNode.data.typeName !== 'ListenerRegion' && (
                <div className="space-y-1">
                    <Label className={`text-xs ${isDarkMode ? 'text-gray-300' : ''}`}>connections (JSON)</Label>
                    <textarea
                        key={`${selectedNode.id}-connections-textarea`}
                        value={textareaValue}
                        onFocus={() => setConnectionsEditingNodeId(selectedNodeId)}
                        onBlur={() => setConnectionsEditingNodeId(null)}
                        onChange={(e) => {
                            const val = e.target.value;
                            setConnectionsEditBuffer(val);
                            // try to parse and commit immediately if valid JSON
                            try {
                                const obj = JSON.parse(val || "{}");
                                // update the node's explicit connections and sync edges
                                updateParam("connections", obj);
                                syncEdgesWithConnections(selectedNode.id, obj);
                            } catch {
                                // while typing, JSON may be invalid — we keep the buffer and don't crash
                            }
                        }}
                        className={`text-xs h-32 font-mono w-full border rounded p-2 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}
                    />
                    <div className="text-[10px] text-gray-500">Connections are auto-populated from edges (and from the
                        live drag target); you can override here. Valid JSON will be committed as you type.
                    </div>
                </div>
            )}
        </div>
    );
}