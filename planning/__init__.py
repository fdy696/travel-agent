"""旅游规划领域包。

保持包入口轻量，不在 import planning 时隐式加载 LangChain/Deep Agents，
这样 models / repository 可以独立单测。
"""
