// Transform current graph into the expected JSON format
import {REGION_CATALOG} from "@/modules/catalog.jsx";

export function toRegistryJSON(nodes, edges) {
    const connectionsBySource = [];
    edges.forEach((e) => {
        const sourceNode = nodes.find((n) => n.id === e.source);
        const targetNode = nodes.find((n) => n.id === e.target);
        if (!sourceNode || !targetNode) return;
        if (!connectionsBySource[sourceNode.id]) connectionsBySource[sourceNode.id] = {};
        const entryName = targetNode.data.params.name;
        connectionsBySource[sourceNode.id][entryName] = targetNode.data.params.task;
    });
    return nodes.map((n) => {
        const name = n.data.params?.name || n.id;
        const type = n.data.typeName;
        const task = n.data.params?.task || "";
        const connections = connectionsBySource[n.id] || {};
        const reply_with_actors = n.data.params?.reply_with_actors || false;
        const threshold = n.data.params?.threshold || null;
        return { name, type, task, connections, reply_with_actors, threshold };
    }); // Return array directly, not wrapped in object
}

// Transform imported JSON format back into nodes and edges
export function fromRegistryJSON(jsonData, isDarkMode, idRef) {
    // Create a map from region name to a unique ID for the new flow
    const nameToIdMap = {};
    const newNodes = jsonData.map((item) => {
        // Generate a new unique ID for the node in the flow diagram
        // Use the idRef to ensure uniqueness
        const nodeId = `imported_${idRef.current++}_${item.name}`;
        nameToIdMap[item.name] = nodeId;

        // Find the type definition in the catalog
        const typeDef = REGION_CATALOG[item.type];
        if (!typeDef) {
             console.warn(`Unknown region type '${item.type}' for region '${item.name}'. Skipping.`);
             return null; // Or handle unknown types differently
        }

        // Merge defaults with imported data
        // We need to be careful not to override the imported name/task/connections
        const defaults = typeDef.defaults(0); // Pass 0 or dummy value, as we'll override name/task anyway
        const mergedParams = {
            ...defaults,
            ...item, // This ensures name, task, connections from JSON override defaults
            // Explicitly ensure connections is an object
            connections: item.connections && typeof item.connections === 'object' && !Array.isArray(item.connections) ? item.connections : {}
        };

        return {
            id: nodeId,
            type: "regionNode",
            position: { x: Math.random() * 500, y: Math.random() * 500 }, // Place randomly or use a layout algorithm
            data: {
                typeName: item.type,
                params: mergedParams,
                nodeId: nodeId, // Add nodeId to data for handle callbacks
                isDarkMode,
                onHandleEnter: () => {}, // Will be updated by EditorImpl
                onHandleLeave: () => {},
            },
        };
    }).filter(node => node !== null); // Remove any null nodes from unknown types

    // Create edges based on the connections defined in the JSON
    const newEdges = [];
    newNodes.forEach((node) => {
        const sourceName = node.data.params.name;
        const connections = node.data.params.connections || {};
        Object.keys(connections).forEach((targetName) => {
            const targetId = nameToIdMap[targetName];
            if (targetId) { // Only create edge if target node exists
                // Ensure the target node actually exists in the newNodes list
                const targetNodeExists = newNodes.some(n => n.id === targetId);
                if (targetNodeExists) {
                     newEdges.push({
                        id: `e_${node.id}_${targetId}`,
                        source: node.id,
                        target: targetId,
                        type: "default"
                    });
                }
            } else {
                console.warn(`Connection target '${targetName}' not found for source '${sourceName}'.`);
            }
        });
    });

    return { nodes: newNodes, edges: newEdges };
}
