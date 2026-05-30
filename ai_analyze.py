import os
from pathlib import Path
from openai import BadRequestError, OpenAI

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),  # 如果您没有配置环境变量，请在此处替换您的API-KEY
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 填写DashScope服务base_url
)

file_object = client.files.create(file=Path("results.md"), purpose="file-extract")
print(file_object.id)

try:
    # 初始化messages列表
    completion = client.chat.completions.create(
        model="qwen-long",
        messages=[
            # sys1: 角色定义
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            # sys2: 文档内容（纯文本或file-id）
            # 请将 '{FILE_ID}'替换为您实际对话场景所使用的 fileid
            {'role': 'system', 'content': f'fileid://{file_object.id}'},
            # 当请求中包含第 2 条system message时，user消息内容长度限制在 9,000 Token 以内
            {'role': 'user', 'content': '这篇文章讲了什么?'}
        ],
        # 所有代码示例均采用流式输出，以清晰和直观地展示模型输出过程。如果您希望查看非流式输出的案例，请参见https://help.aliyun.com/zh/model-studio/text-generation
        stream=True,
        stream_options={"include_usage": True}
    )

    full_content = ""
    for chunk in completion:
        if chunk.choices and chunk.choices[0].delta.content:
            # 拼接输出内容
            full_content += chunk.choices[0].delta.content
            # print(chunk.model_dump())

        # 获取 token 使用情况
        if chunk.usage:
            print(f"总计 tokens: {chunk.usage.total_tokens}")

    print(full_content)

except BadRequestError as e:
    print(f"错误信息：{e}")
    print("请参考文档：https://help.aliyun.com/zh/model-studio/developer-reference/error-code")
