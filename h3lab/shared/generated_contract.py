"""Generated metadata for the pinned shared-service contract. Do not edit."""

OPENAPI_SHA256 = (
    "sha256:d9aab3147d7e2096668bae7e738eb81c9ca8e9abdbd76b2832e03f1a756fd17b"
)
OPENAPI_VERSION = "0.1.0"
PROTOCOL_VERSION = "1.0"
WORKFLOW_ID = "minimax-h3-unified"
REQUIRED_PATHS = (
    "/v1/artifacts/{mediaId}/content",
    "/v1/assets",
    "/v1/assets/{mediaId}/content",
    "/v1/jobs/{jobId}",
    "/v1/jobs/{jobId}/cancel",
    "/v1/jobs/{jobId}/events",
    "/v1/jobs/{jobId}/preview",
    "/v1/jobs/{jobId}/retry-collection",
    "/v1/jobs/{jobId}/view",
    "/v1/workflows",
    "/v1/workflows/{workflowId}/jobs",
    "/v1/workflows/{workflowId}/views/generation",
)
REQUIRED_SCHEMAS = (
    "GenerationDocument",
    "JobDocument",
    "JobSubmission",
    "Problem",
    "PublicJob",
    "PublicJobEvent",
    "PublicJobProvenance",
    "PublicMediaMetadata",
)
GENERATION_KINDS = (
    "asset",
    "number",
    "section",
    "seed",
    "select",
    "submit",
    "text",
    "textarea",
    "toggle",
)
JOB_KINDS = (
    "cancel",
    "delete",
    "download",
    "log",
    "preview",
    "progress",
    "retry_collection",
    "section",
    "status",
    "video",
)
