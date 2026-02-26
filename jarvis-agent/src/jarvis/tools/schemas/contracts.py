from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.tools.schemas.base import ToolOutput
from jarvis.tools.schemas.tool_contract import ToolContract


class StrictInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LaxInputModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class GenericToolOutput(ToolOutput):
    model_config = ConfigDict(extra="allow")


# ── 8 críticas ────────────────────────────────────────────────────────────────

class ShellInput(StrictInputModel):
    command: str = Field(min_length=1)
    cwd: Optional[str] = None
    timeout_sec: int = Field(default=30, ge=1, le=600)
    allow_dangerous: bool = False
    shell: bool = True


class ShellOutput(GenericToolOutput):
    pass


class FilesystemInput(StrictInputModel):
    action: Literal["write_text", "read_text", "list_dir", "mkdir", "exists", "delete", "rename", "move", "copy"]
    path: Optional[str] = None
    root_dir: Optional[str] = None
    content: Optional[str] = None
    new_name: Optional[str] = None
    destination: Optional[str] = None
    recursive: bool = False

    @model_validator(mode="after")
    def _check_required_for_action(self) -> "FilesystemInput":
        if self.action != "list_dir" and not self.path:
            raise ValueError("`path` es obligatorio para esta acción.")
        if self.action == "rename" and not self.new_name:
            raise ValueError("`new_name` es obligatorio para rename.")
        if self.action in {"move", "copy"} and not self.destination:
            raise ValueError("`destination` es obligatorio para move/copy.")
        return self


class FilesystemOutput(GenericToolOutput):
    pass


class CalendarInput(StrictInputModel):
    action: Literal["today", "tomorrow", "week", "create", "create_event", "update", "edit", "delete", "remove"]
    query: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    notes: Optional[str] = None


class CalendarOutput(GenericToolOutput):
    pass


class SendEmailInput(StrictInputModel):
    to: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = ""
    action: Literal["send", "draft"] = "send"


class SendEmailOutput(GenericToolOutput):
    pass


class SendMessageInput(StrictInputModel):
    receiver: str = Field(min_length=1)
    message_text: str = Field(min_length=1)
    platform: Optional[str] = "messages"


class SendMessageOutput(GenericToolOutput):
    pass


class WebAgentInput(StrictInputModel):
    task: str = Field(min_length=1)
    url: Optional[str] = None
    max_steps: int = Field(default=20, ge=1, le=100)
    headless: bool = False
    force_sensitive: bool = False


class WebAgentOutput(GenericToolOutput):
    pass


class DownloadFileInput(StrictInputModel):
    url: str = Field(min_length=8)
    filename: Optional[str] = None
    destination: Optional[str] = None
    organize: bool = True
    timeout: int = Field(default=60, ge=1, le=300)

    @model_validator(mode="after")
    def _check_url(self) -> "DownloadFileInput":
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise ValueError("`url` debe iniciar con http:// o https://.")
        return self


class DownloadFileOutput(GenericToolOutput):
    pass


class SearchAndDownloadInput(StrictInputModel):
    query: str = Field(min_length=1)
    file_type: Optional[str] = None
    organize: bool = True


class SearchAndDownloadOutput(GenericToolOutput):
    pass


# ── resto (laxo mínimo viable) ───────────────────────────────────────────────

class OpenAppInput(LaxInputModel):
    app: Optional[str] = None
    target: Optional[str] = None
    wait: bool = False
    new_instance: bool = False

    @model_validator(mode="after")
    def _check_app_or_target(self) -> "OpenAppInput":
        if not self.app and not self.target:
            raise ValueError("Debe incluir `app` o `target`.")
        return self


class RunCodeInput(LaxInputModel):
    language: Literal["python", "node"]
    code: Optional[str] = None
    file: Optional[str] = None
    timeout_sec: int = 30


class WebSearchInput(LaxInputModel):
    query: str = Field(min_length=1)
    limit: int = 5


class SpotifyInput(LaxInputModel):
    action: str = Field(min_length=1)


class VisionInput(LaxInputModel):
    action: str = Field(min_length=1)
    question: Optional[str] = None
    capture_mode: Optional[str] = None


class CodeAssistantInput(LaxInputModel):
    task: str = Field(min_length=1)
    language: Optional[str] = None
    file_path: Optional[str] = None
    open_vscode: bool = True


class KnowledgeInput(LaxInputModel):
    action: str = Field(min_length=1)
    query: Optional[str] = None


class OrganizeFilesInput(LaxInputModel):
    source_dir: str = Field(min_length=1)
    dest_dir: Optional[str] = None
    mode: Optional[str] = None


class SystemInfoInput(LaxInputModel):
    action: str = Field(min_length=1)
    top_n: int = 10


class DateTimeInput(LaxInputModel):
    format: str = "full"


class WeatherInput(LaxInputModel):
    city: str = Field(min_length=1)
    days: int = 0


class CadGeneratorInput(LaxInputModel):
    description: str = Field(min_length=1)
    session_id: Optional[str] = None
    max_retries: int = 3
    open_viewer: bool = False


class RoutinesInput(LaxInputModel):
    action: str = Field(min_length=1)
    day: Optional[str] = None


CONTRACTS: Dict[str, ToolContract] = {
    "shell": ToolContract("shell", ShellInput, ShellOutput),
    "filesystem": ToolContract("filesystem", FilesystemInput, FilesystemOutput),
    "open_app": ToolContract("open_app", OpenAppInput, GenericToolOutput),
    "run_code": ToolContract("run_code", RunCodeInput, GenericToolOutput),
    "web_search": ToolContract("web_search", WebSearchInput, GenericToolOutput),
    "spotify": ToolContract("spotify", SpotifyInput, GenericToolOutput),
    "calendar": ToolContract("calendar", CalendarInput, CalendarOutput),
    "send_email": ToolContract("send_email", SendEmailInput, SendEmailOutput),
    "send_message": ToolContract("send_message", SendMessageInput, SendMessageOutput),
    "vision": ToolContract("vision", VisionInput, GenericToolOutput),
    "code_assistant": ToolContract("code_assistant", CodeAssistantInput, GenericToolOutput),
    "knowledge": ToolContract("knowledge", KnowledgeInput, GenericToolOutput),
    "organize_files": ToolContract("organize_files", OrganizeFilesInput, GenericToolOutput),
    "download_file": ToolContract("download_file", DownloadFileInput, DownloadFileOutput),
    "search_and_download": ToolContract("search_and_download", SearchAndDownloadInput, SearchAndDownloadOutput),
    "system_info": ToolContract("system_info", SystemInfoInput, GenericToolOutput),
    "datetime": ToolContract("datetime", DateTimeInput, GenericToolOutput),
    "weather": ToolContract("weather", WeatherInput, GenericToolOutput),
    "web_agent": ToolContract("web_agent", WebAgentInput, WebAgentOutput),
    "cad_generator": ToolContract("cad_generator", CadGeneratorInput, GenericToolOutput),
    "routines": ToolContract("routines", RoutinesInput, GenericToolOutput),
}


def get_contract(tool_name: str) -> Optional[ToolContract]:
    return CONTRACTS.get(tool_name)
