import { HttpRequestError } from "../http/httpClient";


export const CONVERSATION_STREAM_RESYNC_REQUIRED = "conversation_stream_resync_required";

export function isConversationStreamResyncRequired(error: unknown) {
  return error instanceof HttpRequestError
    && error.status === 409
    && error.code === CONVERSATION_STREAM_RESYNC_REQUIRED;
}
