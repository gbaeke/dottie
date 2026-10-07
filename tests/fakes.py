from langchain_core.language_models.fake_chat_models import GenericFakeChatModel


class ScriptedModel(GenericFakeChatModel):
    """A chat model that says what the test scripted. Deep Agents binds tools to it: that changes nothing."""

    def bind_tools(self, tools, **kwargs):
        return self
