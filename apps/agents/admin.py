from django.contrib import admin

from .models import AgentRun, ApprovalRequest, Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "organization", "created_at")
    list_filter = ("organization",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "content", "created_at")
    list_filter = ("organization", "role")


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "trigger", "route", "status", "input_tokens", "latency_ms")
    list_filter = ("organization", "trigger", "route", "status")


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "invoice", "organization", "decided_at")
    list_filter = ("organization", "kind", "status")
