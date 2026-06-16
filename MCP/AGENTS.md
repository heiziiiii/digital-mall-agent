# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目定位

基于 Spring AI Alibaba的 **MCP 服务器**，把数码客服后端能力封装为 MCP 工具，通过 WebMVC SSE 暴露给大模型 Agent。本服务是工具提供方，不直接对话。

## 开发要求

### 编码规范

- 中文注释与日志，保持与现有代码一致的措辞风格。
- 代码尽量简洁

修改工具记得修改[src/main/java/com/digitalcs/mcp/tools/tool.md](src/main/java/com/digitalcs/mcp/tools/tool.md)文档
