import { HttpRequestError } from "../../../services/http/httpClient";
export { isConversationStreamResyncRequired } from "../../../services/llm/conversationStreamErrors";

export function isNotFoundRequestError(error: unknown) {
  return error instanceof HttpRequestError
    && error.status === 404
    && error.code === "not_found";
}
