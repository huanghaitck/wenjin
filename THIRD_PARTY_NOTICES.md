# Third-party design references

Wenjin is built independently. The following open-source projects informed the 0.1 architecture and interaction design:

- NousResearch/hermes-agent (MIT): model providers, auxiliary task routing, Mixture of Agents, and editable soul concepts.
- badlogic/pi-mono (MIT): separation between provider APIs, agent loop, tools, state, and user interfaces.
- openai/codex (Apache-2.0): app-server, thread events, approvals, Skills, and MCP integration patterns.
- Model Context Protocol specification (Copyright Anthropic PBC; specification terms apply): prompts, resources, and tools control boundaries.

No source files from these projects are vendored in Wenjin 0.1. Any future vendored or adapted code must be listed here with its exact upstream revision and license.
