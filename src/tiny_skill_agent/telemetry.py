"""OpenTelemetry ベースの OpenAI 呼び出し出力。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .utils import serialize_openai_response, truncate_text

DEFAULT_SERVICE_NAME = "tiny-skill-agent"
DEFAULT_TRACER_NAME = "tiny_skill_agent.openai"
MAX_EVENT_PAYLOAD_CHARS = 12000


class OpenAITelemetryEmitter:
    """OpenAI 呼び出しを OpenTelemetry span/event として出力する。"""

    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer

    def emit_chat_completion(
        self,
        *,
        request: dict[str, Any],
        attempt: int,
        duration_ms: float,
        response: Any | None = None,
        error: Exception | None = None,
        retryable: bool | None = None,
    ) -> None:
        """chat.completions 呼び出し結果を 1 span として記録する。"""
        status = "error" if error is not None else "ok"
        attributes = {
            "openai.api": "chat.completions",
            "openai.model": str(request.get("model") or ""),
            "openai.attempt": attempt,
            "openai.duration_ms": float(duration_ms),
            "openai.status": status,
        }
        if retryable is not None:
            attributes["openai.retryable"] = retryable
        if error is not None:
            attributes["error.type"] = type(error).__name__

        with self._tracer.start_as_current_span(
            "openai.chat.completions",
            attributes=attributes,
        ) as span:
            span.add_event(
                "openai.request",
                {"payload": self._stringify_payload(request)},
            )
            if error is not None:
                span.add_event(
                    "openai.error",
                    {
                        "error.type": type(error).__name__,
                        "error.message": truncate_text(
                            str(error),
                            MAX_EVENT_PAYLOAD_CHARS,
                        ),
                    },
                )
                if hasattr(span, "record_exception"):
                    span.record_exception(error)
                return

            span.add_event(
                "openai.response",
                {
                    "payload": self._stringify_payload(
                        serialize_openai_response(response)
                    )
                },
            )

    @staticmethod
    def _stringify_payload(payload: Any) -> str:
        return truncate_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            MAX_EVENT_PAYLOAD_CHARS,
        )


def build_openai_telemetry_emitter(
    file_path: Path | None = None,
    otlp_endpoint: str | None = None,
) -> OpenAITelemetryEmitter:
    """必要な exporter 群を持つ OpenTelemetry tracer を構築する。"""
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except ImportError as exc:
        raise SystemExit(
            "OpenTelemetry output requires `opentelemetry-sdk` and "
            "`opentelemetry-api`. Install project dependencies first."
        ) from exc
    if file_path is None and not otlp_endpoint:
        raise SystemExit(
            "OpenTelemetry output requires either a local telemetry file "
            "or an OTLP endpoint."
        )

    provider = TracerProvider(
        resource=Resource.create({"service.name": DEFAULT_SERVICE_NAME})
    )
    if file_path is not None:
        provider.add_span_processor(SimpleSpanProcessor(_JsonlSpanExporter(file_path)))
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as exc:
            raise SystemExit(
                "OTLP export requires `opentelemetry-exporter-otlp`."
            ) from exc
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        )
    tracer = provider.get_tracer(DEFAULT_TRACER_NAME, resolve_project_version())
    return OpenAITelemetryEmitter(tracer)


def resolve_project_version() -> str:
    """パッケージに定義した version を返す。"""
    return __version__


class _JsonlSpanExporter:
    """Span を JSONL としてローカルファイルへ出力する exporter。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="") as handle:
            for span in spans:
                handle.write(
                    json.dumps(self._serialize_span(span), ensure_ascii=False) + "\n"
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    @staticmethod
    def _serialize_span(span: Any) -> dict[str, Any]:
        parent = span.parent
        return {
            "name": span.name,
            "context": {
                "trace_id": f"{span.context.trace_id:032x}",
                "span_id": f"{span.context.span_id:016x}",
            },
            "parent_span_id": (
                f"{parent.span_id:016x}" if parent is not None else None
            ),
            "start_time_unix_nano": span.start_time,
            "end_time_unix_nano": span.end_time,
            "status": {
                "status_code": getattr(
                    span.status.status_code,
                    "name",
                    str(span.status.status_code),
                ),
                "description": span.status.description,
            },
            "attributes": dict(span.attributes),
            "events": [
                {
                    "name": event.name,
                    "timestamp_unix_nano": event.timestamp,
                    "attributes": dict(event.attributes),
                }
                for event in span.events
            ],
            "resource": dict(span.resource.attributes),
            "instrumentation_scope": {
                "name": span.instrumentation_scope.name,
                "version": span.instrumentation_scope.version,
            },
        }
