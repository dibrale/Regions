import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
    addEdge,
    Background,
    Controls,
    MiniMap,
    ReactFlowProvider,
    useEdgesState,
    useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Download, Moon, Plus, Sun, Trash2, Upload, X } from "lucide-react";
import './App.css'
import { REGION_CATALOG } from "@/modules/catalog.jsx"
import { CHAIN_COLORS} from "@/modules/chain_colors.jsx";
import { nodeTypes } from "@/modules/region_node.jsx"
import { toRegistryJSON, fromRegistryJSON } from "@/modules/registry_json.jsx";
import { MethodList } from "@/modules/method_list.jsx";

// FIXED: ParamEditor component extracted outside to prevent recreation on every render
function ParamEditor({
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

    const { typeName, params } = selectedNode.data;
    const flat = [];
    Object.entries(params || {}).forEach(([k, v]) => {
        if (v && typeof v === "object" && !Array.isArray(v)) {
            Object.entries(v).forEach(([kk, vv]) => flat.push({ key: `${k}.${kk}`, value: vv }));
        } else {
            flat.push({ key: k, value: v });
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
    const previewConnections = { ...derivedConnections, ...explicitConnections };

    // Decide what to render into the textarea: if user is actively editing this node, show their buffer;
    // otherwise show the live preview (derived+explicit).
    const textareaValue = (connectionsEditingNodeId === selectedNode.id) ? connectionsEditBuffer : JSON.stringify(previewConnections || {}, null, 2);

    return (
        <div className="space-y-3">
            {flat
                .filter(({ key }) => !(key.includes('connections') || key.includes('type')))
                .map(({ key, value }) => (
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
                                    <SelectValue />
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
                            } catch (err) {
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

export default function RegionsFlowEditor() {
    const [isDarkMode, setIsDarkMode] = useState(false);
    // Apply dark class to body for global dark mode
    useEffect(() => {
        if (isDarkMode) {
            document.body.classList.add('dark');
        } else {
            document.body.classList.remove('dark');
        }
    }, [isDarkMode]);
    return (
        <div className="w-full h-full p-4">
            <ReactFlowProvider>
                <EditorImpl isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode} />
            </ReactFlowProvider>
        </div>
    );
}

function EditorImpl({ isDarkMode, setIsDarkMode }) {
    const idRef = useRef(1); // Keep idRef for generating unique IDs during import
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [selectedNodeId, setSelectedNodeId] = useState(null);
    const [selectedEdgeIds, setSelectedEdgeIds] = useState([]);
    const [pendingDeleteId, setPendingDeleteId] = useState(null);
    const [newType, setNewType] = useState("Region");
    // Orchestrator state management
    const [selectedLayer, setSelectedLayer] = useState(0);
    const [layerConfig, setLayerConfig] = useState([{}]); // Start with one empty layer
    const [executionConfig, setExecutionConfig] = useState([[]]); // Start with one empty execution layer
    const [executionOrder, setExecutionOrder] = useState([0]); // Default sequential order
    const [chainColors, setChainColors] = useState([{}]); // Chain color assignments per layer
    // transient drag/hover state to show directional preview in the connections JSON
    const [draggingSourceId, setDraggingSourceId] = useState(null);
    const [hoverTargetId, setHoverTargetId] = useState(null);
    // editing state for manual JSON editing (prevents cursor losing focus while typing)
    const [connectionsEditBuffer, setConnectionsEditBuffer] = useState("");
    const [connectionsEditingNodeId, setConnectionsEditingNodeId] = useState(null);
    // refs to track previous edges and nodes for diffing without triggering extra renders/effects
    const prevEdgesRef = useRef([]);
    const nodesRef = useRef(nodes);

    useEffect(() => {
        nodesRef.current = nodes;
    }, [nodes]);

    // Update existing nodes when dark mode changes
    useEffect(() => {
        setNodes((currentNodes) =>
            currentNodes.map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    isDarkMode,
                },
            }))
        );
    }, [isDarkMode, setNodes]);

    // Update nodes with layer information when layer selection or layer config changes
    useEffect(() => {
        setNodes((currentNodes) =>
            currentNodes.map((node) => {
                const regionName = node.data.params?.name;
                const currentLayerConfig = layerConfig[selectedLayer] || {};
                // Find which chain this region belongs to in the current layer
                let chainName = null;
                let isInCurrentLayer = false;
                let chainColorClass = '';
                let chainTextClass = '';
                for (const [chain, regions] of Object.entries(currentLayerConfig)) {
                    if (regions.includes(regionName)) {
                        chainName = chain;
                        isInCurrentLayer = true;
                        // Get chain color
                        const chainColor = chainColors[selectedLayer]?.[chain] || 0;
                        const colorConfig = CHAIN_COLORS[chainColor];
                        chainColorClass = isDarkMode ? colorConfig.dark : colorConfig.light;
                        chainTextClass = colorConfig.text;
                        break;
                    }
                }
                return {
                    ...node,
                    data: {
                        ...node.data,
                        layerInfo: {
                            isInCurrentLayer,
                            chainName,
                            chainColorClass,
                            chainTextClass,
                        },
                    },
                };
            })
        );
    }, [selectedLayer, layerConfig, chainColors, isDarkMode, setNodes]);

    // Sync edges <-> node.params.connections when edges change.
    useEffect(() => {
        const prev = prevEdgesRef.current;
        const added = edges.filter((e) => !prev.some((pe) => (pe.id ? pe.id === e.id : (pe.source === e.source && pe.target === e.target))));
        const removed = prev.filter((pe) => !edges.some((e) => (pe.id ? e.id === pe.id : (e.source === pe.source && e.target === pe.target))));
        if (added.length === 0 && removed.length === 0) {
            prevEdgesRef.current = edges;
            return;
        }

        // For each added edge, persist in the source node params.connections
        if (added.length > 0) {
            setNodes((prevNodes) =>
                prevNodes.map((n) => {
                    const related = added.filter((a) => a.source === n.id);
                    if (related.length === 0) return n;
                    const params = { ...n.data.params };
                    params.connections = { ...(params.connections || {}) };
                    related.forEach((a) => {
                        const tgt = nodesRef.current.find((nd) => nd.id === a.target);
                        if (tgt) params.connections[tgt.data.params.name] = tgt.data.params.task ?? "";
                    });
                    return { ...n, data: { ...n.data, params } };
                })
            );
        }

        // For each removed edge, remove from source node params.connections
        if (removed.length > 0) {
            setNodes((prevNodes) =>
                prevNodes.map((n) => {
                    const related = removed.filter((a) => a.source === n.id);
                    if (related.length === 0) return n;
                    const params = { ...n.data.params };
                    if (!params.connections) return n;
                    const newConns = { ...params.connections };
                    related.forEach((a) => {
                        const tgt = nodesRef.current.find((nd) => nd.id === a.target);
                        if (tgt && Object.prototype.hasOwnProperty.call(newConns, tgt.data.params.name)) {
                            delete newConns[tgt.data.params.name];
                        }
                    });
                    params.connections = newConns;
                    return { ...n, data: { ...n.data, params } };
                })
            );
        }
        prevEdgesRef.current = edges;
    }, [edges, setNodes]);

    // Keyboard listener for Delete w/ confirmation
    const onKeyDown = useCallback(
        (e) => {
            // if user's focus is inside an input/textarea/contentEditable, let the browser handle keys normally
            const active = document.activeElement;
            if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable)) {
                return; // don't intercept; allow typing/backspace/delete inside fields
            }
            if (e.key === "Delete" || e.key === "Backspace") {
                e.preventDefault();
                // if edges are selected, delete them (no confirmation)
                if (selectedEdgeIds && selectedEdgeIds.length > 0) {
                    const toRemove = new Set(selectedEdgeIds);
                    setEdges((prev) => prev.filter((ed) => !toRemove.has(ed.id)));
                    setSelectedEdgeIds([]);
                    return;
                }
                // otherwise, if a node is selected, request confirmation to delete node
                if (selectedNodeId) {
                    setPendingDeleteId(selectedNodeId);
                }
            }
        },
        [selectedEdgeIds, selectedNodeId, setEdges]
    );

    // Selection change handler from React Flow
    const onSelectionChange = useCallback(({ nodes: selNodes, edges: selEdges }) => {
        // update selected edge ids
        setSelectedEdgeIds((selEdges || []).map((e) => e.id));
        // if nodes are present in the selection, pick the first one
        if (selNodes && selNodes.length > 0) {
            setSelectedNodeId(selNodes[0].id);
            return;
        }
        // selNodes is empty (no node selected). Do NOT clear the selectedNodeId if the user is
        // actively typing in an input/textarea or editing the connections buffer — clearing
        // the selection here causes the ParamEditor to unmount/remount, which steals focus.
        const active = typeof document !== "undefined" ? document.activeElement : null;
        const userTyping = !!(active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable));
        if (userTyping) {
            // preserve selection while user is typing
            return;
        }
        // also preserve selection if user is explicitly editing the connections textarea
        if (connectionsEditingNodeId) return;
        // safe to clear selection
        setSelectedNodeId(null);
    }, [connectionsEditingNodeId]);

    const onConnectStart = useCallback((_, { nodeId }) => {
        // user started dragging a connection from nodeId
        setDraggingSourceId(nodeId || null);
    }, []);

    const onConnectStop = useCallback(() => {
        // clear transient drag state when the drag finishes (connected or cancelled)
        setDraggingSourceId(null);
        setHoverTargetId(null);
    }, []);

    const onNodeMouseEnter = useCallback((_, node) => {
        // while dragging a connection, hovering over a node should set it as the potential target
        if (draggingSourceId && node.id !== draggingSourceId) setHoverTargetId(node.id);
    }, [draggingSourceId]);

    const onNodeMouseLeave = useCallback((_, node) => {
        if (draggingSourceId) setHoverTargetId(null);
    }, [draggingSourceId]);

    // Create an edge and persist it to the source node's params.connections
    const onConnect = useCallback((connection) => {
        // add the edge (React Flow internal state)
        setEdges((eds) => addEdge({
            ...connection,
            type: "default",
            id: `e_${connection.source}_${connection.target}`
        }, eds));

        // persist connection into source node params
        const { source, target } = connection;
        setNodes((prev) =>
            prev.map((n) => {
                if (n.id !== source) return n;
                const params = { ...n.data.params };
                params.connections = { ...params.connections };
                const targetNode = nodesRef.current.find((nd) => nd.id === target);
                if (targetNode) params.connections[targetNode.data.params.name] = targetNode.data.params.task ?? "";
                return { ...n, data: { ...n.data, params } };
            })
        );
    }, [setEdges, setNodes]);

    const addNode = useCallback(
        (typeName) => {
            const idx = idRef.current++;
            const defaults = REGION_CATALOG[typeName].defaults(idx);
            const id = `${typeName}_${idx}`;
            const x = 120 + (idx % 5) * 80;
            const y = 80 + (idx % 7) * 60;
            const node = {
                id,
                type: "regionNode",
                position: { x, y },
                data: {
                    typeName,
                    params: defaults,
                    nodeId: id, // Add nodeId to data for handle callbacks
                    isDarkMode,
                    // callbacks for handle hover — these are safe to store in node data here
                    onHandleEnter: (nid) => setHoverTargetId(nid),
                    onHandleLeave: () => setHoverTargetId(null),
                },
            };
            setNodes((ns) => ns.concat(node));
            setSelectedNodeId(id);
        },
        [setNodes, isDarkMode]
    );

    const onNodeClick = useCallback((_, node) => setSelectedNodeId(node.id), []);
    const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) || null, [nodes, selectedNodeId]);

    const updateParam = useCallback(
        (keyPath, value) => {
            setNodes((ns) =>
                ns.map((n) => {
                    if (n.id !== selectedNodeId) return n;
                    const params = { ...n.data.params };
                    const parts = keyPath.split(".");
                    let cur = params;
                    for (let i = 0; i < parts.length - 1; i++) {
                        const p = parts[i];
                        cur[p] = cur[p] ?? {};
                        cur = cur[p];
                    }
                    cur[parts[parts.length - 1]] = value;
                    return { ...n, data: { ...n.data, params } };
                })
            );
        },
        [setNodes, selectedNodeId]
    );

    const removeNode = useCallback(() => {
        if (!pendingDeleteId) return;
        setNodes((ns) => ns.filter((n) => n.id !== pendingDeleteId));
        setEdges((es) => es.filter((e) => e.source !== pendingDeleteId && e.target !== pendingDeleteId));
        if (selectedNodeId === pendingDeleteId) setSelectedNodeId(null);
        setPendingDeleteId(null);
    }, [pendingDeleteId, selectedNodeId, setNodes, setEdges]);

    // Helper to sync edges to match an explicit connections object for a given source node
    const syncEdgesWithConnections = useCallback((sourceNodeId, connectionsObj) => {
        // map names -> node ids
        const nameToId = {};
        nodesRef.current.forEach((n) => {
            nameToId[n.data.params.name] = n.id;
        });
        setEdges((prevEdges) => {
            const next = [...prevEdges];
            // ensure edges for entries in connectionsObj exist
            Object.keys(connectionsObj || {}).forEach((targetName) => {
                const targetId = nameToId[targetName];
                if (!targetId) return; // unknown name
                const exists = next.some((e) => e.source === sourceNodeId && e.target === targetId);
                if (!exists) next.push({
                    id: `e_${sourceNodeId}_${targetId}`,
                    source: sourceNodeId,
                    target: targetId,
                    type: "default"
                });
            });
            // remove edges that are from sourceNodeId but not present in connectionsObj
            return next.filter((e) => {
                if (e.source !== sourceNodeId) return true;
                const targetNode = nodesRef.current.find((n) => n.id === e.target);
                const targetName = targetNode?.data?.params?.name;
                return targetName && Object.prototype.hasOwnProperty.call(connectionsObj || {}, targetName);
            });
        });
    }, []);

    // --- New Import Functionality ---
    const importRegions = useCallback((event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const jsonData = JSON.parse(e.target.result);
                if (!Array.isArray(jsonData)) {
                     alert('Invalid file format: Expected an array of region objects.');
                     return;
                }
                const { nodes: importedNodes, edges: importedEdges } = fromRegistryJSON(jsonData, isDarkMode, idRef);
                setNodes(importedNodes);
                setEdges(importedEdges);
                setSelectedNodeId(null); // Clear selection after import
                // Optionally reset other state like layerConfig if needed, or prompt user
                // setLayerConfig([{}]);
                // setExecutionConfig([[]]);
                // setExecutionOrder([0]);
                // setChainColors([{}]);
                alert('Regions imported successfully!');
            } catch (error) {
                console.error("Error importing regions:", error);
                alert('Error importing regions: ' + (error.message || 'Invalid JSON or unexpected format.'));
            } finally {
                // Reset the input so the same file can be selected again
                event.target.value = '';
            }
        };
        reader.readAsText(file);
    }, [isDarkMode, setNodes, setEdges]);

    const exportJSON = useCallback(() => {
        console.log("Export called - nodes:", nodes.length, "edges:", edges.length);
        const json = toRegistryJSON(nodes, edges);
        console.log("Generated JSON:", json);
        const jsonString = JSON.stringify(json, null, 2);
        console.log("JSON string:", jsonString);

        // Create and trigger download
        const blob = new Blob([jsonString], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'regions.json';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        console.log("Download triggered");
    }, [nodes, edges]);

    const exportOrchestratorConfig = useCallback(() => {
        const config = {
            layer_config: layerConfig,
            execution_config: executionConfig,
            execution_order: executionOrder
        };
        const jsonString = JSON.stringify(config, null, 2);

        // Create and trigger download
        const blob = new Blob([jsonString], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'orchestrator.json';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }, [layerConfig, executionConfig, executionOrder]);

    const importOrchestratorConfig = useCallback((event) => {
        const file = event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const config = JSON.parse(e.target.result);
                if (config.layer_config) {
                    setLayerConfig(config.layer_config);
                }
                if (config.execution_config) {
                    // Convert arrays back to tuples
                    const convertedExecutionConfig = config.execution_config.map(layer =>
                        layer.map(entry => Array.isArray(entry) ? entry : [entry[0], entry[1]])
                    );
                    setExecutionConfig(convertedExecutionConfig);
                }
                if (config.execution_order) {
                    setExecutionOrder(config.execution_order);
                }
                alert('Orchestrator configuration imported successfully!');
            } catch (error) {
                alert('Error importing configuration: ' + error.message);
            } finally {
                 // Reset the input so the same file can be selected again
                event.target.value = '';
            }
        };
        reader.readAsText(file);
    }, []);

    const exportAllState = useCallback(() => {
        try {
            // Combine all relevant state into a single object
            const allState = {
                // Flow Diagram State
                nodes: toRegistryJSON(nodes, edges), // Reuse existing function to get serializable node data
                edges: edges, // Edges are already serializable

                // Orchestrator State
                layerConfig: layerConfig,
                executionConfig: executionConfig,
                executionOrder: executionOrder,
                chainColors: chainColors,
            };

            const jsonString = JSON.stringify(allState, null, 2);
            const blob = new Blob([jsonString], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'app_full_state.json'; // Suggest a filename
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);

            console.log("Full application state exported successfully.");
        } catch (error) {
            console.error("Error exporting full state:", error);
            alert('Error exporting full state: ' + (error.message || 'Unknown error'));
        }
    }, [nodes, edges, layerConfig, executionConfig, executionOrder, chainColors]); // Dependencies

    const importAllState = useCallback((event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const allState = JSON.parse(e.target.result);

                // --- Validate basic structure (basic check) ---
                if (
                    !allState.hasOwnProperty('nodes') ||
                    !allState.hasOwnProperty('edges') ||
                    !allState.hasOwnProperty('layerConfig') ||
                    !allState.hasOwnProperty('executionConfig') ||
                    !allState.hasOwnProperty('executionOrder') ||
                    !allState.hasOwnProperty('chainColors')
                ) {
                    throw new Error('Invalid file format: Missing required state properties.');
                }

                // --- Import Flow Diagram State ---
                // Use fromRegistryJSON to convert the imported node data back to React Flow nodes
                const { nodes: importedNodes, edges: importedEdges } = fromRegistryJSON(allState.nodes, isDarkMode, idRef);
                setNodes(importedNodes);
                setEdges(importedEdges);

                // --- Import Orchestrator State ---
                setLayerConfig(allState.layerConfig);
                // Ensure executionConfig inner arrays are proper arrays (not generic objects from JSON)
                const convertedExecutionConfig = allState.executionConfig.map(layer =>
                    layer.map(entry => Array.isArray(entry) ? [entry[0], entry[1]] : [null, null]) // Basic conversion, adjust if needed
                );
                setExecutionConfig(convertedExecutionConfig);
                setExecutionOrder(allState.executionOrder);
                setChainColors(allState.chainColors);

                // --- Clear Selection ---
                setSelectedNodeId(null);
                setSelectedEdgeIds([]);

                alert('Full application state imported successfully!');

            } catch (error) {
                console.error("Error importing full state:", error);
                alert('Error importing full state: ' + (error.message || 'Invalid JSON or unexpected format.'));
            } finally {
                // Reset the input so the same file can be selected again
                event.target.value = '';
            }
        };
        reader.onerror = (e) => {
             console.error("Error reading file:", e);
             alert('Error reading file.');
             event.target.value = '';
        };
        reader.readAsText(file);
    }, [isDarkMode, setNodes, setEdges, setLayerConfig, setExecutionConfig, setExecutionOrder, setChainColors, setSelectedNodeId, setSelectedEdgeIds]);

    // Initialize or update the connections edit buffer when selection changes (but not while actively editing)
    useEffect(() => {
        if (!selectedNode) {
            setConnectionsEditBuffer("");
            return;
        }
        if (connectionsEditingNodeId && connectionsEditingNodeId === selectedNode.id) return; // don't clobber while editing

        // compute derived connections from edges
        const derived = {};
        edges.filter((e) => e.source === selectedNode.id).forEach((e) => {
            const tgt = nodes.find((n) => n.id === e.target);
            if (tgt) derived[tgt.data.params.name] = tgt.data.params.task ?? "";
        });
        const explicit = selectedNode.data.params.connections || {};
        const starting = Object.keys(explicit).length > 0 ? explicit : derived;
        setConnectionsEditBuffer(JSON.stringify(starting || {}, null, 2));
    }, [selectedNodeId, selectedNode, edges, nodes, connectionsEditingNodeId]);

    const sidebar = (
        <div className={`h-full space-y-3 ${isDarkMode ? 'dark' : ''}`}>
            {/* Layer Selection Panel */}
            {/* Chain Assignment Panel */}
            <Card className={`rounded-2xl ${isDarkMode ? 'bg-gray-900 border-gray-700' : ''}`}>
                <CardHeader className="pb-2">
                    <CardTitle className={`text-base ${isDarkMode ? 'text-white' : ''}`}>Chain Assignment -
                        Layer {selectedLayer}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                    <div className="space-y-2">
                        {Object.entries(layerConfig[selectedLayer] || {}).map(([chainName, regions]) => {
                            const chainColor = chainColors[selectedLayer]?.[chainName] || 0;
                            const colorConfig = CHAIN_COLORS[chainColor];
                            return (
                                <div key={chainName}
                                     className={`border rounded p-2 ${isDarkMode ? 'border-gray-600 bg-gray-800' : 'border-gray-200 bg-gray-50'}`}>
                                    <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2">
                                            <span
                                                className={`text-sm font-medium ${isDarkMode ? 'text-white' : ''}`}>{chainName}</span>
                                            <div
                                                className={`w-4 h-4 rounded ${isDarkMode ? colorConfig.dark : colorConfig.light}`}></div>
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <Select
                                                value={chainColor.toString()}
                                                onValueChange={(value) => {
                                                    const newChainColors = [...chainColors];
                                                    if (!newChainColors[selectedLayer]) {
                                                        newChainColors[selectedLayer] = {};
                                                    }
                                                    newChainColors[selectedLayer][chainName] = parseInt(value);
                                                    setChainColors(newChainColors);
                                                }}
                                            >
                                                <SelectTrigger
                                                    className={`w-20 h-6 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}>
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent
                                                    className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                                    {CHAIN_COLORS.map((color, index) => (
                                                        <SelectItem key={index} value={index.toString()}
                                                                    className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>
                                                            <div className="flex items-center gap-2">
                                                                <div
                                                                    className={`w-3 h-3 rounded ${isDarkMode ? color.dark : color.light}`}></div>
                                                                {color.name}
                                                            </div>
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                onClick={() => {
                                                    const newLayerConfig = [...layerConfig];
                                                    delete newLayerConfig[selectedLayer][chainName];
                                                    setLayerConfig(newLayerConfig);
                                                    // Also remove color assignment
                                                    const newChainColors = [...chainColors];
                                                    if (newChainColors[selectedLayer]) {
                                                        delete newChainColors[selectedLayer][chainName];
                                                    }
                                                    setChainColors(newChainColors);
                                                }}
                                                className="h-6 w-6 p-0"
                                            >
                                                <X className="w-3 h-3" />
                                            </Button>
                                        </div>
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {regions.map((regionName, index) => (
                                            <span
                                                key={index}
                                                className={`text-xs px-2 py-1 rounded ${isDarkMode ? colorConfig.dark : colorConfig.light} ${colorConfig.text}`}
                                            >
                      {regionName}
                                                <button
                                                    onClick={() => {
                                                        const newLayerConfig = [...layerConfig];
                                                        newLayerConfig[selectedLayer][chainName] = regions.filter((_, i) => i !== index);
                                                        // Don't delete the chain even if it becomes empty - preserve empty chains
                                                        setLayerConfig(newLayerConfig);
                                                    }}
                                                    className="ml-1 hover:text-red-500"
                                                >
                        ×
                      </button>
                    </span>
                                        ))}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="New chain name"
                            className={`flex-1 text-xs border rounded px-2 py-1 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && e.target.value.trim()) {
                                    const chainName = e.target.value.trim();
                                    const newLayerConfig = [...layerConfig];
                                    if (!newLayerConfig[selectedLayer][chainName]) {
                                        newLayerConfig[selectedLayer][chainName] = [];
                                        setLayerConfig(newLayerConfig);
                                        // Assign default color (cycle through colors based on chain count)
                                        const newChainColors = [...chainColors];
                                        if (!newChainColors[selectedLayer]) {
                                            newChainColors[selectedLayer] = {};
                                        }
                                        const existingChainCount = Object.keys(newLayerConfig[selectedLayer]).length - 1;
                                        newChainColors[selectedLayer][chainName] = existingChainCount % CHAIN_COLORS.length;
                                        setChainColors(newChainColors);
                                        e.target.value = '';
                                    }
                                }
                            }}
                        />
                        <Button
                            size="sm"
                            onClick={(e) => {
                                const input = e.target.parentElement.querySelector('input');
                                const chainName = input.value.trim();
                                if (chainName) {
                                    const newLayerConfig = [...layerConfig];
                                    if (!newLayerConfig[selectedLayer][chainName]) {
                                        newLayerConfig[selectedLayer][chainName] = [];
                                        setLayerConfig(newLayerConfig);
                                        // Assign default color (cycle through colors based on chain count)
                                        const newChainColors = [...chainColors];
                                        if (!newChainColors[selectedLayer]) {
                                            newChainColors[selectedLayer] = {};
                                        }
                                        const existingChainCount = Object.keys(newLayerConfig[selectedLayer]).length - 1;
                                        newChainColors[selectedLayer][chainName] = existingChainCount % CHAIN_COLORS.length;
                                        setChainColors(newChainColors);
                                        input.value = '';
                                    }
                                }
                            }}
                            className="gap-1"
                        >
                            <Plus className="w-3 h-3" /> Add Chain
                        </Button>
                    </div>
                    <div className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                        Drag regions from the flow diagram into chains, or click a region and select "Assign to Chain"
                        below.
                    </div>
                    {selectedNodeId && (
                        <div className="space-y-2">
                            <Label className={`text-xs ${isDarkMode ? 'text-gray-300' : ''}`}>
                                Assign "{nodes.find(n => n.id === selectedNodeId)?.data?.params?.name}" to chain:
                            </Label>
                            <Select
                                value={(() => {
                                    const regionName = nodes.find(n => n.id === selectedNodeId)?.data?.params?.name;
                                    const currentLayerConfig = layerConfig[selectedLayer] || {};
                                    // Find which chain this region is currently assigned to
                                    for (const [chainName, regions] of Object.entries(currentLayerConfig)) {
                                        if (regions.includes(regionName)) {
                                            return chainName;
                                        }
                                    }
                                    return ""; // Return empty string if not assigned to any chain
                                })()}
                                onValueChange={(chainName) => {
                                    const regionName = nodes.find(n => n.id === selectedNodeId)?.data?.params?.name;
                                    if (regionName && chainName) {
                                        const newLayerConfig = [...layerConfig];
                                        // Remove this specific region from other chains, only delete chains if they contained this region
                                        Object.keys(newLayerConfig[selectedLayer]).forEach(chain => {
                                            if (chain !== chainName) { // Don't modify the target chain yet
                                                const originalLength = newLayerConfig[selectedLayer][chain].length;
                                                newLayerConfig[selectedLayer][chain] = newLayerConfig[selectedLayer][chain].filter(r => r !== regionName);
                                                // Only delete chains that become empty AFTER removing this specific region
                                                // (i.e., they had this region and now have nothing)
                                                if (originalLength > 0 && newLayerConfig[selectedLayer][chain].length === 0) {
                                                    delete newLayerConfig[selectedLayer][chain];
                                                }
                                            }
                                        });
                                        // Add to selected chain
                                        if (!newLayerConfig[selectedLayer][chainName]) {
                                            newLayerConfig[selectedLayer][chainName] = [];
                                        }
                                        if (!newLayerConfig[selectedLayer][chainName].includes(regionName)) {
                                            newLayerConfig[selectedLayer][chainName].push(regionName);
                                        }
                                        setLayerConfig(newLayerConfig);
                                    }
                                }}
                            >
                                <SelectTrigger
                                    className={`${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}>
                                    <SelectValue placeholder="Select chain" />
                                </SelectTrigger>
                                <SelectContent className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                    {Object.keys(layerConfig[selectedLayer] || {}).map(chainName => (
                                        <SelectItem key={chainName} value={chainName}
                                                    className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>
                                            {chainName}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                </CardContent>
            </Card>
            <Tabs defaultValue="params" className="grow grid grid-rows-[auto,1fr]">
                <TabsList className={`w-full ${isDarkMode ? 'bg-gray-800 border-gray-600' : ''}`}>
                    <TabsTrigger value="params"
                                 className={isDarkMode ? 'text-white data-[state=active]:bg-gray-700' : ''}>
                        Parameters
                    </TabsTrigger>
                    <TabsTrigger value="methods"
                                 className={isDarkMode ? 'text-white data-[state=active]:bg-gray-700' : ''}>
                        Methods
                    </TabsTrigger>
                    <TabsTrigger value="execution"
                                 className={isDarkMode ? 'text-white data-[state=active]:bg-gray-700' : ''}>
                        Execution
                    </TabsTrigger>
                </TabsList>
                <TabsContent value="params" className="overflow-auto p-0">
                    <Card className={`rounded-2xl h-full ${isDarkMode ? 'bg-gray-900 border-gray-700' : ''}`}>
                        <CardHeader className="pb-1">
                            <CardTitle className={`text-sm ${isDarkMode ? 'text-white' : ''}`}>Init
                                Parameters</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            <ParamEditor
                                selectedNode={selectedNode}
                                updateParam={updateParam}
                                edges={edges}
                                nodes={nodes}
                                draggingSourceId={draggingSourceId}
                                hoverTargetId={hoverTargetId}
                                connectionsEditingNodeId={connectionsEditingNodeId}
                                connectionsEditBuffer={connectionsEditBuffer}
                                setConnectionsEditingNodeId={setConnectionsEditingNodeId}
                                setConnectionsEditBuffer={setConnectionsEditBuffer}
                                selectedNodeId={selectedNodeId}
                                syncEdgesWithConnections={syncEdgesWithConnections}
                                isDarkMode={isDarkMode}
                            />
                            <div className="flex gap-2">
                                <Button variant="destructive" disabled={!selectedNodeId} className="gap-2"
                                        onClick={() => setPendingDeleteId(selectedNodeId)}>
                                    <Trash2 className="w-4 h-4" /> Delete selected
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>
                <TabsContent value="methods" className="overflow-auto p-0">
                    <Card className="rounded-2xl h-full"><CardHeader className="pb-1"><CardTitle className="text-sm">Available
                        Methods</CardTitle></CardHeader>
                        <CardContent>
                            {selectedNode ? (<MethodList typeName={selectedNode.data.typeName} />) : (
                                <div className="text-sm text-gray-500">Select a region to see its methods and
                                    docstrings.</div>)}
                        </CardContent>
                    </Card>
                </TabsContent>
                <TabsContent value="execution" className="overflow-auto p-0">
                    <Card className={`rounded-2xl h-full ${isDarkMode ? 'bg-gray-900 border-gray-700' : ''}`}>
                        <CardHeader className="pb-1">
                            <CardTitle className={`text-sm ${isDarkMode ? 'text-white' : ''}`}>Method Execution -
                                Layer {selectedLayer}</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            {/* Show all regions in current layer and their assigned methods */}
                            <div className="space-y-3">
                                {Object.entries(layerConfig[selectedLayer] || {}).map(([chainName, regions]) => (
                                    <div key={chainName}>
                                        <div
                                            className={`text-xs font-medium mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                                            Chain: {chainName}
                                        </div>
                                        {regions.map(regionName => {
                                            const currentMethods = executionConfig[selectedLayer]?.filter(([region]) => region === regionName) || [];
                                            const availableMethods = Object.keys(REGION_CATALOG[nodes.find(n => n.data.params.name === regionName)?.data.typeName]?.methods || {});
                                            return (
                                                <div key={regionName}
                                                     className={`border rounded p-3 ${isDarkMode ? 'border-gray-600 bg-gray-800' : 'border-gray-200 bg-gray-50'}`}>
                                                    <div
                                                        className={`text-sm font-medium mb-2 ${isDarkMode ? 'text-white' : ''}`}>
                                                        {regionName}
                                                    </div>
                                                    {/* Current methods */}
                                                    <div className="space-y-1 mb-2">
                                                        {currentMethods.map(([, method], index) => (
                                                            <div key={index}
                                                                 className="flex items-center justify-between">
                                <span
                                    className={`text-xs px-2 py-1 rounded ${isDarkMode ? 'bg-green-600 text-white' : 'bg-green-100 text-green-800'}`}>
                                  {index + 1}. {method}()
                                </span>
                                                                <Button
                                                                    size="sm"
                                                                    variant="ghost"
                                                                    onClick={() => {
                                                                        const newExecutionConfig = [...executionConfig];
                                                                        newExecutionConfig[selectedLayer] = newExecutionConfig[selectedLayer].filter(
                                                                            ([r, m]) => !(r === regionName && m === method)
                                                                        );
                                                                        setExecutionConfig(newExecutionConfig);
                                                                    }}
                                                                    className="h-6 w-6 p-0"
                                                                >
                                                                    <X className="w-3 h-3" />
                                                                </Button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                    {/* Add method */}
                                                    <div className="flex gap-2">
                                                        <Select
                                                            onValueChange={(method) => {
                                                                const newExecutionConfig = [...executionConfig];
                                                                if (!newExecutionConfig[selectedLayer]) {
                                                                    newExecutionConfig[selectedLayer] = [];
                                                                }
                                                                // Check if method already exists
                                                                const exists = newExecutionConfig[selectedLayer].some(([r, m]) => r === regionName && m === method);
                                                                if (!exists) {
                                                                    newExecutionConfig[selectedLayer].push([regionName, method]);
                                                                    setExecutionConfig(newExecutionConfig);
                                                                }
                                                            }}
                                                        >
                                                            <SelectTrigger
                                                                className={`flex-1 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}>
                                                                <SelectValue placeholder="Add method" />
                                                            </SelectTrigger>
                                                            <SelectContent
                                                                className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                                                {availableMethods.map(method => (
                                                                    <SelectItem key={method} value={method}
                                                                                className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>
                                                                        {method}()
                                                                    </SelectItem>
                                                                ))}
                                                            </SelectContent>
                                                        </Select>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                ))}
                            </div>
                            {Object.keys(layerConfig[selectedLayer] || {}).length === 0 && (
                                <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                                    No regions assigned to this layer. Use the Chain Assignment panel to add regions
                                    first.
                                </div>
                            )}
                            {/* Execution Timeline */}
                            {executionConfig[selectedLayer]?.length > 0 && (
                                <div className="mt-4">
                                    <div
                                        className={`text-xs font-medium mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                                        Execution Timeline:
                                    </div>
                                    <div className="space-y-1">
                                        {executionConfig[selectedLayer].map(([region, method], index) => (
                                            <div key={index}
                                                 className={`text-xs px-2 py-1 rounded ${isDarkMode ? 'bg-blue-600 text-white' : 'bg-blue-100 text-blue-800'}`}>
                                                {index + 1}. {region}.{method}()
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
            <div className="text-[11px] text-gray-500 px-1">Drag from a node's right pip to another node's left pip to
                create a connection.
            </div>
        </div>
    );

    return (
        <div className={`w-full h-[95vh] flex ${isDarkMode ? 'dark' : ''}`} onKeyDown={onKeyDown} tabIndex={0}>
            {/* Top thin bar with Layer Management, Add Region, and Theme Toggle */}
            <div
                className={`fixed top-0 left-0 right-0 z-100 border-b ${isDarkMode ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-200'}`}>
                <div className="max-w-screen-2xl mx-4 px-2 py-2 flex items-start gap-4">
                    {/* Layer Management (moved from sidebar) */}
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <Label className={`text-xs ${isDarkMode ? 'text-gray-300' : ''}`}>Current Layer:</Label>
                            <Select value={selectedLayer.toString()}
                                    onValueChange={(v) => setSelectedLayer(parseInt(v))}>
                                <SelectTrigger
                                    className={`${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''} w-28`}>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                    {layerConfig.map((_, index) => (
                                        <SelectItem key={index} value={index.toString()}
                                                    className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>
                                            Layer {index}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                size="sm"
                                onClick={() => {
                                    setLayerConfig([...layerConfig, {}]);
                                    setExecutionConfig([...executionConfig, []]);
                                    setExecutionOrder([...executionOrder, layerConfig.length]);
                                    setChainColors([...chainColors, {}]);
                                }}
                                className="gap-1"
                            >
                                <Plus className="w-3 h-3" /> Add Layer
                            </Button>
                            <Button
                                size="sm"
                                variant="destructive"
                                disabled={layerConfig.length <= 1}
                                onClick={() => {
                                    if (confirm(`Delete Layer ${selectedLayer}? This will remove all chain assignments and method configurations for this layer.`)) {
                                        const newLayerConfig = layerConfig.filter((_, i) => i !== selectedLayer);
                                        const newExecutionConfig = executionConfig.filter((_, i) => i !== selectedLayer);
                                        const newExecutionOrder = executionOrder.filter(i => i !== selectedLayer).map(i => i > selectedLayer ? i - 1 : i);
                                        const newChainColors = chainColors.filter((_, i) => i !== selectedLayer);
                                        setLayerConfig(newLayerConfig);
                                        setExecutionConfig(newExecutionConfig);
                                        setExecutionOrder(newExecutionOrder);
                                        setChainColors(newChainColors);
                                        setSelectedLayer(Math.min(selectedLayer, newLayerConfig.length - 1));
                                    }
                                }}
                                className="gap-1"
                            >
                                <Trash2 className="w-3 h-3" /> Delete Layer
                            </Button>
                        </div>
                    </div>
                    {/* Add Region */}
                    <div className="flex flex-col pl-40 gap-2">
                        <div className="flex items-center gap-2">
                            <div className={`text-xs font-medium ${isDarkMode ? 'text-white' : 'text-gray-700'}`}>Add
                                Region
                            </div>
                            <Select value={newType} onValueChange={(v) => setNewType(v)}>
                                <SelectTrigger
                                    className={`w-48 ${isDarkMode ? 'bg-gray-800 border-gray-600 text-white' : ''}`}>
                                    <SelectValue placeholder="Select type" />
                                </SelectTrigger>
                                <SelectContent className={isDarkMode ? 'bg-gray-800 border-gray-600' : ''}>
                                    {Object.entries(REGION_CATALOG).map(([k, v]) => (
                                        <SelectItem key={k} value={k}
                                                    className={isDarkMode ? 'text-white hover:bg-gray-700' : ''}>
                                            {v.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button onClick={() => addNode(newType)} className="gap-2"><Plus className="w-4 h-4" /> Place
                                node</Button>
                        </div>
                    </div>
                    {/* Theme Toggle */}
                    <div className="ml-auto right self-start">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setIsDarkMode(!isDarkMode)}
                            className={`${isDarkMode ? 'bg-gray-800 border-gray-600 text-white hover:bg-gray-700' : ''} gap-2`}
                        >
                            {isDarkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                            {isDarkMode ? 'Light' : 'Dark'}
                        </Button>
                    </div>
                </div>
            </div>
            {/* Bottom action bar: Export/Import buttons */}
            <div
                className={`fixed bottom-0 left-0 right-0 z-100 border-t ${isDarkMode ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-200'}`}>
                <div className="max-w-screen-2xl mx-4 px-2 py-2 flex items-start gap-4">
                    <div className="flex flex-wrap gap-2 justify-end">
                        <Button variant="default" onClick={exportJSON}
                                className="gap-2 bg-green-600 hover:bg-green-700 text-white">
                            <Download className="w-4 h-4" /> Export Regions
                        </Button>
                        {/* --- Import Regions Button --- */}
                        <div className="relative">
                            <input
                                type="file"
                                accept=".json"
                                onChange={importRegions} // Use the new import function
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                id="import-regions-footer"
                            />
                            <Button variant="outline"
                                    className={`${isDarkMode ? 'border-gray-600 text-white hover:bg-gray-800' : ''} gap-2`}>
                                <Upload className="w-4 h-4" /> Import Regions
                            </Button>
                        </div>
                        {/* --- End Import Regions Button --- */}

                        <Button variant="default" onClick={exportOrchestratorConfig}
                                className="gap-2 bg-green-600 hover:bg-green-700 text-white">
                            <Download className="w-4 h-4" /> Export Orchestrator Config
                        </Button>
                        <div className="relative">
                            <input
                                type="file"
                                accept=".json"
                                onChange={importOrchestratorConfig}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                id="import-orchestrator-footer"
                            />
                            <Button variant="outline"
                                    className={`${isDarkMode ? 'border-gray-600 text-white hover:bg-gray-800' : ''} gap-2`}>
                                <Upload className="w-4 h-4" /> Import Orchestrator Config
                            </Button>
                        </div>

                        {/* --- Full State Buttons --- */}
                        <Button variant="default" onClick={exportAllState}
                                className="gap-2 bg-blue-600 hover:bg-blue-700 text-white"> {/* Different color for distinction */}
                            <Download className="w-4 h-4" /> Export All State
                        </Button>
                        <div className="relative">
                            <input
                                type="file"
                                accept=".json"
                                onChange={importAllState}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                id="import-all-state-footer"
                            />
                            <Button variant="outline"
                                    className={`${isDarkMode ? 'border-gray-600 text-white hover:bg-gray-800' : ''} gap-2`}>
                                <Upload className="w-4 h-4" /> Import All State
                            </Button>
                        </div>
                        {/* --- End Full State Buttons --- */}
                    </div>
                </div>
            </div>
            <div className="w-full h-full flex gap-4">
                <div className="w-96 flex-shrink-0 offset-y-16 py-12 overflow-y-auto">
                    {sidebar}
                </div>
                <div className="flex-1 py-12">
                    <Card className={`rounded-2xl h-full ${isDarkMode ? 'bg-gray-900 border-gray-700' : ''}`}>
                        <CardHeader className="py-1">
                            <CardTitle className={`text-base ${isDarkMode ? 'text-white' : ''}`}>
                                Regions Flow Editor
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="h-[calc(100%-2rem)]">
                            <ReactFlow
                                nodeTypes={nodeTypes}
                                nodes={nodes}
                                edges={edges}
                                onNodesChange={onNodesChange}
                                onEdgesChange={onEdgesChange}
                                onConnect={onConnect}
                                onConnectStart={onConnectStart}
                                onConnectStop={onConnectStop}
                                onNodeMouseEnter={onNodeMouseEnter}
                                onNodeMouseLeave={onNodeMouseLeave}
                                onNodeClick={onNodeClick}
                                onSelectionChange={onSelectionChange}
                                fitView
                                // disable React Flow's built-in delete handling so our custom onKeyDown controls delete behavior
                                deleteKeyCode={null}
                            >
                                <Background variant="dots" gap={16} size={1} />
                                <Controls
                                    style={{
                                        button: {
                                            backgroundColor: isDarkMode ? '#374151' : '#ffffff',
                                            color: isDarkMode ? '#ffffff' : '#000000',
                                            border: isDarkMode ? '1px solid #4b5563' : '1px solid #d1d5db',
                                        },
                                    }}
                                />
                                <MiniMap
                                    pannable
                                    zoomable
                                    style={{
                                        backgroundColor: isDarkMode ? '#1f2937' : '#ffffff',
                                    }}
                                    maskColor={isDarkMode ? 'rgba(31, 41, 55, 0.8)' : 'rgba(0, 0, 0, 0.1)'}
                                />
                            </ReactFlow>
                        </CardContent>
                    </Card>
                </div>
                {/* Delete confirmation dialog */}
                <Dialog open={!!pendingDeleteId} onOpenChange={(v) => !v && setPendingDeleteId(null)}>
                    <DialogContent className="rounded-2xl">
                        <DialogHeader><DialogTitle>Delete this region?</DialogTitle></DialogHeader>
                        <div className="text-sm text-gray-600">This action can't be undone.</div>
                        <DialogFooter>
                            <Button variant="secondary" onClick={() => setPendingDeleteId(null)}>Cancel</Button>
                            <Button variant="destructive" onClick={removeNode}>Delete</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            </div>
        </div>
    );
}
