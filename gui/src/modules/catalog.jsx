// --- Region catalog (edit to mirror Python classes) ---
export const REGION_CATALOG = {
    Region: {
        label: "Region",
        defaults: (i) => ({
            name: `Region_${i}`,
            task: "Describe the purpose of this region",
            connections: {},
        }),
        methods: {
            make_questions: { doc: "Generate questions for connected regions to update knowledge." },
            make_replies: { doc: "Generate replies to all pending requests in _incoming_requests." },
        },
    },
    RAGRegion: {
        label: "RAGRegion",
        defaults: (i) => ({
            name: `RAG_${i}`,
            task: "Retrieve facts relevant to the request",
            reply_with_actors: true,
            threshold: 0.5,
            connections: {},
        }),
        methods: {
            make_replies: { doc: "Generate structured replies to all pending requests using RAG retrieval." },
            make_updates: { doc: "Process incoming knowledge updates and consolidate similar fragments in the RAG database." },
            request_summaries: { doc: "Request knowledge summaries from all connected regions." },
        },
    },
    ListenerRegion: {
        label: "ListenerRegion",
        defaults: (i) => ({
            name: `Listener_${i}`,
            task: "Listen and forward specific events/messages",
            connections: {}
        }),
        methods: {
            start: { doc: "Launches the background forwarding task." },
            forward: { doc: "Background task that continuously drains ALL pending messages from inbox and forwards each message to output process via mp.Queue." },
            stop: { doc: "Cleanly stops forwarding and terminates output process." },
            verify: { doc: "Verify correct configuration of ListenerRegion in the orchestrator via the region profile." }
        },
    },
};