from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.schemas.llm.chat import ChatCompletionRequestBody


class ChatSocketStartCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["start"]
    channel_id: str = Field(min_length=1, max_length=128)
    request: ChatCompletionRequestBody


class ChatSocketSubscribeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["subscribe"]
    channel_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    checkpoint_message_id: str | None = None


class ChatSocketUnsubscribeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["unsubscribe"]
    channel_id: str = Field(min_length=1, max_length=128)


ChatSocketCommand = Annotated[
    ChatSocketStartCommand | ChatSocketSubscribeCommand | ChatSocketUnsubscribeCommand,
    Field(discriminator="type"),
]

CHAT_SOCKET_COMMAND_ADAPTER = TypeAdapter(ChatSocketCommand)
