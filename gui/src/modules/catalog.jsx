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
            summarize_replies: { doc: "Summarize received replies into a single message per sender." },
            clear_replies: { doc: "Clear all stored replies." },
            keep_last_reply_per_source: { doc: "Keep only the last reply per sender in _incoming_replies." },
        },
    },
    FeedForwardRegion: {
        label: "FeedForwardRegion",
        defaults: (i) => ({
            name: `Region_${i}`,
            task: "Describe the purpose of this region",
            connections: {},
        }),
        methods: {
            make_questions: { doc: "Generate questions for connected regions to update knowledge." },
            make_replies: { doc: "Generate replies to all pending requests in _incoming_requests, addressing each reply to all connected regions." },
            summarize_replies: { doc: "Summarize received replies into a single message per sender." },
            clear_replies: { doc: "Clear all stored replies." },
            keep_last_reply_per_source: { doc: "Keep only the last reply per sender in _incoming_replies." },
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
            keep_last_reply_per_source: { doc: "Keep only the last reply per sender in _incoming_replies." },
        },
    },
    ListenerRegion: {
        label: "ListenerRegion",
        defaults: (i) => ({
            name: `Listener_${i}`
        }),
        methods: {
            start: { doc: "Launches the background forwarding task." },
            stop: { doc: "Cleanly stops forwarding and terminates output process." },
        },
    },
    BroadcastRegion: {
        label: "BroadcastRegion",
        defaults: (i) => ({
            name: `Broadcast_${i}`,
            task: "Forward all incoming messages to connected regions",
            connections: {},
        }),
        methods: {
            broadcast: { doc: "Send collected messages to all connected regions." },
            keep_last_reply_per_source: { doc: "Keep only the last reply per sender in _incoming_replies." },
        },
    },
};