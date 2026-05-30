"""
配置管理模块
"""
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """应用配置"""
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Scopus (Elsevier)
    scopus_api_key: str = ""

    # PubMed (NCBI E-utilities)
    pubmed_api_key: str = ""

    # 搜索参数
    max_results_per_source: int = 10

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量和 .env 文件加载配置"""
        # 尝试加载 .env 文件
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())

        return cls(
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            scopus_api_key=os.environ.get("SCOPUS_API_KEY", ""),
            pubmed_api_key=os.environ.get("PUBMED_API_KEY", ""),
            max_results_per_source=int(os.environ.get("MAX_RESULTS_PER_SOURCE", "10")),
        )

    def validate(self) -> list[str]:
        """验证配置，返回错误列表"""
        errors = []
        if not self.deepseek_api_key or self.deepseek_api_key == "your_deepseek_api_key_here":
            errors.append("请设置 DEEPSEEK_API_KEY (在 .env 文件或环境变量中)")
        return errors
